"""Experimental top-down bake of selected WotLK projectile effects.

Original textures, emitter rates, bones and lifetime curves; deterministic 2D
approximation, not a full WoW renderer. Frost adds a sampled mesh core and ribbons.
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
from .models import RawAssets, array_at, model_info, preview
from .poses import Skeleton

MODEL='spells/fireball_missile_high.m2'
PROFILES={
    'wow.fire.projectile':MODEL,
    'wow.frost.projectile':'spells/frostbolt.m2',
    'wow.shadow.projectile':'spells/shadowbolt_missile.m2',
    'wow.fel.projectile':'spells/fel_fireball_missile_high.m2',
}

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

class ScalarTrack:
    """An explicit WotLK scalar track, including external and global sequences."""
    def __init__(self,pose,offset,default=0):
        data=pose.data;self.mode,global_id=struct.unpack_from('<Hh',data,offset)
        if self.mode not in (0,1):raise ValueError('Unsupported scalar interpolation: '+str(self.mode))
        nt,ot=array_at(data,offset+4,8);nv,ov=array_at(data,offset+12,8)
        if nt!=nv:raise ValueError('Scalar time/value array counts differ')
        index=pose.sequence['index'];self.period=pose.selected['duration_ms']
        if global_id>=0:
            if global_id>=len(pose.globals):raise ValueError('Invalid scalar global sequence')
            self.period=int(pose.globals[global_id]);index=0
        self.times=np.array([0.]);self.values=np.array([float(default)])
        if index>=nt:return
        n,to=struct.unpack_from('<II',data,ot+index*8);nk,vo=struct.unpack_from('<II',data,ov+index*8)
        if n!=nk or n>4096:raise ValueError('Invalid scalar key count')
        if not n:return
        source=data if global_id>=0 else pose.source(pose.sequence)
        if to+n*4>len(source) or vo+n*4>len(source):raise ValueError('Scalar keys outside source')
        self.times=np.frombuffer(source,dtype='<u4',count=n,offset=to).astype(float)
        self.values=np.frombuffer(source,dtype='<f4',count=n,offset=vo).astype(float)
        if np.any(np.diff(self.times)<0) or not np.isfinite(self.values).all():raise ValueError('Invalid scalar keys')
    def at(self,seconds):
        t=seconds*1000
        if self.period:t%=self.period
        if self.mode==1:return float(np.interp(t,self.times,self.values))
        return float(self.values[max(0,int(np.searchsorted(self.times,t,side='right'))-1)])


def birth_phases(track,cycle,rng):
    if np.all(track.values==track.values[0]):
        n=round(track.values[0]*cycle)
        if n>12000:raise ValueError('Particle birth budget exceeded')
        return [(i+rng.random())/max(1,n)*cycle for i in range(n)]
    # Integrate a changing birth rate rather than assigning uniform births.
    # This is a bounded 240 Hz numerical approximation to the source curve.
    times=np.linspace(0,cycle,round(cycle*240)+1)
    rates=np.array([track.at(t) for t in times])
    cumulative=np.r_[0,np.cumsum((rates[:-1]+rates[1:])*.5*np.diff(times))]
    total=cumulative[-1];n=round(total)
    if n>12000:raise ValueError('Particle birth budget exceeded')
    return [float(np.interp((i+rng.random())/max(1,n)*total,cumulative,times)) for i in range(n)]


def emitters(assets,model=MODEL):
    data=assets.read(model);info=model_info(data,model)
    pose=Skeleton(assets,model,dict(animation_id=0,time_ms=0))
    if struct.unpack_from('<I',data,16)[0]&0x200:raise ValueError('Unsupported extended particle layout')
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
        tracks=[ScalarTrack(pose,p+off) for off in (52,72,92,112,132,152,176,200,220,240)]
        values=[t.at(0) for t in tracks]
        if not np.all((tracks[5].values>=0)&(tracks[5].values<=15)) or not np.all((tracks[6].values>=0)&(tracks[6].values<=1000)):raise ValueError('Unbounded particle emission')
        for field in (24,32):
            n,off=array_at(data,p+field,1)
            if n and data[off:off+n].strip(b'\0'):raise ValueError('Model/recursive particles require a separate renderer')
        result.append(dict(index=i,flags=flags,pos=pos,bone=bone,texture=path,blend=blend,shape=shape,rows=rows,cols=cols,
            tracks=tracks,dependencies=set(pose.dependencies),max_life=float(tracks[5].values.max()),animated=any(len(t.values)>1 and np.ptp(t.values)>0 for t in tracks),speed=values[0],variation=values[1],vertical=values[2],horizontal=values[3],gravity=values[4],life=values[5],rate=values[6],length=values[7],width=values[8],zsource=values[9],
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

def skeleton_at(assets,model,time_ms):
    pose=Skeleton(assets,model,dict(animation_id=0,time_ms=0))
    duration=pose.selected['duration_ms']
    pose.time=time_ms%duration if duration else 0
    pose.global_time=time_ms
    return pose


def typed_constant(data,offset,components,dtype,default):
    interpolation,_=struct.unpack_from('<Hh',data,offset)
    if interpolation not in (0,1):raise ValueError('Unsupported ribbon interpolation')
    nt,_=array_at(data,offset+4,8);nv,ov=array_at(data,offset+12,8)
    if nt!=nv:raise ValueError('Mismatched ribbon track arrays')
    if not nv:return np.asarray(default,dtype=float)
    n,start=struct.unpack_from('<II',data,ov)
    if not n:return np.asarray(default,dtype=float)
    if n>4096 or start+n*components*np.dtype(dtype).itemsize>len(data):raise ValueError('Ribbon keys outside M2')
    values=np.frombuffer(data,dtype=dtype,count=n*components,offset=start).reshape(n,components)
    if not np.isfinite(values).all() or not np.allclose(values,values[0]):raise ValueError('Only constant ribbon tracks supported')
    return values[0].astype(float)


def ribbons(assets,model):
    data=assets.read(model);info=model_info(data,model)
    count,start=array_at(data,288,176);nm,om=array_at(data,112,4)
    if count>16:raise ValueError('Too many ribbons')
    result=[]
    for i in range(count):
        p=start+i*176;nt,ot=array_at(data,p+20,2);nb,ob=array_at(data,p+28,2)
        if nt!=1 or nb!=1:raise ValueError('Only single-texture ribbons supported')
        ti=struct.unpack_from('<H',data,ot)[0];mi=struct.unpack_from('<H',data,ob)[0]
        if ti>=len(info['textures']) or mi>=nm:raise ValueError('Ribbon material outside model')
        _,blend=struct.unpack_from('<HH',data,om+mi*4)
        rate,life,gravity=struct.unpack_from('<3f',data,p+116)
        rows,cols=struct.unpack_from('<HH',data,p+128)
        if blend not in (2,4) or not 0<life<=2 or not 0<rate<=100 or gravity!=0 or rows!=1 or cols!=1:raise ValueError('Unsupported ribbon layout')
        color=typed_constant(data,p+36,3,'<f4',[1,1,1])
        alpha=typed_constant(data,p+56,1,'<u2',[32767])[0]/32767
        above=typed_constant(data,p+76,1,'<f4',[0])[0];below=typed_constant(data,p+96,1,'<f4',[0])[0]
        if not 0<=above<=8 or not 0<=below<=8:raise ValueError('Unbounded ribbon width')
        slot=typed_constant(data,p+132,1,'<u2',[0])[0]
        visible=typed_constant(data,p+152,1,'u1',[1])[0]
        if slot!=0 or visible!=1:raise ValueError('Unsupported ribbon slot/visibility')
        result.append(dict(bone=struct.unpack_from('<I',data,p+4)[0],pos=np.array(struct.unpack_from('<3f',data,p+8)),
                           texture=info['textures'][ti]['path'],blend=blend,rate=rate,life=life,color=color,alpha=alpha,above=above,below=below))
    return result


def ribbon_frame(canvas,assets,model,r,texture,t,unit,anchor,trail_speed=2.5,cycle=1):
    # Flatten the historical strip into the tabletop plane. Motion is the same
    # authored 2.5 world units/second used for the baked particle trail.
    size=canvas.shape[0];points=[]
    steps=max(2,math.ceil(r['rate']*r['life']))
    for age in np.linspace(0,r['life'],steps+1):
        sk=skeleton_at(assets,model,((t-age)%cycle)*1000)
        m=sk.matrix(r['bone']);q=m[:3,:3]@r['pos']+m[:3,3]-[trail_speed*age,0,0]
        points.append([anchor[0]*size+q[0]*unit,anchor[1]*size-q[1]*unit])
    tex=np.asarray(texture).astype(np.float32)/255
    for i in range(steps):
        a,b=np.asarray(points[i]),np.asarray(points[i+1]);delta=b-a;length=np.linalg.norm(delta)
        if length<1e-6:continue
        normal=np.array([-delta[1],delta[0]])/length
        quad=np.array([a+normal*r['above']*unit,a-normal*r['below']*unit,b-normal*r['below']*unit,b+normal*r['above']*unit])
        uv=np.array([[i/steps,0],[i/steps,1],[(i+1)/steps,1],[(i+1)/steps,0]])
        layer=np.zeros_like(canvas)
        for tri in ((0,1,2),(0,2,3)):
            p=quad[list(tri)];lo=np.maximum(0,np.floor(p.min(axis=0)).astype(int));hi=np.minimum(size-1,np.ceil(p.max(axis=0)).astype(int))
            if np.any(hi<lo):continue
            yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1];a0,b0,c0=p
            den=(b0[1]-c0[1])*(a0[0]-c0[0])+(c0[0]-b0[0])*(a0[1]-c0[1])
            if abs(den)<1e-8:continue
            w0=((b0[1]-c0[1])*(xx+.5-c0[0])+(c0[0]-b0[0])*(yy+.5-c0[1]))/den
            w1=((c0[1]-a0[1])*(xx+.5-c0[0])+(a0[0]-c0[0])*(yy+.5-c0[1]))/den
            w2=1-w0-w1;covered=(w0>=0)&(w1>=0)&(w2>=0)
            tuv=np.stack([w0,w1,w2],axis=-1)@uv[list(tri)]
            tx=np.clip((tuv[:,:,0]*(tex.shape[1]-1)).astype(int),0,tex.shape[1]-1);ty=np.clip((tuv[:,:,1]*(tex.shape[0]-1)).astype(int),0,tex.shape[0]-1)
            pixels=tex[ty,tx].copy();pixels[:,:,:3]*=r['color'];pixels[:,:,3]*=r['alpha']
            layer[lo[1]:hi[1]+1,lo[0]:hi[0]+1][covered]=pixels[covered]
        composite(canvas,layer,size/2,size/2,r['blend'])


def bake(assets,out,size=384,fps=30,seed=1731,profile="wow.fire.projectile",model=None,stationary=False,duration=None):
    if profile not in PROFILES:raise ValueError("Unknown effect profile")
    custom=model is not None
    model=model or PROFILES[profile]
    cycle=2 if profile=='wow.shadow.projectile' else 1
    if not 128<=size<=1024 or not 10<=fps<=60:raise ValueError('size 128..1024, fps 10..60')
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise ValueError('Output directory must be empty')
    definitions,info=emitters(assets,model)
    strips=ribbons(assets,model)
    cycle=max(cycle,math.ceil(max((e['max_life'] for e in definitions),default=1)))
    cycle_ms=cycle*1000
    for e in definitions:
        for track in e['tracks']:
            if np.ptp(track.values)>0 and track.period:cycle_ms=math.lcm(cycle_ms,track.period)
    if duration is not None:
        if not math.isfinite(duration) or not 0<duration<=15:raise ValueError('Duration must be 0..15 seconds')
        cycle_ms=round(duration*1000)
    if cycle_ms<=0 or cycle_ms>15000 or cycle_ms*fps%1000:raise ValueError('Animated cycle must fit 15 seconds and whole output frames')
    cycle=cycle_ms/1000
    out.mkdir(parents=True,exist_ok=True);frames=out/'frames';frames.mkdir()
    textures={p:Image.fromarray(assets.image(p)) for p in {e['texture'] for e in definitions+strips}}
    # One deterministic repeating emission cycle, with enough preceding cycles
    # for particles alive at t=0. Particle lifetime, not frame count, drives age.
    particles=[]
    for e in definitions:
        rng=np.random.default_rng(seed+e['index'])
        phases=birth_phases(e['tracks'][6],cycle,rng)
        if (len(particles)+len(phases))*fps*cycle>1000000:raise ValueError('Particle render budget exceeded')
        for phase in phases:
            particle=dict(e)
            values=[track.at(phase) for track in e['tracks']]
            particle.update(zip(('speed','variation','vertical','horizontal','gravity','life','rate','length','width','zsource'),values))
            e=particle
            if e['life']<=0:continue
            s=skeleton_at(assets,model,phase*1000)
            matrix=s.matrix(e['bone'])
            angle=rng.uniform(-e['vertical'],e['vertical']);azimuth=rng.uniform(0,e['horizontal'])
            direction=np.array([math.sin(angle)*math.cos(azimuth),math.sin(angle)*math.sin(azimuth),math.cos(angle)])
            if e['shape']==2:
                direction=rng.normal(size=3);direction/=np.linalg.norm(direction)
            local=e['pos']+np.array([rng.uniform(-.5,.5)*e['length'],rng.uniform(-.5,.5)*e['width'],0])
            pos=matrix[:3,:3]@local+matrix[:3,3]
            velocity=matrix[:3,:3]@direction*e['speed']*(1+rng.uniform(-1,1)*e['variation'])
            particles.append((e,phase,pos,velocity))
    if len(particles)>12000 or len(particles)*fps*cycle>1000000:raise ValueError('Particle render budget exceeded')
    unit=size/8;anchor=(.5,.5) if stationary else (.625,.5)
    visible_frames=0
    for frame in range(round(fps*cycle)):
        t=frame/fps;canvas=np.zeros((size,size,4),dtype=np.float32)
        for strip in strips:
            ribbon_frame(canvas,assets,model,strip,textures[strip['texture']],t,unit,anchor,trail_speed=0 if stationary else 2.5,cycle=cycle)
        if model==PROFILES['wow.frost.projectile']:
            # Preserve the real ice core at the same model-origin and world scale.
            core,meta=preview(assets,model,size=256,pose=dict(animation_id=0,time_ms=skeleton_at(assets,model,t*1000).time))
            ratio=unit/meta['pixels_per_world_unit']
            w=max(1,round(core.width*ratio));h=max(1,round(core.height*ratio))
            pixels=np.asarray(core.resize((w,h),Image.Resampling.LANCZOS)).astype(np.float32)/255
            composite(canvas,pixels,anchor[0]*size-meta['anchor_pixels'][0]*ratio+w/2,
                      anchor[1]*size-meta['anchor_pixels'][1]*ratio+h/2,2)
        for e,phase,pos,velocity in particles:
            age=(t-phase)%cycle if duration is None else t-phase
            if age<0 or age>=e['life']:continue
            u=age/e['life'];point=pos+velocity*age
            if not stationary and not e['flags']&0x10:point=point-np.array([2.5*age,0,0])
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
        if alpha.any():visible_frames+=1
        rgb=np.divide(canvas[:,:,:3],alpha,out=np.zeros_like(canvas[:,:,:3]),where=alpha>1e-6)
        rgba=np.concatenate([np.clip(rgb,0,1),alpha],axis=-1)
        Image.fromarray((rgba*255).round().astype('uint8')).save(frames/f'{frame:04d}.png')
    if not visible_frames:raise ValueError('No visible particles in the selected sequence/clip')
    webm=out/((Path(model).stem+'-particles.webm') if custom else (profile.split('.')[1]+'-projectile.webm'))
    subprocess.run(['ffmpeg','-v','error','-y','-framerate',str(fps),'-i',str(frames/'%04d.png'),'-c:v','libvpx-vp9','-pix_fmt','yuva420p','-b:v','0','-crf','28','-auto-alt-ref','0',str(webm)],check=True)
    deps={model,*[e['texture'] for e in definitions+strips]}
    for e in definitions:deps.update(e['dependencies'])
    if model==PROFILES['wow.frost.projectile']:
        deps.update(meta['used_textures']);deps.add(model[:-3]+'00.skin')
    if particles:
        pose=Skeleton(assets,model,dict(animation_id=0,time_ms=0))
        for e in definitions+strips:pose.matrix(e['bone'])
        deps.update(pose.dependencies)
    metadata=dict(format='wowmap.effect-bake/1',profile=None if custom else profile,motion_style=profile,model=model,stationary=stationary,seamless_cycle=duration is None,size=size,fps=fps,duration_ms=cycle_ms,anchor=list(anchor),seed=seed,
        emitters=len(definitions),ribbons=len(strips),mesh_core=model==PROFILES['wow.frost.projectile'],animated_emitters=sum(e['animated'] for e in definitions),sources=[dict(path=p,sha256=hashlib.sha256(assets.read(p)).hexdigest()) for p in sorted(deps)],
        limitations=['experimental 2D particle approximation','mesh core only for frost; no depth occlusion, mesh color-track or UV animation', 'ribbons use source bones, widths and textures with an authored 2D camera-facing strip','plane/sphere emission and atlas timing approximated','step and linear scalar tracks; animated birth rates integrated at 240 Hz','trail speed is an authored bake parameter, not spell movement data','black matte removed from the fire atlas for tabletop compositing'])
    (out/'bake-report.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    return metadata

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assets',required=True);p.add_argument('--out',required=True);p.add_argument('--size',type=int,default=384);p.add_argument('--fps',type=int,default=30)
    p.add_argument('--profile',choices=sorted(PROFILES),default='wow.fire.projectile')
    p.add_argument('--model',help='Explicit M2 path; use with --profile for tabletop motion style, not an automatic spell binding')
    p.add_argument('--stationary',action='store_true',help='No projectile trail; anchor in the centre')
    p.add_argument('--duration',type=float,help='One-shot clip in seconds; no promise of a seamless loop')
    args=p.parse_args()
    with RawAssets(args.assets) as assets:print(json.dumps(bake(assets,args.out,args.size,args.fps,profile=args.profile,model=args.model,stationary=args.stationary,duration=args.duration),indent=2))

if __name__=='__main__':main()

