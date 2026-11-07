"""Bounded tabletop beam bakes from WotLK SpellChainEffects and original BLP.

The native strip texture and tint are retained; UV flow, endpoint taper and
projection are authored approximations, not the full WoW chain simulation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import numpy as np
from PIL import Image
from .dbc import DBC
from .models import RawAssets

TABLE='dbfilesclient/spellchaineffects.dbc'
PROFILES={
    'wow.frost.beam':{'chain_id':326,'flow':1},
    'wow.shadow.beam':{'chain_id':10,'flow':1},
    'wow.nature.beam':{'chain_id':5,'flow':1},
    'wow.drain.beam':{'chain_id':5,'flow':-1},
}


def chain_record(data,chain_id):
    table=DBC(data)
    # 3.2.0.10192--3.3.5.12340: five packed u8 fields followed by u32s.
    # Never use DBC.cell(): 48 logical columns occupy 177, not 192 bytes.
    if table.fields!=48 or table.record_size!=177:raise ValueError('Expected WotLK 48-column / 177-byte SpellChainEffects')
    matches=[]
    for i in range(table.records):
        p=20+i*177
        if struct.unpack_from('<I',data,p)[0]==chain_id:matches.append(p)
    if len(matches)!=1:raise ValueError('Expected one unique chain ID')
    p=matches[0];offset=struct.unpack_from('<I',data,p+28)[0]
    if offset>=table.string_bytes:raise ValueError('Chain texture offset outside string block')
    start=table.string_start+offset;end=data.find(b'\0',start)
    texture=data[start:end].decode('utf-8').replace('\\','/').lower()
    if not texture or texture.startswith('/') or any(s in ('..','') for s in texture.split('/')) or ':' in texture:raise ValueError('Unsafe chain texture path')
    width=struct.unpack_from('<f',data,p+8)[0];scale=struct.unpack_from('<f',data,p+16)[0]
    color=list(data[p+156:p+161])
    if not np.isfinite([width,scale]).all() or not 0<width<=16 or not 0<scale<=32:raise ValueError('Unbounded chain width/scale')
    if color[4]!=3:raise ValueError('Only additive chain strips supported')
    return dict(id=chain_id,texture=texture,width=width,texcoord_scale=scale,alpha=color[0]/255,color=[v/255 for v in color[1:4]],blend=color[4])


def beam_frame(texture,record,time,flow,width=512,height=128):
    if flow not in (-1,1):raise ValueError('Flow must be -1 or 1')
    yy,xx=np.mgrid[:height,:width];x=xx/(width-1)
    # Only X is stretched by the Foundry adapter. The independent Y size keeps
    # beam thickness stable at all target distances.
    bend=.035*np.sin(2*np.pi*(2*x-time))*np.sin(np.pi*x)
    v=((yy+.5)/height-.125)/.75-bend
    u=x*record['texcoord_scale']+flow*2*time
    # Mirrored repeat avoids a hard cut when a legacy strip is not seamless.
    uv=1-np.abs((u%2)-1)
    tx=np.rint(uv*(texture.shape[1]-1)).astype(int)
    ty=np.clip((v*texture.shape[0]).astype(int),0,texture.shape[0]-1)
    pixels=texture[ty,tx].astype(np.float32)/255
    pixels[(v<0)|(v>=1)]=0
    emitted=pixels[:,:,:3]*pixels[:,:,3:4]*np.asarray(record['color'])*record['alpha']
    # Convert additive light to portable straight RGBA. Black padding must be
    # transparent on light maps; a black atlas rectangle is never exported.
    edge=np.minimum(1,np.minimum(x,1-x)*64)
    vertical=np.clip(np.minimum(v,1-v)*12,0,1)
    emitted*=(edge*vertical)[:,:,None]
    alpha=emitted.max(axis=-1,keepdims=True)
    rgb=np.divide(emitted,alpha,out=np.zeros_like(emitted),where=alpha>1e-7)
    return np.rint(np.clip(np.concatenate([rgb,alpha],axis=-1),0,1)*255).astype('uint8')


def bake(assets,out,profile,fps=30):
    if profile not in PROFILES:raise ValueError('Unknown beam profile')
    if not 10<=fps<=60:raise ValueError('fps 10..60')
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise ValueError('Output directory must be empty')
    spec=PROFILES[profile];data=assets.read(TABLE);record=chain_record(data,spec['chain_id']);texture=assets.image(record['texture'])
    out.mkdir(parents=True,exist_ok=True);frames=out/'frames';frames.mkdir()
    for i in range(fps):Image.fromarray(beam_frame(texture,record,i/fps,spec['flow'])).save(frames/f'{i:04d}.png')
    name=profile.split('.')[1]+'-beam.webm'
    subprocess.run(['ffmpeg','-v','error','-y','-framerate',str(fps),'-i',str(frames/'%04d.png'),'-c:v','libvpx-vp9','-pix_fmt','yuva420p','-b:v','0','-crf','24','-auto-alt-ref','0',str(out/name)],check=True)
    report=dict(format='wowmap.beam-bake/1',profile=profile,chain=record,flow=spec['flow'],size=[512,128],fps=fps,duration_ms=1000,
                sources=[dict(path=p,sha256=hashlib.sha256(assets.read(p)).hexdigest()) for p in [TABLE,record['texture']]],
                limitations=['original chain texture and ARGB tint; not a full WoW chain renderer','UV flow speed, mirrored wrapping, 2D bend and endpoint taper authored for tabletop use','no branching, chain jumps, impact flashes or sound'])
    (out/'bake-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assets',required=True);p.add_argument('--out',required=True);p.add_argument('--profile',required=True,choices=sorted(PROFILES));p.add_argument('--fps',type=int,default=30)
    a=p.parse_args()
    with RawAssets(a.assets) as assets:print(json.dumps(bake(assets,a.out,a.profile,a.fps),indent=2))

if __name__=='__main__':main()
