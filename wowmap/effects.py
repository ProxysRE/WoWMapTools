"""Experimental top-down bake of the WotLK fireball's particle emitters.

Original textures, emitter rates, bones and lifetime curves; deterministic 2D
approximation, not a full WoW renderer. No mesh/UV animation, ribbon or lighting.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import numpy as np
from PIL import Image
from .models import RawAssets, array_at, model_info
from .poses import Skeleton

MODEL='spells/fireball_missile_high.m2'

def flat_curve(data,offset,components,dtype):
    size=np.dtype(dtype).itemsize
    nt,ot=array_at(data,offset,2);nv,ov=array_at(data,offset+8,size*components)
    if nt!=nv or nt>4096:raise ValueError('Invalid particle lifetime curve')
    times=np.frombuffer(data,dtype='<u2',count=nt,offset=ot).astype(float)/32767
    values=np.frombuffer(data,dtype=dtype,count=nv*components,offset=ov).reshape(nv,components).astype(float)
    if len(times) and (np.any(np.diff(times)<0) or not np.isfinite(values).all()):raise ValueError('Invalid curve values')
    return times,values

def curve_at(curve,t,default):
    times,values=curve
    if not len(times):return np.asarray(default,dtype=float)
    return np.array([np.interp(t,times,values[:,i]) for i in range(values.shape[1])])

def constant_track(data,offset,default):
    interpolation,global_sequence=struct.unpack_from('<Hh',data,offset)
    if interpolation not in (0,1):raise ValueError('Unsupported emitter interpolation')
    nt,ot=array_at(data,offset+4,8);nv,ov=array_at(data,offset+12,8)
    if nt!=nv:raise ValueError('Mismatched emitter track arrays')
    if not nv:return default
    n,start=struct.unpack_from('<II',data,ov)
    if start+4*n>len(data):raise ValueError('Emitter keys outside M2')
    if not n:return default
    values=np.frombuffer(data,dtype='<f4',count=n,offset=start)
    if not np.isfinite(values).all() or not np.allclose(values,values[0]):
        raise ValueError('Pilot supports only constant emission tracks')
    return float(values[0])

def emitters(assets):
    data=assets.read(MODEL);info=model_info(data,MODEL)
    if struct.unpack_from('<I',data,16)[0]&0x200:raise ValueError('Unsupported extended particle layout')
    if array_at(data,288,176)[0]:raise ValueError('Ribbons are not supported')
    count,start=array_at(data,296,476)
    if count>64:raise ValueError('Too many emitters')
    result=[]
    for i in range(count):
        p=start+i*476
        flags=struct.unpack_from('<I',data,p+4)[0]
        pos=np.array(struct.unpack_from('<3f',data,p+8))
        bone,texture=struct.unpack_from('<HH',data,p+20)
        blend,shape=struct.unpack_from('<BB',data,p+40)
        rows,cols=struct.unpack_from('<HH',data,p+48)
        if shape not in (1,2) or blend not in (2,4):raise ValueError('Unsupported particle shape/blend')
        if not 1<=rows<=16 or not 1<=cols<=16:raise ValueError('Invalid texture atlas')
        if texture>=len(info['textures']):raise ValueError('Particle texture index outside model')
        path=info['textures'][texture]['path']
        if not path:raise ValueError('Replaceable particle textures are not supported')
        values=[constant_track(data,p+off,0) for off in (52,72,92,112,132,152,176,200,220,240)]
        if not 0<values[5]<=5 or not 0<=values[6]<=1000:raise ValueError('Unbounded particle emission')
        result.append(dict(index=i,flags=flags,pos=pos,bone=bone,texture=path,blend=blend,shape=shape,rows=rows,cols=cols,
            speed=values[0],variation=values[1],vertical=values[2],horizontal=values[3],gravity=values[4],life=values[5],rate=values[6],length=values[7],width=values[8],zsource=values[9],
            color=flat_curve(data,p+260,3,'<f4'),alpha=flat_curve(data,p+276,1,'<u2'),scale=flat_curve(data,p+292,2,'<f4')))
    return result,info

def composite(canvas,sprite,x,y,blend):
    h,w=sprite.shape[:2];left=int(round(x-w/2));top=int(round(y-h/2))
    x0=max(0,left);y0=max(0,top);x1=min(canvas.shape[1],left+w);y1=min(canvas.shape[0],top+h)
    if x1<=x0 or y1<=y0:return
    src=sprite[y0-top:y1-top,x0-left:x1-left];dst=canvas[y0:y1,x0:x1]
    a=src[:,:,3:4]
    if blend==4:
        emitted=src[:,:,:3]*a
        dst[:,:,:3]=np.minimum(1,dst[:,:,:3]+emitted)
        dst[:,:,3:4]+= (1-dst[:,:,3:4])*emitted.max(axis=-1,keepdims=True)
    else:
        dst[:,:,:3]=src[:,:,:3]*a+dst[:,:,:3]*(1-a)
        dst[:,:,3:4]=a+dst[:,:,3:4]*(1-a)

def bake(assets,out,size=384,fps=30,seed=1731):
    if not 128<=size<=1024 or not 10<=fps<=60:raise ValueError('size 128..1024, fps 10..60')
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise ValueError('Output directory must be empty')
    definitions,info=emitters(assets)
    out.mkdir(parents=True,exist_ok=True);frames=out/'frames';frames.mkdir()
    textures={p:Image.fromarray(assets.image(p)) for p in {e['texture'] for e in definitions}}
    # One deterministic repeating emission cycle, with enough preceding cycles
    # for particles alive at t=0. Particle lifetime, not frame count, drives age.
    particles=[]
    for e in definitions:
        count=round(e['rate'])
        rng=np.random.default_rng(seed+e['index'])
        for i in range(count):
            phase=(i+rng.random())/max(1,count)
            s=Skeleton(assets,MODEL,dict(animation_id=0,time_ms=phase*1000))
            matrix=s.matrix(e['bone'])
            angle=rng.uniform(-e['vertical'],e['vertical']);azimuth=rng.uniform(0,e['horizontal'])
            direction=np.array([math.sin(angle)*math.cos(azimuth),math.sin(angle)*math.sin(azimuth),math.cos(angle)])
            if e['shape']==2:
                direction=rng.normal(size=3);direction/=np.linalg.norm(direction)
            local=e['pos']+np.array([rng.uniform(-.5,.5)*e['length'],rng.uniform(-.5,.5)*e['width'],0])
            pos=matrix[:3,:3]@local+matrix[:3,3]
            velocity=matrix[:3,:3]@direction*e['speed']*(1+rng.uniform(-1,1)*e['variation'])
            particles.append((e,phase,pos,velocity))
    unit=size/8;anchor=(.625,.5)
    for frame in range(fps):
        t=frame/fps;canvas=np.zeros((size,size,4),dtype=np.float32)
        for e,phase,pos,velocity in particles:
            age=(t-phase)%1
            if age>=e['life']:continue
            u=age/e['life'];point=pos+velocity*age
            if not e['flags']&0x10:point=point-np.array([2.5*age,0,0])
            scale=curve_at(e['scale'],u,[1,1]);color=np.clip(curve_at(e['color'],u,[255,255,255])/255,0,1)
            alpha=np.clip(curve_at(e['alpha'],u,[32767])[0]/32767,0,1)
            texture=textures[e['texture']];rows=e['rows'];cols=e['cols']
            cell=min(rows*cols-1,int(u*rows*cols))
            tw=texture.width//cols;th=texture.height//rows
            sprite=texture.crop(((cell%cols)*tw,(cell//cols)*th,(cell%cols+1)*tw,(cell//cols+1)*th))
            w=max(1,min(size*2,round(abs(scale[0])*unit)));h=max(1,min(size*2,round(abs(scale[1])*unit)))
            sprite=sprite.resize((w,h),Image.Resampling.BILINEAR)
            pixels=np.asarray(sprite).astype(np.float32)/255
            # Authoring correction for this legacy fire atlas: black padding
            # must not become an opaque square on a bright tabletop background.
            if e['texture'].endswith('t_vfx_fire_anim02_64.blp'):
                pixels[:,:,3]*=np.clip(pixels[:,:,:3].max(axis=-1),0,1)**2
            pixels[:,:,:3]*=color;pixels[:,:,3]*=alpha
            composite(canvas,pixels,anchor[0]*size+point[0]*unit,anchor[1]*size-point[1]*unit,e['blend'])
        # Convert premultiplied accumulation back to straight RGBA for VP9 alpha.
        alpha=canvas[:,:,3:4]
        rgb=np.divide(canvas[:,:,:3],alpha,out=np.zeros_like(canvas[:,:,:3]),where=alpha>1e-6)
        rgba=np.concatenate([np.clip(rgb,0,1),alpha],axis=-1)
        Image.fromarray((rgba*255).round().astype('uint8')).save(frames/f'{frame:04d}.png')
    webm=out/'fire-projectile.webm'
    subprocess.run(['ffmpeg','-v','error','-y','-framerate',str(fps),'-i',str(frames/'%04d.png'),'-c:v','libvpx-vp9','-pix_fmt','yuva420p','-b:v','0','-crf','28','-auto-alt-ref','0',str(webm)],check=True)
    deps={MODEL,*[e['texture'] for e in definitions]}
    if particles:
        pose=Skeleton(assets,MODEL,dict(animation_id=0,time_ms=0))
        for e in definitions:pose.matrix(e['bone'])
        deps.update(pose.dependencies)
    metadata=dict(format='wowmap.effect-bake/1',profile='wow.fire.projectile',model=MODEL,size=size,fps=fps,duration_ms=1000,anchor=list(anchor),seed=seed,
        emitters=len(definitions),sources=[dict(path=p,sha256=hashlib.sha256(assets.read(p)).hexdigest()) for p in sorted(deps)],
        limitations=['experimental 2D particle approximation','no mesh, ribbons, depth occlusion or UV animation','plane/sphere emission and atlas timing approximated','constant emission tracks only','trail speed is an authored bake parameter, not spell movement data','black matte removed from the fire atlas for tabletop compositing'])
    (out/'bake-report.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    return metadata

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assets',required=True);p.add_argument('--out',required=True);p.add_argument('--size',type=int,default=384);p.add_argument('--fps',type=int,default=30)
    args=p.parse_args()
    with RawAssets(args.assets) as assets:print(json.dumps(bake(assets,args.out,args.size,args.fps),indent=2))

if __name__=='__main__':main()
