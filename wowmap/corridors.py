"""Compile authored orthogonal corridors into one floor polygon and boundary walls.

The half-cell occupancy grid is construction geometry, not a random maze or a
substitute for collision QA against the exported Foundry wall documents.
"""
from collections import defaultdict,deque
import math
import numpy as np


def compile_network(config,size):
    unit=config.get('unit',.5)
    if unit not in (.25,.5,1):raise ValueError('Corridor unit must be .25, .5 or 1 cell')
    w,h=[round(v/unit) for v in size];mask=np.zeros((h,w),dtype=bool)
    ids=set();lengths=[];widths=[]
    def rectangle(bounds):
        if len(bounds)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in bounds):raise ValueError('Invalid corridor rectangle')
        a,b,c,d=bounds
        if not 0<=a<c<=size[0] or not 0<=b<d<=size[1]:raise ValueError('Corridor rectangle outside scene')
        coords=[round(v/unit) for v in bounds]
        if any(abs(v/unit-n)>1e-6 for v,n in zip(bounds,coords)):raise ValueError('Corridor edges must align to construction unit')
        x0,y0,x1,y1=coords;mask[y0:y1,x0:x1]=True
    for row in config.get('rooms',[]):
        if row['id'] in ids:raise ValueError('Duplicate corridor/room id')
        ids.add(row['id']);rectangle(row['bounds'])
    for row in config.get('corridors',[]):
        if row['id'] in ids:raise ValueError('Duplicate corridor/room id')
        ids.add(row['id']);width=row['width']
        if type(width) not in (int,float) or not 1<=width<=6:raise ValueError('Corridor width must be 1..6 cells')
        pts=row['points']
        if len(pts)<2:raise ValueError('Corridor needs two points')
        widths.append(width)
        for a,b in zip(pts,pts[1:]):
            if len(a)!=2 or len(b)!=2 or (a[0]!=b[0] and a[1]!=b[1]) or a==b:raise ValueError('Corridors require nonzero orthogonal segments')
            lengths.append(abs(b[0]-a[0])+abs(b[1]-a[1]))
            rectangle([min(a[0],b[0])-width/2,min(a[1],b[1])-width/2,max(a[0],b[0])+width/2,max(a[1],b[1])+width/2])
    if not mask.any():raise ValueError('Empty corridor network')
    # All floor area must be connected; a disconnected room is an authoring error.
    start=tuple(np.argwhere(mask)[0]);todo=deque([start]);seen={start}
    while todo:
        y,x=todo.popleft()
        for yy,xx in [(y-1,x),(y+1,x),(y,x-1),(y,x+1)]:
            if 0<=yy<h and 0<=xx<w and mask[yy,xx] and (yy,xx) not in seen:seen.add((yy,xx));todo.append((yy,xx))
    if len(seen)!=int(mask.sum()):raise ValueError('Disconnected corridor floor')
    edges=set()
    for y,x in np.argwhere(mask):
        x=int(x);y=int(y)
        if y==0 or not mask[y-1,x]:edges.add(((x,y),(x+1,y)))
        if x==w-1 or not mask[y,x+1]:edges.add(((x+1,y),(x+1,y+1)))
        if y==h-1 or not mask[y+1,x]:edges.add(((x+1,y+1),(x,y+1)))
        if x==0 or not mask[y,x-1]:edges.add(((x,y+1),(x,y)))
    outgoing=defaultdict(list)
    for a,b in edges:outgoing[a].append(b)
    if any(len(v)!=1 for v in outgoing.values()):raise ValueError('Floor touches itself at a corner; separate or join passages explicitly')
    loops=[]
    while edges:
        a,b=min(edges);start=a;points=[a]
        while True:
            if (a,b) not in edges:raise ValueError('Broken corridor boundary')
            edges.remove((a,b));a=b
            if a==start:break
            points.append(a);b=outgoing[a][0]
        # Remove collinear grid vertices for compact polygons and native walls.
        simple=[]
        for i,p in enumerate(points):
            prev=points[i-1];nxt=points[(i+1)%len(points)]
            if (p[0]-prev[0])*(nxt[1]-p[1])!=(p[1]-prev[1])*(nxt[0]-p[0]):simple.append([p[0]*unit,p[1]*unit])
        loops.append(simple)
    def area(points):return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))/2
    outer=[p for p in loops if area(p)>0];holes=[p for p in loops if area(p)<0]
    if len(outer)!=1:raise ValueError('Expected a single connected floor boundary')
    shape=dict(type='polygon',points=outer[0],feather=0,cutouts=[dict(type='polygon',points=p,feather=0) for p in holes])
    prefix=config.get('id','corridor');walls=[]
    for loop_index,points in enumerate([outer[0]]+sorted(holes)):
        for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
            walls.append(dict(id=f'{prefix}-boundary-{loop_index}-{i}',points=[a,b],thickness=config.get('wall_thickness',.28),asset=config['wall_asset'],tile_cells=1.4))
    floors=[dict(id=prefix+'-floor',asset=config['floor_asset'],tile_cells=1.15,tint=config.get('floor_tint','#a9a3a0'),texture_variation=.07,shape=shape)]
    metrics=dict(area_cells=float(mask.sum()*unit*unit),rooms=len(config.get('rooms',[])),corridors=len(widths),
                 declared_widths=sorted(set(widths)),longest_authored_straight_cells=max(lengths,default=0),
                 physical_loops=len(holes),boundary_segments=len(walls),connected=True)
    return floors,walls,metrics
