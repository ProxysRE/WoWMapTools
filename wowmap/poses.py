"""Deterministic WotLK v264 skeletal snapshots, in the model's native axes.

M2Sequence/M2Bone/M2Track layouts are pinned to 3.3.5.12340. Track headers
always live in M2; external sequence key offsets address the companion ANIM.
No playback clock, particles, UV animation or camera-facing bone rotation.
"""
import math
import struct
import numpy as np
from .models import array_at, model_info

NAMES = {0:'Stand', 15:'HandsClosed', 16:'AttackUnarmed', 17:'Attack1H',
         18:'Attack2H', 19:'Attack2HL', 25:'ReadyUnarmed', 26:'Ready1H',
         27:'Ready2H', 28:'Ready2HL', 29:'ReadyBow', 48:'ReadyRifle',
         51:'ReadySpellDirected', 52:'ReadySpellOmni',108:'ReadyThrown'}


def pose_options(value):
    if value is None: return {'preset':'bind'}
    if isinstance(value,str):
        if value not in ('bind','idle','combat'): raise ValueError('Unknown pose preset')
        return {'preset':value}
    if not isinstance(value,dict) or set(value)-{'animation_id','variation','time_ms','fraction','close_hands'}:
        raise ValueError('Pose must be bind, idle, combat or an animation selection')
    result=dict(value)
    for key,default in [('animation_id',None),('variation',0)]:
        v=result.get(key,default)
        if type(v) is not int or not 0<=v<=65535: raise ValueError(key+' must be an integer 0..65535')
        result[key]=v
    if 'fraction' in result and 'time_ms' in result: raise ValueError('Choose pose fraction or time_ms')
    for key,limit in [('fraction',1),('time_ms',0xffffffff)]:
        if key in result:
            v=result[key]
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=limit:
                raise ValueError('Invalid pose '+key)
    if 'close_hands' in result and type(result['close_hands']) is not bool: raise ValueError('close_hands must be boolean')
    result.setdefault('fraction',.35) if 'time_ms' not in result else None
    return result


def sequences(data):
    count,start=array_at(data,28,64)
    result=[]
    for i in range(count):
        offset=start+64*i
        aid,variation,duration=struct.unpack_from('<HHI',data,offset)
        result.append(dict(index=i,animation_id=aid,variation=variation,duration_ms=duration,
                           flags=struct.unpack_from('<I',data,offset+12)[0],
                           alias=struct.unpack_from('<H',data,offset+62)[0]))
    return result


def choose_sequence(rows,options,gear=None):
    preset=options.get('preset')
    gear=gear or {}
    if preset=='idle': candidates=[0]
    elif preset=='combat':
        inventory=gear.get('main_hand',{}).get('inventory_type')
        subclass=gear.get('main_hand',{}).get('subclass')
        if inventory==17: candidates=([28,27] if subclass in (6,10) else [27,28])+[26,25,18,19,17,16]
        elif subclass==3: candidates=[48,29,26,25,16]
        elif subclass==19: candidates=[51,26,25,16]
        elif inventory==25: candidates=[108,26,25,16]
        elif inventory in (15,26): candidates=[29,48,26,25,16]
        elif 'main_hand' in gear: candidates=[26,25,17,16]
        else: candidates=[25,16,26,17]
    else: candidates=[options['animation_id']]
    variation=options.get('variation',0)
    for aid in candidates:
        selected=next((r for r in rows if r['animation_id']==aid and r['variation']==variation),None)
        if selected is not None: break
    else: raise ValueError('Model has no requested pose animation: '+str(candidates))
    resolved=selected;seen=set()
    while resolved['flags']&0x40:
        if resolved['index'] in seen or resolved['alias']>=len(rows): raise ValueError('Invalid animation alias chain')
        seen.add(resolved['index']);resolved=rows[resolved['alias']]
    return selected,resolved


def quaternion(value):
    value=np.asarray(value,dtype=np.float64)
    norm=np.linalg.norm(value)
    if not np.isfinite(norm) or norm<1e-8: raise ValueError('Invalid animation quaternion')
    return value/norm


def slerp(a,b,t):
    a=quaternion(a);b=quaternion(b);dot=float(a@b)
    if dot<0: b=-b;dot=-dot
    if dot>.9995: return quaternion(a+(b-a)*t)
    theta=np.arccos(np.clip(dot,-1,1))
    return (a*np.sin((1-t)*theta)+b*np.sin(t*theta))/np.sin(theta)


