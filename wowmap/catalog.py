"""Search a full resource catalog and map scene requirements to independent ZIP packages."""
import argparse
import gzip
import json
from pathlib import Path
import re
from .planning import expand
from .render import resource_names,validate
from .models import RawAssets,inspect_model


def load(path):
    with gzip.open(path,'rt',encoding='utf-8') as stream:return {r['path']:r for r in (json.loads(line) for line in stream)}


def search(records,query,extension=None,limit=20):
    tokens=re.findall(r'[\w]+',query.lower());hits=[]
    for name,record in records.items():
        if extension and not name.endswith(extension.lower()):continue
        if not all(token in name for token in tokens):continue
        basename=Path(name).stem
        score=sum(5 if token in basename else 1 for token in tokens)
        hits.append((score,name,record))
    return [record for score,name,record in sorted(hits,key=lambda row:(-row[0],row[1]))[:limit]]


def requirements(plan,records,raw=None):
    plan,report=expand(plan);validate(plan)
    wanted=resource_names(plan);uninspected=[];replaceable=[];model_errors=[]
    for model in sorted({obj['model'] for obj in plan.get('objects',[])}):
        wanted.add(model)
        if raw is not None and raw.has(model):
            try:info=inspect_model(raw,model)
            except (ValueError,KeyError) as error:
                model_errors.append(dict(model=model,error=str(error)));uninspected.append(model);continue
            wanted.update(info['required_skins']);wanted.update(info['required_textures'])
            if info['used_replaceable_texture_types']:replaceable.append(model)
            if not info['inspection_complete']:uninspected.append(model)
        else:uninspected.append(model)
    found=[];unknown=[]
    for name in sorted(wanted):
        if name not in records:unknown.append(name);continue
        entry=records[name]
        found.append(dict(path=name,package=entry['package'],id=entry['id'],available=raw.has(name) if raw else False))
    missing=[name for name in sorted(wanted) if raw is None or not raw.has(name)]
    return dict(resources=found,missing_packages=sorted({r['package'] for r in found if not r['available']}),
                unavailable_resources=missing,model_errors=model_errors,
                not_in_catalog=unknown,models_needing_inspection=uninspected,replaceable_texture_models=replaceable,
                dependencies_complete=not uninspected and not replaceable and not unknown and not missing and not model_errors,
                note='Material references require the M2 and selected SKIN; this is not an automatic downloader.')


def main():
    parser=argparse.ArgumentParser(description='Search resources or prepare a scene download list')
    parser.add_argument('command',choices=['search','plan'])
    parser.add_argument('--catalog',required=True)
    parser.add_argument('--query',default='')
    parser.add_argument('--extension')
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--plan')
    parser.add_argument('--packages')
    parser.add_argument('--out')
    args=parser.parse_args()
    try:
        records=load(args.catalog)
        if args.command=='search':result=search(records,args.query,args.extension,args.limit)
        else:
            if not args.plan:raise ValueError('--plan is required')
            plan=json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
            if args.packages:
                with RawAssets(args.packages) as raw:result=requirements(plan,records,raw)
            else:result=requirements(plan,records)
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if args.out:
            out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(text,encoding='utf-8')
        else:print(text)
        return 0
    except (OSError,ValueError,KeyError) as error:print(f'ERROR: {error}');return 1


if __name__=='__main__':raise SystemExit(main())
