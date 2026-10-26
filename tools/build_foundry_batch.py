"""Headless batch adapter for the unchanged Foundry JSON Builder project.

Run from any directory. Request and source paths are resolved inside this repository.
Outputs are staged and published only after every document passes the real builder.
"""
import argparse
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


def build_batch(request_path,output):
    request_path=source_path(str(request_path));request=read_json(request_path)
    if request.get('format')!='foundry-builder.batch/1':raise ValueError('Expected foundry-builder.batch/1')
    entries=request.get('documents')
    if not isinstance(entries,list) or not 1<=len(entries)<=200:raise ValueError('Batch must contain 1..200 documents')
    output=Path(output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('Output directory must be empty')
    prepared=[];ids=set()
    for entry in entries:
        key=entry['id']
        if not isinstance(key,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',key) or key in ids:raise ValueError('Document ids must be unique ASCII slugs')
        ids.add(key);mode=entry['mode'];source=read_json(source_path(entry['source']))
        outcome=builder_app.build_document(mode,copy.deepcopy(source),source_name=entry['source'])
        prepared.append((key,outcome))
    actors={key:out.document for key,out in prepared if out.kind=='actor'}
    placements=copy.deepcopy(request.get('placements',[]))
    for placement in placements:
        if placement.get('actor') not in actors:raise ValueError('Placement must reference a built NPC id')
    population=dict(format='wowmap.population/1',targets=dict(dnd5e=project_config.DND5E_VERSION),
                    actors=[dict(key=key,document=doc) for key,doc in actors.items()],placements=placements)
    # Shared validator checks source population independently of any rendered map.
    if placements:
        sys.path.insert(0,str(ROOT))
        from wowmap.population import validate_population
        validate_population(population)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent,prefix='.builder-stage-') as temporary:
        stage=Path(temporary);rows=[]
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
                    population='population.json' if actors else None)
        (stage/'build-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if output.exists():output.rmdir()
        shutil.move(str(stage),str(output))
    return result


def main():
    parser=argparse.ArgumentParser(description='Build Foundry JSON without opening the GUI')
    parser.add_argument('request');parser.add_argument('--out',default='output/builder')
    args=parser.parse_args()
    try:print(json.dumps(build_batch(args.request,args.out),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,builder_app.AppBuildError,build_enhancement_module.EnhancementModuleBuildError) as error:
        parser.exit(1,f'ERROR: {error}\n')


if __name__=='__main__':main()
