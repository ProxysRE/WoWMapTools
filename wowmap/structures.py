"""Textured structural geometry and openings; shared coordinates for future VTT export."""
import math
import numpy as np
from PIL import Image,ImageDraw
from .geometry import validate_shape
from .objects import finite,pair


def wall_parts(wall):
    a=np.asarray(wall['points'][0],dtype=float);b=np.asarray(wall['points'][1],dtype=float)
    length=float(np.linalg.norm(b-a))
    if length<=0:raise ValueError('Wall segment has zero length')
    direction=(b-a)/length
    intervals=[]
    for opening in wall.get('openings',[]):
        width=finite(opening['width'],'opening width');at=finite(opening['at'],'opening at')
        start=at-width/2;end=at+width/2
        if width<=0 or start<0 or end>length:raise ValueError('Opening lies outside wall segment')
        intervals.append((start,end,opening))
    intervals.sort(key=lambda item:item[0]);cursor=0;pieces=[];openings=[]
    for start,end,opening in intervals:
        if start<cursor:raise ValueError('Wall openings overlap')
        if start>cursor:pieces.append((a+direction*cursor,a+direction*start))
        openings.append((a+direction*start,a+direction*end,opening));cursor=end
    if cursor<length:pieces.append((a+direction*cursor,b))
    return pieces,openings


def validate_structures(plan):
    ids=set()
    for floor in plan.get('floors',[]):
        if floor['id'] in ids:raise ValueError('Duplicate structure id')
        ids.add(floor['id']);validate_shape(floor['shape'])
    for wall in plan.get('walls',[]):
        if wall['id'] in ids:raise ValueError('Duplicate structure id')
        ids.add(wall['id'])
        if len(wall['points'])!=2:raise ValueError('Each wall needs exactly two endpoints')
        for point in wall['points']:pair(point,'wall point')
        if not .02<=finite(wall['thickness'],'wall thickness')<=5:raise ValueError('wall thickness must be .02..5 cells')
        if finite(wall.get('tile_cells',2),'wall tile_cells')<=0:raise ValueError('wall tile_cells must be positive')
        for opening in wall.get('openings',[]):
            if opening['id'] in ids:raise ValueError('Duplicate opening id')
            ids.add(opening['id'])
            if opening['type'] not in ('door','window','passage'):raise ValueError('Unknown opening type')
            if opening.get('state','closed') not in ('open','closed','locked'):raise ValueError('Invalid opening state')
            if opening['type'] in ('door','window') and not opening.get('asset'):raise ValueError('Doors/windows require a frame/leaf texture asset')
        wall_parts(wall)


def strip(target,a,b,thickness,texture,ppc,tile_cells,shade=True):
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float);direction=b-a;length=float(np.linalg.norm(direction))
    if length<1e-8:return
    direction/=length;normal=np.array([-direction[1],direction[0]])
    corners=np.array([a+normal*thickness/2,b+normal*thickness/2,b-normal*thickness/2,a-normal*thickness/2])*ppc
    low=np.floor(corners.min(axis=0)-2).astype(int);high=np.ceil(corners.max(axis=0)+2).astype(int)
    left=max(0,int(low[0]));top=max(0,int(low[1]));right=min(target.width,int(high[0]));bottom=min(target.height,int(high[1]))
    if right<=left or bottom<=top:return
    yy,xx=np.mgrid[top:bottom,left:right];points=np.stack([(xx+.5)/ppc,(yy+.5)/ppc],axis=-1)-a
    along=points@direction;across=points@normal
    tex=np.asarray(texture.convert('RGB'));u=np.floor(along/tile_cells*tex.shape[1]).astype(int)%tex.shape[1]
    v=np.floor(across/tile_cells*tex.shape[0]).astype(int)%tex.shape[0]
    rgb=tex[v,u].astype(np.float32)
    if shade:rgb*=(.72+.28*(1-np.minimum(1,np.abs(across)/(thickness/2))))[:,:,None]
    alpha=np.uint8(((along>=0)&(along<=length)&(np.abs(across)<=thickness/2))*255)
    rgba=np.dstack([np.uint8(np.clip(rgb,0,255)),alpha]);patch=Image.fromarray(rgba)
    target.alpha_composite(patch,(left,top))


def render_walls(walls,resolve,size,ppc,draw_doors=True):
    image=Image.new('RGBA',size);geometry=[]
    for wall in walls:
        pieces,openings=wall_parts(wall)
        texture=resolve(wall['asset']);tile=wall.get('tile_cells',2);thickness=wall['thickness']
        for a,b in pieces:
            strip(image,a,b,thickness,texture,ppc,tile)
            geometry.append(dict(id=wall['id'],type='wall',points=[a.tolist(),b.tolist()],thickness=thickness))
        for a,b,opening in openings:
            kind=opening['type'];state=opening.get('state','closed')
            geometry.append(dict(id=opening['id'],wall=wall['id'],type=kind,points=[a.tolist(),b.tolist()],state=state))
            if kind=='passage' or (kind=='door' and not draw_doors):continue
            tex=resolve(opening['asset'])
            if kind=='door':
                end=b if state!='open' else a+np.array([-(b-a)[1],(b-a)[0]])
                strip(image,a,end,max(.08,thickness*.55),tex,ppc,tile)
            else:
                direction=(b-a)/np.linalg.norm(b-a);normal=np.array([-direction[1],direction[0]])
                for offset in [-.35,.35]:
                    strip(image,a+normal*thickness*offset,b+normal*thickness*offset,thickness*.22,tex,ppc,tile)
                # A thin pale pane makes the window legible in top view.
                draw=ImageDraw.Draw(image)
                draw.line([tuple(a*ppc),tuple(b*ppc)],fill=(155,209,225,210),width=max(1,round(thickness*.22*ppc)))
    return image,geometry
