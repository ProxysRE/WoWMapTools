"""Small transparent video overlays made from explicitly chosen WoW textures.

This is an authored 2D loop, not emulation of the client's M2 particle system.
"""
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image


def smoke_frame(texture,frame,frames=48,size=256,seed=7,tint=(125,75,180)):
    if type(frames) is not int or not 8<=frames<=120 or type(size) is not int or not 64<=size<=512:raise ValueError('Invalid effect frame dimensions')
    if type(frame) is not int or not 0<=frame<=frames:raise ValueError('Invalid effect frame')
    if len(tint)!=3 or any(type(v) is not int or not 0<=v<=255 for v in tint):raise ValueError('Invalid effect tint')
    rgba=np.asarray(texture.convert('RGBA'),dtype=np.float32)/255
    # The original additive sprite stores coverage in intensity over black.
    coverage=np.clip(rgba[...,:3].max(axis=-1)*rgba[...,3],0,1)
    sprite=Image.fromarray(np.uint8(coverage*255),'L')
    alpha=np.zeros((size,size),dtype=np.float32);rng=random.Random(seed)
    for _ in range(9):
        phase=rng.random();x=rng.uniform(.32,.68);y=rng.uniform(.4,.7)
        scale=rng.uniform(.24,.45);drift=rng.uniform(-.10,.10)
        age=(frame/frames+phase)%1;opacity=math.sin(math.pi*age)**2*.28
        dim=max(1,round(size*scale*(.75+age*.5)))
        puff=np.asarray(sprite.resize((dim,dim),Image.Resampling.BILINEAR),dtype=np.float32)/255*opacity
        left=round(size*(x+drift*age)-dim/2);top=round(size*(y-age*.22)-dim/2)
        x0=max(0,left);y0=max(0,top);x1=min(size,left+dim);y1=min(size,top+dim)
        if x0>=x1 or y0>=y1:continue
        a=puff[y0-top:y1-top,x0-left:x1-left];dest=alpha[y0:y1,x0:x1];alpha[y0:y1,x0:x1]=a+dest*(1-a)
    pixels=np.zeros((size,size,4),dtype=np.uint8);pixels[...,:3]=tint;pixels[...,3]=np.uint8(np.clip(alpha,0,1)*255)
    pixels[pixels[...,3]==0,:3]=0
    return Image.fromarray(pixels,'RGBA')


def write_smoke_loop(assets,texture,out,frames=48,fps=16,size=256,seed=7):
    encoder=shutil.which('ffmpeg')
    if not encoder:raise ValueError('ffmpeg with libvpx-vp9 is required')
    if type(fps) is not int or not 8<=fps<=30:raise ValueError('Invalid effect frame rate')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    image=Image.fromarray(assets.image(texture));raw=assets.read(texture)
    first=smoke_frame(image,0,frames,size,seed)
    with tempfile.TemporaryDirectory(prefix='.effect-',dir=out) as temporary:
        stage=Path(temporary);target=stage/'void-mist.webm'
        command=[encoder,'-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','rgba','-video_size',f'{size}x{size}','-framerate',str(fps),'-i','pipe:0','-an','-c:v','libvpx-vp9','-pix_fmt','yuva420p','-auto-alt-ref','0','-lossless','1','-y',str(target)]
        with subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE) as process:
            try:
                for frame in range(frames):process.stdin.write(smoke_frame(image,frame,frames,size,seed).tobytes())
                process.stdin.close();error=process.stderr.read().decode();returncode=process.wait()
            except BaseException:
                process.kill();process.wait();raise
        if returncode:raise ValueError('WebM encoding failed: '+error)
        target.replace(out/'void-mist.webm')
    first.save(out/'void-mist-first.png')
    report=dict(source_texture=texture,source_sha256=hashlib.sha256(raw).hexdigest(),frames=frames,fps=fps,size=size,seed=seed,
                duration_seconds=frames/fps,kind='authored 2D smoke loop; not original M2 particle playback',
                tint=[125,75,180],video_sha256=hashlib.sha256((out/'void-mist.webm').read_bytes()).hexdigest())
    (out/'effect-provenance.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    import argparse
    from .models import RawAssets
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--texture',default='world/expansion01/doodads/netherstorm/crackeffects/smoke01_flip.blp')
    parser.add_argument('--seed',type=int,default=7)
    args=parser.parse_args()
    try:
        with RawAssets(args.packages) as assets:result=write_smoke_loop(assets,args.texture,args.out,seed=args.seed)
        print(json.dumps(result))
    except (OSError,ValueError) as error:parser.exit(1,'ERROR: '+str(error)+'\n')

if __name__=='__main__':main()
