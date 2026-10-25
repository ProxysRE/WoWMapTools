"""Shared scene geometry for masks, placement and structural export."""
import math
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .objects import finite,pair


def validate_shape(shape,depth=0):
    if depth>8:raise ValueError('Shapes are nested too deeply')
    kind=shape['type']
    if kind in ('ellipse','rectangle'):
        bounds=shape['bounds']
        if len(bounds)!=4:raise ValueError('bounds needs four coordinates')
        for v in bounds:finite(v,'bounds')
        if bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:raise ValueError('Invalid shape bounds')
    elif kind in ('path','polygon'):
        points=shape['points']
        if len(points)<(2 if kind=='path' else 3):raise ValueError('Not enough shape points')
        for p in points:pair(p,'shape point')
        if kind=='path' and finite(shape['width'],'path width')<=0:raise ValueError('path width must be positive')
    else:raise ValueError(f'Unknown shape: {kind}')
    for name in ('feather','roughness'):
        if finite(shape.get(name,0),name)<0:raise ValueError(f'{name} must be nonnegative')
    for hole in shape.get('cutouts',[]):validate_shape(hole,depth+1)


def path_points(shape):
    points=np.array(shape['points'],dtype=float)
    if shape['type']!='path' or not shape.get('smooth',False):return points.tolist()
    result=[]
    for i in range(len(points)-1):
        p0=points[max(0,i-1)];p1=points[i];p2=points[i+1];p3=points[min(len(points)-1,i+2)]
        steps=max(8,min(128,math.ceil(np.linalg.norm(p2-p1)*8)))
        for t in np.linspace(0,1,steps,endpoint=False):
            p=.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t*t+(-p0+3*p1-3*p2+p3)*t*t*t)
            result.append(p.tolist())
    result.append(points[-1].tolist());return result


def segment_distance(point,a,b):
    point=np.asarray(point);a=np.asarray(a);b=np.asarray(b);v=b-a
    denom=float(v@v)
    t=np.clip(float((point-a)@v)/denom,0,1) if denom>0 else 0
    return float(np.linalg.norm(point-(a+t*v)))


def signed_distance(shape,point):
    x,y=point;kind=shape['type']
    if kind=='rectangle':
        a,b,c,d=shape['bounds'];inside=a<=x<=c and b<=y<=d
        distance=min(x-a,c-x,y-b,d-y) if inside else -math.hypot(max(a-x,0,x-c),max(b-y,0,y-d))
    elif kind=='ellipse':
        a,b,c,d=shape['bounds'];rx=(c-a)/2;ry=(d-b)/2
        distance=(1-math.hypot((x-(a+c)/2)/rx,(y-(b+d)/2)/ry))*min(rx,ry)
    else:
        points=path_points(shape)
        segments=list(zip(points,points[1:]))
        if kind=='polygon':segments.append((points[-1],points[0]))
        distance=min(segment_distance(point,a,b) for a,b in segments)
        if kind=='path':distance=shape['width']/2-distance
        else:
            inside=False
            for (ax,ay),(bx,by) in segments:
                if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:inside=not inside
            distance=distance if inside else -distance
    for hole in shape.get('cutouts',[]):distance=min(distance,-signed_distance(hole,point))
    return distance


def mask_shape(shape,size,ppc,rng):
    mask=Image.new('L',size);draw=ImageDraw.Draw(mask)
    kind=shape['type']
    if kind in ('ellipse','rectangle'):
        bounds=[round(v*ppc) for v in shape['bounds']]
        (draw.ellipse if kind=='ellipse' else draw.rectangle)(bounds,fill=255)
    else:
        points=[(round(x*ppc),round(y*ppc)) for x,y in path_points(shape)]
        if kind=='polygon':draw.polygon(points,fill=255)
        else:
            radius=shape['width']*ppc/2
            draw.line(points,fill=255,width=max(1,round(radius*2)),joint='curve')
            for x,y in points:draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
    feather=shape.get('feather',.4)*ppc
    if feather:mask=mask.filter(ImageFilter.GaussianBlur(feather))
    values=np.asarray(mask,dtype=np.float32)/255
    rough=shape.get('roughness',0)
    if rough:
        noise=rng.integers(0,256,(max(2,math.ceil(size[1]/max(4,ppc*.7))),max(2,math.ceil(size[0]/max(4,ppc*.7)))),dtype=np.uint8)
        noise=np.asarray(Image.fromarray(noise).resize(size,Image.Resampling.BICUBIC),dtype=np.float32)/127.5-1
        values=np.clip(values+noise*rough*4*values*(1-values),0,1)
    for hole in shape.get('cutouts',[]):values*=1-mask_shape(hole,size,ppc,rng)
    return values
