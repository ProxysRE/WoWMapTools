"""Check village routes, population placements, and transition destinations.

This discrete QA treats ordinary doors as openable. Windows, solid walls, and
selected furniture footprints block a five-foot disc. It is not Foundry physics.
"""
import argparse
from collections import deque
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from wowmap.foundry import compile_scene
from wowmap.models import RawAssets,mesh_data


def check(packages):
    plans={k:json.loads((ROOT/'examples'/('alderford-'+k+'.json')).read_text()) for k in ['gate','market','civic']}
    request=json.loads((ROOT/'requests/builder/alderford.json').read_text())
    region_keys={k:{r['id'] for r in p['foundry']['regions']} for k,p in plans.items()}
    geometry={};report={};step=.2;radius=.5
    yy,xx=np.mgrid[0:36:step,0:48:step];xx=xx+step/2;yy=yy+step/2
    with RawAssets(packages) as raw:
        for key,p in plans.items():
            if key!='gate':
                assert not any('palisade' in o['id'] for o in p['objects'])
                assert not any('palisade' in w['id'] for w in p['walls'])
            scene=compile_scene(p,'alderford-check',key,region_keys,'wowmap/check/'+key)
            blocked=np.zeros(xx.shape,dtype=bool)
            for w in scene['walls']:
                if not w['move'] or w['door']:continue
                ax,ay,bx,by=[c/p['pixels_per_cell'] for c in w['c']]
                vx,vy=bx-ax,by-ay;length=math.hypot(vx,vy)
                along=((xx-ax)*vx+(yy-ay)*vy)/length
                across=(-(xx-ax)*vy+(yy-ay)*vx)/length
                blocked|=np.hypot(np.maximum(np.maximum(-along,along-length),0),np.maximum(np.abs(across)-.08,0))<radius
            # Bounding rectangles intentionally err on the conservative side.
            selected=[]
            for o in p['objects']:
                if not any(tag in o['id'] for tag in ['bed','table','counter','shelf','barrel','crate','wagon','anvil','stove','bench','well']):continue
                model=o['model']
                if model not in geometry:
                    vertices,_,_=mesh_data(raw,model)
                    xyz=vertices['position'][:,:2];span=xyz.max(axis=0)-xyz.min(axis=0)
                    geometry[model]=span/max(span)
                width,height=geometry[model]*o['size_cells']*o.get('scale',1)
                angle=math.radians(o.get('rotation',0));c,s=math.cos(angle),math.sin(angle)
                dx=xx-o['position'][0];dy=yy-o['position'][1]
                qx=c*dx+s*dy;qy=-s*dx+c*dy
                blocked|=np.hypot(np.maximum(np.abs(qx)-width/2,0),np.maximum(np.abs(qy)-height/2,0))<radius
                selected.append(o['id'])
            start=(int(18/step),int(24/step)) if key=='market' else (int((32 if key=='gate' else 12)/step),int(24/step))
            if blocked[start]:raise ValueError(key+': main route start is blocked')
            queue=deque([start]);seen={start}
            while queue:
                y,x=queue.popleft()
                for dy,dx in [(0,1),(0,-1),(1,0),(-1,0)]:
                    pos=ny,nx=y+dy,x+dx
                    if 0<=ny<blocked.shape[0] and 0<=nx<blocked.shape[1] and not blocked[ny,nx] and pos not in seen:
                        seen.add(pos);queue.append(pos)
            reachable=np.zeros_like(blocked)
            for y,x in seen:reachable[y,x]=True
            targets=[]
            # Test exact token centres, not only nearby empty floor.
            for item in [r for r in request['placements'] if r['scene']==key]:
                x,y=item['position'];cy,cx=int(y/step),int(x/step)
                ok=bool(reachable[cy,cx]);targets.append(dict(name=item['id'],kind='token',reachable=ok))
            for loc in p['locations']:
                x,y=loc.get('access_position',loc['position']);near=(xx-x)**2+(yy-y)**2<=1.6**2
                targets.append(dict(name=loc['name'],kind='location',reachable=bool((reachable&near).any())))
            for r in p['foundry']['regions']:
                if r['id'].startswith(('arrival','exit')):
                    a,b,c,d=r['shapes'][0]['bounds'];inside=(xx>=a)&(xx<=c)&(yy>=b)&(yy<=d)
                    targets.append(dict(name=r['id'],kind='transition',reachable=bool((reachable&inside).any())))
            failures=[r for r in targets if not r['reachable']]
            report[key]=dict(token_diameter_cells=1,step_cells=step,large_props=len(selected),targets=targets,
                             walls=len(scene['walls']),lights=len(scene['lights']),regions=len(scene['regions']))
            print(key,json.dumps(failures,ensure_ascii=False),flush=True)
            if failures:raise ValueError(key+': unreachable targets')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--packages',required=True)
    parser.add_argument('--out',default=str(ROOT/'output/alderford-layout-check.json'))
    args=parser.parse_args();report=check(args.packages)
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