def rotation_matrix(q):
    x,y,z,w=quaternion(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


class Skeleton:
    def __init__(self,assets,name,options,gear=None):
        self.assets=assets;self.name=name;self.data=assets.read(name)
        model_info(self.data,name)
        self.rows=sequences(self.data)
        self.selected,self.sequence=choose_sequence(self.rows,options,gear)
        duration=self.selected['duration_ms']
        self.time=options.get('time_ms',duration*options.get('fraction',.35))
        if self.time>duration: raise ValueError('Pose time_ms exceeds animation duration')
        self.global_time=self.time
        self.external=None;self.dependencies=set();self.ignored_billboards=[]
        count,start=array_at(self.data,20,4)
        self.globals=np.frombuffer(self.data,dtype='<u4',count=count,offset=start)
        count,start=array_at(self.data,44,88)
        if count>4096: raise ValueError('Too many skeleton bones')
        self.bones=[start+i*88 for i in range(count)]
        self.parents=[struct.unpack_from('<h',self.data,p+8)[0] for p in self.bones]
        if any(p < -1 or p>=count for p in self.parents): raise ValueError('Invalid bone parent')
        self.matrices=[None]*count;self.active=set()
        self.hand_bones=set();self.hand_sequence=None
        close=options.get('close_hands',bool(gear))
        if close and gear:
            count,start=array_at(self.data,52,2)
            keys=np.frombuffer(self.data,dtype='<i2',count=count,offset=start)
            fingers=[]
            main=gear.get('main_hand',{})
            if 'main_hand' in gear and main.get('subclass') not in (2,18): fingers+=list(range(8,13))
            if ('off_hand' in gear or main.get('inventory_type')==17 or
                    main.get('subclass') in (2,3,18)): fingers+=list(range(13,18))
            roots={int(keys[k]) for k in fingers if k<len(keys) and keys[k]>=0}
            # Finger key bones can have child segments that also need the grip tracks.
            self.hand_bones=set(roots)
            for _ in self.bones:
                old=len(self.hand_bones)
                self.hand_bones.update(i for i,p in enumerate(self.parents) if p in self.hand_bones)
                if len(self.hand_bones)==old: break
            if roots and any(r['animation_id']==15 and r['variation']==0 for r in self.rows):
                _,self.hand_sequence=choose_sequence(self.rows,{'animation_id':15})

    def source(self,sequence):
        if sequence['flags']&0x20: return self.data
        path=self.name[:-3]+f"{sequence['animation_id']:04d}-{sequence['variation']:02d}.anim"
        if not self.assets.has(path): raise ValueError('Missing external animation: '+path)
        self.dependencies.add(path)
        return self.assets.read(path)

    def track(self,offset,kind,default,sequence,time):
        interpolation,global_sequence=struct.unpack_from('<Hh',self.data,offset)
        nt,ot=array_at(self.data,offset+4,8);nv,ov=array_at(self.data,offset+12,8)
        if nt!=nv: raise ValueError('Animation time/value array counts differ')
        index=sequence['index']
        if global_sequence>=0:
            if global_sequence>=len(self.globals): raise ValueError('Invalid global sequence index')
            length=int(self.globals[global_sequence]);time=self.global_time%length if length else 0
            index=0
        if index>=nt: return np.array(default,dtype=np.float64)
        n,tstart=struct.unpack_from('<II',self.data,ot+index*8)
        nk,vstart=struct.unpack_from('<II',self.data,ov+index*8)
        if n!=nk: raise ValueError('Animation key/time counts differ')
        if not n: return np.array(default,dtype=np.float64)
        if interpolation not in (0,1): raise ValueError('Unsupported bone track interpolation: '+str(interpolation))
        source=self.data if global_sequence>=0 else self.source(sequence)
        stride=8 if kind=='rotation' else 2 if kind=='alpha' else 12
        if tstart+n*4>len(source) or vstart+n*stride>len(source): raise ValueError('Animation keys outside source file')
        times=np.frombuffer(source,dtype='<u4',count=n,offset=tstart)
        if np.any(times[1:]<times[:-1]): raise ValueError('Animation timestamps are not ordered')
        width=4 if kind=='rotation' else 1 if kind=='alpha' else 3
        values=np.frombuffer(source,dtype='<i2' if kind in ('rotation','alpha') else '<f4',count=n*width,offset=vstart).reshape(n,-1).astype(np.float64)
        if kind=='alpha': values=np.clip(values/32767,0,1)
        if kind=='rotation': values=np.where(values<0,values+32768,values-32767)/32767
        if not np.isfinite(values).all(): raise ValueError('Non-finite animation key')
        i=max(0,min(n-1,int(np.searchsorted(times,time,side='right'))-1))
        value=values[i]
        if interpolation==1 and i+1<n and time>times[i] and times[i+1]>times[i]:
            t=float((time-times[i])/(times[i+1]-times[i]))
            value=slerp(value,values[i+1],t) if kind=='rotation' else value+(values[i+1]-value)*t
        return quaternion(value) if kind=='rotation' else value

    def matrix(self,index):
        if self.matrices[index] is not None: return self.matrices[index]
        if index in self.active: raise ValueError('Cyclic bone hierarchy')
        self.active.add(index)
        p=self.bones[index];parent=self.parents[index]
        flags=struct.unpack_from('<I',self.data,p+4)[0]
        pivot=np.array(struct.unpack_from('<3f',self.data,p+76))
        if not np.isfinite(pivot).all(): raise ValueError('Non-finite bone pivot')
        seq=self.hand_sequence if index in self.hand_bones and self.hand_sequence else self.sequence
        time=0 if seq is self.hand_sequence else self.time
        translation=self.track(p+16,'translation',[0,0,0],seq,time)
        rotation=self.track(p+36,'rotation',[0,0,0,1],seq,time)
        scale=self.track(p+56,'scale',[1,1,1],seq,time)
        local=np.eye(4);local[:3,:3]=rotation_matrix(rotation)@np.diag(scale)
        local[:3,3]=pivot+translation-local[:3,:3]@pivot
        if flags&0x78: self.ignored_billboards.append(index)
        self.matrices[index]=self.matrix(parent)@local if parent>=0 else local
        self.active.remove(index)
        return self.matrices[index]

    def skin(self,vertices):
        result=vertices.copy()
        weights=vertices['weights'].astype(np.float64)
        totals=weights.sum(axis=1)
        weights=np.divide(weights,totals[:,None],out=np.zeros_like(weights),where=totals[:,None]>0)
        position=np.zeros((len(vertices),3));normal=np.zeros_like(position)
        for influence in range(4):
            bone_indices=vertices['bones'][:,influence]
            for bone in np.unique(bone_indices[weights[:,influence]>0]):
                if bone>=len(self.bones): raise ValueError('Vertex references invalid skeleton bone')
                mask=(bone_indices==bone)&(weights[:,influence]>0);matrix=self.matrix(int(bone))
                w=weights[mask,influence,None]
                position[mask]+=(vertices['position'][mask]@matrix[:3,:3].T+matrix[:3,3])*w
                # Zero scale is a legitimate way of hiding eye-glow or accessory geometry.
                normal_matrix=np.linalg.pinv(matrix[:3,:3]).T
                normal[mask]+=(vertices['normal'][mask]@normal_matrix.T)*w
        zero=totals==0;position[zero]=vertices['position'][zero];normal[zero]=vertices['normal'][zero]
        lengths=np.linalg.norm(normal,axis=1,keepdims=True)
        result['position']=position
        result['normal']=np.divide(normal,lengths,out=np.zeros_like(normal),where=lengths>1e-8)
        if not np.isfinite(result['position']).all() or not np.isfinite(result['normal']).all():raise ValueError('Non-finite skinned geometry')
        return result

    def metadata(self):
        row=self.selected
        return dict(animation_id=row['animation_id'],animation=NAMES.get(row['animation_id'],str(row['animation_id'])),
                    variation=row['variation'],sequence_index=row['index'],resolved_sequence_index=self.sequence['index'],
                    resolved_animation_id=self.sequence['animation_id'],
                    time_ms=float(self.time),duration_ms=row['duration_ms'],
                    external_sources=sorted(self.dependencies),hand_grip=bool(self.hand_sequence),
                    billboard_bones_without_camera_alignment=sorted(set(self.ignored_billboards)))
