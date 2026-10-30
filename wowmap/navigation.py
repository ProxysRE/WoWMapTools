"""Independent walkability checks from floor polygons and exported native walls."""
from collections import deque
import math
import numpy as np


def inside(shape,x,y):
    kind=shape['type']
    if kind in ('rectangle','ellipse'):
        a,b,c,d=shape['bounds']
        if kind=='rectangle':result=(x>=a)&(x<c)&(y>=b)&(y<d)
        else:result=((x-(a+c)/2)/((c-a)/2))**2+((y-(b+d)/2)/((d-b)/2))**2<1
    elif kind=='polygon':
        result=np.zeros(x.shape,dtype=bool);pts=shape['points']
        for (ax,ay),(bx,by) in zip(pts,pts[1:]+pts[:1]):
            if ay==by:continue
            result^=((ay>y)!=(by>y))&(x<(bx-ax)*(y-ay)/(by-ay)+ax)
    else:raise ValueError('Navigation supports exact rectangles, ellipses and polygons')
    for hole in shape.get('cutouts',[]):result&=~inside(hole,x,y)
    return result


def walk_mask(plan,scene,token_cells=1,step=.25):
    if token_cells<=0 or step<=0:raise ValueError('Invalid navigation scale')
    w,h=plan['size_cells'];ys,xs=np.mgrid[step/2:h:step,step/2:w:step]
    radius=token_cells/2;valid=np.ones(xs.shape,dtype=bool)
    # Check all footprint corners plus center against the union of floor layers.
    for dx,dy in [(0,0),(-radius,-radius),(-radius,radius),(radius,-radius),(radius,radius)]:
        cover=((xs+dx>=0)&(xs+dx<w)&(ys+dy>=0)&(ys+dy<h)) if plan.get('navigation',{}).get('base_walkable',False) else np.zeros(xs.shape,dtype=bool)
        for floor in plan.get('floors',[]):cover|=inside(floor['shape'],xs+dx,ys+dy)
        valid&=cover
    ppc=plan['pixels_per_cell']
    for wall in scene['walls']:
        if wall['door'] or not wall['move']:continue
        x1,y1,x2,y2=[v/ppc for v in wall['c']]
        # Native wall collision: expand by the square token footprint.
        if x1==x2:blocked=(abs(xs-x1)<radius)&(ys>min(y1,y2)-radius)&(ys<max(y1,y2)+radius)
        elif y1==y2:blocked=(abs(ys-y1)<radius)&(xs>min(x1,x2)-radius)&(xs<max(x1,x2)+radius)
        else:
            dx=x2-x1;dy=y2-y1;length=dx*dx+dy*dy
            t=np.clip(((xs-x1)*dx+(ys-y1)*dy)/length,0,1)
            blocked=(xs-x1-t*dx)**2+(ys-y1-t*dy)**2<(radius*math.sqrt(2))**2
        valid&=~blocked
    return valid,step


def find_path(mask,step,start,end,exclude=None):
    def index(point):return int(point[1]/step),int(point[0]/step)
    a=index(start);b=index(end);h,w=mask.shape
    if not all(0<=y<h and 0<=x<w and mask[y,x] for y,x in [a,b]):return None
    queue=deque([a]);parent={a:None}
    while queue:
        p=queue.popleft()
        if p==b:
            path=[]
            while p is not None:path.append(((p[1]+.5)*step,(p[0]+.5)*step));p=parent[p]
            return path[::-1]
        for dy,dx in [(0,1),(1,0),(0,-1),(-1,0)]:
            n=(p[0]+dy,p[1]+dx)
            if not 0<=n[0]<h or not 0<=n[1]<w or n in parent or not mask[n]:continue
            if exclude and exclude((n[1]+.5)*step,(n[0]+.5)*step):continue
            parent[n]=p;queue.append(n)
    return None
