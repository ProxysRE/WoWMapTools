"""Check authored inn circulation with a 5-foot token and real M2 XY footprints.

Doors are considered operable/open. This is layout QA, not a Foundry physics emulator.
Only selected large props block the simulation; rugs, dishes and stair treads do not.
"""
import argparse
from collections import deque
import json
import math
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wowmap.models import RawAssets,mesh_data
from wowmap.foundry import compile_scene

TARGETS={
 'ground':dict(start=[13.3,23.2],hall=[13.3,14],parlour=[12.1,9.25],kitchen=[22.15,10.5],bar_service=[22.6,14.4],pantry=[27.1,14.5],reception=[23.1,21.2],stairs=[26.9,23.2]),
 'upper':dict(start=[26.9,17.5],corridor=[23.8,14.5],room_a=[9.15,10.1],room_b=[13.1,9.8],room_c=[20.2,10.1],room_d=[26.1,10.1],dorm=[9.8,20.2],owner=[17.2,20.5])}


def check(plans,raw):
    keys={k:{r['id'] for r in p['foundry']['regions']} for k,p in plans.items()}
    all_results={};memo={};step=.08;radius=.5
    xx,yy=np.meshgrid(np.arange(6.3,28.71,step),np.arange(5.3,23.71,step))
    for key,plan in plans.items():
        scene=compile_scene(plan,'layout-check',key,keys,'wowmap/layout/'+key)
        blocked=np.zeros(xx.shape,dtype=bool)
        for w in scene['walls']:
            if not w['move'] or w['door']:continue
            ax,ay,bx,by=[v/plan['pixels_per_cell'] for v in w['c']]
            vx=bx-ax;vy=by-ay;den=vx*vx+vy*vy
            length=math.sqrt(den)
            along=((xx-ax)*vx+(yy-ay)*vy)/length
            across=(-(xx-ax)*vy+(yy-ay)*vx)/length
            blocked|=np.hypot(np.maximum(np.maximum(-along,along-length),0),np.maximum(np.abs(across)-.1,0))<radius
        selected=[]
        for obj in plan['objects']:
            name=Path(obj['model']).stem
            if not any(t in name for t in ['table','chair','bench','bed','counter','shelf','keg','crate','barrel','stove']):continue
            if obj['model'] not in memo:
                v,_,_=mesh_data(raw,obj['model']);low=v['position'][:,:2].min(axis=0);high=v['position'][:,:2].max(axis=0);memo[obj['model']]=high-low
            span=memo[obj['model']];w,h=span/max(span)*obj['size_cells']
            angle=math.radians(obj.get('rotation',0));c,s=math.cos(angle),math.sin(angle)
            dx=xx-obj['position'][0];dy=yy-obj['position'][1]
            qx=c*dx+s*dy;qy=-s*dx+c*dy
            blocked|=np.hypot(np.maximum(np.abs(qx)-w/2,0),np.maximum(np.abs(qy)-h/2,0))<radius
            selected.append(obj['id'])
        def point(p):return (round((p[1]-5.3)/step),round((p[0]-6.3)/step))
        start=point(TARGETS[key]['start'])
        if blocked[start]:raise ValueError(f'{key}: start point obstructed')
        queue=deque([start]);dist={start:0}
        while queue:
            y,x=queue.popleft()
            for dy,dx in [(0,1),(1,0),(0,-1),(-1,0)]:
                ny,nx=y+dy,x+dx
                if 0<=ny<blocked.shape[0] and 0<=nx<blocked.shape[1] and not blocked[ny,nx] and (ny,nx) not in dist:
                    dist[ny,nx]=dist[(y,x)]+1;queue.append((ny,nx))
        result={name:dict(reachable=point(p) in dist,distance_cells=round(dist[point(p)]*step,2) if point(p) in dist else None) for name,p in TARGETS[key].items()}
        all_results[key]=dict(token_diameter_cells=radius*2,grid_step_cells=step,large_props=len(selected),targets=result)
        print(key,json.dumps(result),flush=True)
        failed=[name for name,item in result.items() if not item['reachable']]
        if failed:raise ValueError(f'{key}: unreachable test points: {failed}')
    return all_results


def main():
    p=argparse.ArgumentParser();p.add_argument('--packages',required=True);p.add_argument('--out',default='output/old-oak-layout-check.json');a=p.parse_args()
    plans={k:json.loads(Path('examples/old-oak-'+k+'.json').read_text()) for k in TARGETS}
    with RawAssets(a.packages) as raw:result=check(plans,raw)
    Path(a.out).write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':main()
