"""Headless batch adapter for the unchanged Foundry JSON Builder project.

Run from any directory. Request and source paths are resolved inside this repository.
Outputs are staged and published only after every document passes the real builder.
"""
import argparse
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
BUILDER=ROOT/'foundry_builder'
sys.path.insert(0,str(BUILDER))
import builder_app
import build_enhancement_module
import project_config


def read_json(path):
    if path.stat().st_size>4*1024*1024:raise ValueError('JSON input exceeds 4 MiB')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def source_path(path):
    if not isinstance(path,str) or not path:raise ValueError('Source path is required')
    target=(ROOT/path).resolve()
    if not target.is_relative_to(ROOT) or target.suffix.lower()!='.json':raise ValueError('Input must be a JSON file inside the repository')
    return target


def build_batch(request_path,output,icon_assets=None,dbc_assets=None,model_assets=None):
    with ExitStack() as resources:
        return _build_batch(request_path,output,icon_assets,dbc_assets,model_assets,resources)


def _build_batch(request_path,output,icon_assets,dbc_assets,model_assets,resources):
    request_path=source_path(str(request_path));request=read_json(request_path)
    if request.get('format')!='foundry-builder.batch/1':raise ValueError('Expected foundry-builder.batch/1')
    entries=request.get('documents')
    if not isinstance(entries,list) or not 1<=len(entries)<=200:raise ValueError('Batch must contain 1..200 documents')
    output=Path(output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('Output directory must be empty')
    if any(not isinstance(entry,dict) for entry in entries):raise ValueError('Each document entry must be an object')
    prepared=[];ids=set();icons=None;tokens=None;icon_bindings=[]
    if any(entry.get('icons') or entry.get('item_icons') for entry in entries):
        if icon_assets is None:raise ValueError('This request needs --icon-assets pointing to a private icon export')
        sys.path.insert(0,str(ROOT))
        from wowmap.icons import IconAssets
        icons=IconAssets(icon_assets)
    if any('appearance' in entry for entry in entries):
        if dbc_assets is None or model_assets is None:raise ValueError('Creature appearances need --dbc-assets and --model-assets')
        sys.path.insert(0,str(ROOT))
        from wowmap.tokens import TokenAssets
        tokens=resources.enter_context(TokenAssets(dbc_assets,model_assets).session())
    for entry in entries:
        key=entry['id']
        if not isinstance(key,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',key) or key in ids:raise ValueError('Document ids must be unique ASCII slugs')
        ids.add(key);mode=entry['mode'];source=read_json(source_path(entry['source']))
        outcome=builder_app.build_document(mode,copy.deepcopy(source),source_name=entry['source'])
        binding_start=len(icons.bindings) if icons else 0
        if 'icons' in entry:
            if not isinstance(entry['icons'],dict):raise ValueError('icons must be an object')
            if entry['icons']:
                if outcome.kind=='enhancement_set':raise ValueError('Icon bindings for enhancement_set archives are not supported')
                outcome.document=icons.bind(outcome.document,entry['icons'])
        if 'item_icons' in entry:
            if not isinstance(entry['item_icons'],dict):raise ValueError('item_icons must be an object')
            if entry['item_icons']:
                if outcome.kind!='actor':raise ValueError('item_icons belongs to an NPC document')
                start=len(icons.bindings)
                candidate=icons.bind_items(outcome.document,entry['item_icons'])
                old={row['pointer'] for row in icons.bindings[binding_start:start]}
                if old & {row['pointer'] for row in icons.bindings[start:]}:
                    raise ValueError('icons and item_icons target the same image')
                outcome.document=candidate
        if icons:
            icon_bindings.extend(dict(document=key,**row) for row in icons.bindings[binding_start:])
        if 'appearance' in entry:
            if outcome.kind!='actor':raise ValueError('Creature appearance belongs to an NPC document')
            options=entry['appearance']
            if not isinstance(options,dict):raise ValueError('appearance must be an object')
            conflicts={'/prototypeToken/texture/src'}
            if options.get('actor_image',True):conflicts.add('/img')
            if conflicts & set(entry.get('icons',{})):raise ValueError('Icon and appearance target the same image')
            images=tokens.pair(options)
            outcome.document.setdefault('prototypeToken',{}).setdefault('texture',{})['src']=images['token']
            if images['portrait']:outcome.document['img']=images['portrait']
        prepared.append((key,outcome))
    actors={key:out.document for key,out in prepared if out.kind=='actor'}
    placements=copy.deepcopy(request.get('placements',[]))
    population=dict(format='wowmap.population/1',targets=dict(dnd5e=project_config.DND5E_VERSION),
                    actors=[dict(key=key,document=doc) for key,doc in actors.items()],placements=placements)
    media=(list(icons.media.values()) if icons else [])+(list(tokens.media.values()) if tokens else [])
    if media:population['media']=media
    # Shared validator checks source population independently of any rendered map.
    sys.path.insert(0,str(ROOT))
    from wowmap.population import validate_population
    validate_population(population)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent,prefix='.builder-stage-') as temporary:
        stage=Path(temporary);rows=[]
        if icons:icons.write(stage)
        if tokens:tokens.write(stage)
        review_files=icons.review(stage,icon_bindings) if icons else []
        if icon_bindings:
            (stage/'icon-bindings.json').write_text(json.dumps(icon_bindings,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        for key,outcome in prepared:
            extension='.zip' if outcome.kind=='enhancement_set' else '.json'
            dest=stage/(key+extension)
            if outcome.kind=='enhancement_set':
                _,module_report=build_enhancement_module.build_archive(outcome.document,dest)
                outcome.report['module']=module_report
            else:dest.write_text(json.dumps(outcome.document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            report=stage/(key+'.report.json');report.write_text(json.dumps(outcome.report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            rows.append(dict(id=key,mode=outcome.builder_key,file=dest.name,report=report.name,sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
        if actors:(stage/'population.json').write_text(json.dumps(population,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        result=dict(format='foundry-builder.result/1',request=str(request_path.relative_to(ROOT)),targets=project_config.TARGETS,documents=rows,
                    population='population.json' if actors else None,media=media,icon_reviews=review_files)
        if media:
            (stage/'INSTALL_MEDIA.txt').write_text(
                'Copy the included wowmap folder into your Foundry server user Data folder.\n'
                'Images must exist before importing the JSON documents. Merge folders; keep existing files.\n'
                'Images use content hashes and include selected icons and/or creature tokens.\n',encoding='utf-8')
        (stage/'build-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if output.exists():output.rmdir()
        shutil.move(str(stage),str(output))
    return result


def main():
    parser=argparse.ArgumentParser(description='Build Foundry JSON without opening the GUI')
    parser.add_argument('request');parser.add_argument('--out',default='output/builder')
    parser.add_argument('--icon-assets',help='Private export folder with icon catalog and ZIPs')
    parser.add_argument('--dbc-assets',help='Private folder of exported DBC ZIPs')
    parser.add_argument('--model-assets',help='Private folder of model, SKIN and texture ZIPs')
    args=parser.parse_args()
    try:print(json.dumps(build_batch(args.request,args.out,args.icon_assets,args.dbc_assets,args.model_assets),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,builder_app.AppBuildError,build_enhancement_module.EnhancementModuleBuildError) as error:
        parser.exit(1,f'ERROR: {error}\n')


if __name__=='__main__':main()
