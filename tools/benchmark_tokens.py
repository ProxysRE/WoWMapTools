"""Alternate current/reference token builds with byte comparison, using private assets.

The reference is read from a local Git commit into a temporary Python package;
no checkout is modified. Child imports are outside the timed section. Each sample
uses fresh DBC/model sessions. No rendering, encoding or image size is reduced.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
CHILD='''import json,time,hashlib
from unittest.mock import patch
from wowmap.tokens import TokenAssets
from wowmap.characters import CharacterDB
args=json.load(__import__('sys').stdin);count=[0];original=CharacterDB.assemble
def assemble(*a,**k):count[0]+=1;return original(*a,**k)
start=time.perf_counter()
tokens=TokenAssets(args['dbc'],args['models'])
with patch.object(CharacterDB,'assemble',assemble),tokens.session():
 for options in args['options']:tokens.pair(options)
print(json.dumps(dict(seconds=time.perf_counter()-start,assemblies=count[0],media=sorted(tokens.images))))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',required=True);p.add_argument('--dbc-assets',required=True);p.add_argument('--model-assets',required=True)
    p.add_argument('--request',default='requests/builder/all-races.json');p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--out',default='output/token-benchmark.json')
    args=p.parse_args()
    if not 1<=args.repeats<=10:p.error('--repeats must be 1..10')
    commit=subprocess.check_output(['git','rev-parse','--verify',args.reference+'^{commit}'],cwd=ROOT,text=True).strip()
    entries=json.loads((ROOT/args.request).read_text(encoding='utf-8'))['documents']
    options=[r['appearance'] for r in entries if r['id'] in {'human-male','orc-female','tauren-male'}]
    if len(options)!=3:p.error('Request must contain human-male, orc-female and tauren-male')
    payload=json.dumps(dict(dbc=str(Path(args.dbc_assets).resolve()),models=str(Path(args.model_assets).resolve()),options=options))
    results=dict(reference=[],current=[])
    with tempfile.TemporaryDirectory(prefix='wowmap-benchmark-') as temp:
        temp=Path(temp);reference=temp/'reference';reference.mkdir();work=temp/'work';work.mkdir()
        names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'wowmap'],cwd=ROOT,text=True).splitlines()
        for name in names:
            if not name.endswith('.py'):continue
            path=reference/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(subprocess.check_output(['git','show',commit+':'+name],cwd=ROOT))
        for repeat in range(args.repeats):
            for label in (['reference','current'] if repeat%2==0 else ['current','reference']):
                env=dict(os.environ,PYTHONPATH=str(reference if label=='reference' else ROOT))
                run=subprocess.run([sys.executable,'-c',CHILD],input=payload,cwd=work,env=env,text=True,capture_output=True,check=True)
                results[label].append(json.loads(run.stdout))
    hashes=results['reference'][0]['media']
    if not all(row['media']==hashes for samples in results.values() for row in samples):raise ValueError('Image bytes differ')
    for samples in results.values():
        for row in samples:row.pop('media')
    before=statistics.median(r['seconds'] for r in results['reference']);after=statistics.median(r['seconds'] for r in results['current'])
    result=dict(reference_commit=commit,samples=results,byte_identical_images=len(hashes),reference_median_seconds=before,current_median_seconds=after,reduction_percent=(1-after/before)*100,scope='3 equipped bodies, 6 views, fresh sessions; alternating local measurements')
    output=Path(args.out);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))


if __name__=='__main__':main()
