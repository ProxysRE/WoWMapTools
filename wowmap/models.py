"""Static M2 (WotLK v264) inspection and CPU orthographic previews.

Not a game renderer: no skeleton animation, billboarding, particles or shader effects.
"""
import argparse
from collections import OrderedDict
import gzip
import io
import json
from pathlib import Path
import struct
from zipfile import ZipFile
import numpy as np
from PIL import Image
from .pack import normalize


class RawAssets:
    def __init__(self, folder, verify_archives=False):
        self.files = {}
        self.archives = []
        self.cache = OrderedDict()
        try:
            folder=Path(folder)
            for path in sorted([*folder.glob('*.zip'),*(folder/'packages').glob('*.zip')]):
                archive = ZipFile(path)
                self.archives.append(archive)
                if verify_archives and archive.testzip() is not None:
                    raise ValueError(f'Corrupt ZIP: {path.name}')
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    name = normalize(info.filename)
                    if info.file_size > 256*1024*1024:
                        raise ValueError(f'Resource exceeds 256 MiB: {name}')
                    if name in self.files:
                        raise ValueError(f'Duplicate virtual resource: {name}')
                    self.files[name] = (archive, info)
            if not self.files:
                raise ValueError('No resource ZIP packages found')
        except Exception:
            self.close()
            raise

    def __enter__(self): return self
    def __exit__(self,*args): self.close()

    def close(self):
        for archive in self.archives: archive.close()

    def has(self, name): return normalize(name) in self.files

    def read(self, name):
        name = normalize(name)
        if name not in self.files:
            raise ValueError(f'Missing resource: {name}')
        archive, info = self.files[name]
        return archive.read(info)

    def image(self, name):
        name = normalize(name)
        if name not in self.cache:
            with Image.open(io.BytesIO(self.read(name))) as image:
                image.load()
                if max(image.size) > 4096:
                    raise ValueError(f'Texture too large for preview: {name}')
                self.cache[name] = np.asarray(image.convert('RGBA')).copy()
            if len(self.cache) > 32: self.cache.popitem(last=False)
        self.cache.move_to_end(name)
        return self.cache[name]


def array_at(data, header_offset, stride):
    if header_offset + 8 > len(data): raise ValueError('Truncated array header')
    count, offset = struct.unpack_from('<II',data,header_offset)
    if offset + count * stride > len(data): raise ValueError('Array outside model file')
    return count, offset


def model_info(data, name):
    if len(data) < 160 or data[:4] != b'MD20' or struct.unpack_from('<I',data,4)[0] != 264:
        raise ValueError('Only MD20 M2 version 264 (WotLK) is supported')
    count, offset = array_at(data,80,16)
    textures = []
    for i in range(count):
        kind, flags, length, start = struct.unpack_from('<IIII',data,offset+i*16)
        if start+length > len(data): raise ValueError('Texture name outside model file')
        filename = normalize(data[start:start+length].rstrip(b'\0').decode('utf-8')) if length and kind==0 else None
        textures.append(dict(kind=kind,flags=flags,path=filename))
    vertices, _ = array_at(data,60,48)
    views = struct.unpack_from('<I',data,68)[0]
    if not 1 <= views <= 8: raise ValueError('Invalid number of skin profiles')
    return dict(path=normalize(name),vertices=vertices,textures=textures,
                skins=[normalize(name[:-3]+f'{index:02d}.skin') for index in range(views)])


def inspect_model(assets, name):
    info = model_info(assets.read(name),name)
    info['missing'] = sorted({t['path'] for t in info['textures'] if t['path'] and not assets.has(t['path'])} |
                             {s for s in info['skins'] if not assets.has(s)})
    info['replaceable_texture_types'] = sorted({t['kind'] for t in info['textures'] if t['kind'] != 0})
    return info


def mesh_data(assets, name, texture_overrides=None):
    data = assets.read(name)
    info = inspect_model(assets,name)
    if info['missing']:
        raise ValueError('Missing dependencies: '+', '.join(info['missing']))
    overrides=texture_overrides or {}
    if not isinstance(overrides,dict) or any(type(k) is not int or k<=0 for k in overrides):
        raise ValueError('Texture overrides must map positive texture types to resource paths')
    if set(info['replaceable_texture_types'])-set(overrides):
        raise ValueError('Replaceable textures require explicit skin selection')
    if set(overrides)-set(info['replaceable_texture_types']):
        raise ValueError('Texture override type is not used by this model')
    for texture in info['textures']:
        if texture['kind']:
            texture['path']=normalize(overrides[texture['kind']])
            if not assets.has(texture['path']):raise ValueError('Missing selected skin: '+texture['path'])
    count, offset = array_at(data,60,48)
    vertex_dtype=np.dtype(dict(names=['position','weights','bones','normal','uv','uv2'],
                              formats=[('<f4',3),('u1',4),('u1',4),('<f4',3),('<f4',2),('<f4',2)],
                              offsets=[0,12,16,20,32,40],itemsize=48))
    vertices=np.frombuffer(data,dtype=vertex_dtype,count=count,offset=offset).copy()
    if not all(np.isfinite(vertices[key]).all() for key in ('position','normal','uv')):
        raise ValueError('Non-finite model geometry')
    skin=assets.read(info['skins'][0])
    if skin[:4]!=b'SKIN': raise ValueError('Invalid SKIN header')
    count,offset=array_at(skin,4,2); lookup=np.frombuffer(skin,dtype='<u2',count=count,offset=offset)
    count,offset=array_at(skin,12,2); indices=np.frombuffer(skin,dtype='<u2',count=count,offset=offset)
    if len(indices)%3 or (len(indices) and indices.max()>=len(lookup)) or (len(lookup) and lookup.max()>=len(vertices)):
        raise ValueError('Invalid triangle indices')
    count,offset=array_at(skin,28,48)
    sections=[struct.unpack_from('<10H',skin,offset+i*48) for i in range(count)]
    count,offset=array_at(skin,36,24)
    batches=[struct.unpack_from('<BB11H',skin,offset+i*24) for i in range(count)]
    count,offset=array_at(data,128,2); texture_lookup=np.frombuffer(data,dtype='<u2',count=count,offset=offset)
    count,offset=array_at(data,112,4); materials=[struct.unpack_from('<HH',data,offset+i*4) for i in range(count)]
    draws=[]
    for batch in batches:
        section_index,material_index,texture_count,combo=batch[3],batch[6],batch[8],batch[9]
        if section_index>=len(sections) or material_index>=len(materials) or combo>=len(texture_lookup):
            raise ValueError('Invalid material batch')
        if texture_count!=1: raise ValueError('Preview supports single-texture batches only')
        tex_index=int(texture_lookup[combo])
        if tex_index>=len(info['textures']): raise ValueError('Invalid texture lookup')
        flags,blend=materials[material_index]
        if blend not in (0,1,2): raise ValueError(f'Unsupported preview blend mode: {blend}')
        section=sections[section_index]
        start=section[4]+(section[1]<<16); length=section[5]
        if start+length>len(indices) or length%3: raise ValueError('Invalid section index range')
        triangles=lookup[indices[start:start+length]].reshape(-1,3)
        draws.append(dict(triangles=triangles,texture=info['textures'][tex_index]['path'],blend=blend,flags=flags))
    return vertices,draws,info


def preview(assets, name, size=512, texture_overrides=None, yaw=0, view='top'):
    if not 64<=size<=2048: raise ValueError('Preview size must be 64..2048')
    if isinstance(yaw,bool) or not isinstance(yaw,(int,float)) or not np.isfinite(yaw) or not -360<=yaw<=360:
        raise ValueError('Preview yaw must be finite degrees between -360 and 360')
    if view not in ('top','front'):raise ValueError('Preview view must be top or front')
    vertices,draws,info=mesh_data(assets,name,texture_overrides)
    if yaw:
        angle=np.deg2rad(yaw);c,s=np.cos(angle),np.sin(angle)
        rotation=np.array([[c,-s],[s,c]])
        for key in ('position','normal'):vertices[key][:,:2]=vertices[key][:,:2]@rotation.T
    if view=='front':
        # Camera at +X looks toward -X; screen-right = +Y, up = +Z.
        # Apply the same proper rotation to normals; this is not a mirrored image.
        for key in ('position','normal'):vertices[key][:]=vertices[key][:,[1,2,0]]
    xyz=vertices['position']; low=xyz[:,:2].min(axis=0); high=xyz[:,:2].max(axis=0)
    span=max(high-low)
    if span<1e-6: raise ValueError('Degenerate projected bounds')
    padding=max(8,round(size*.05)) if view=='front' else 8
    scale=(size-2*padding)/span;center=(low+high)/2
    screen=(xyz[:,:2]-center)*scale
    screen[:,0]+=size/2;screen[:,1]=size/2-screen[:,1]
    image=np.zeros((size,size,4),dtype=np.float32)
    depth=np.full((size,size),-np.inf,dtype=np.float32)
    light=np.array([-.3,.4,.85]);light=light/np.linalg.norm(light)
    # Base static pose only; no particle, ribbon, skeletal or UV animation evaluation.
    for draw in draws:
        tex=assets.image(draw['texture'])
        for tri in draw['triangles']:
            p=screen[tri]; uv=vertices['uv'][tri]; z=xyz[tri,2]
            xmin=max(0,int(np.floor(p[:,0].min())));xmax=min(size-1,int(np.ceil(p[:,0].max())))
            ymin=max(0,int(np.floor(p[:,1].min())));ymax=min(size-1,int(np.ceil(p[:,1].max())))
            if xmin>xmax or ymin>ymax: continue
            a,b,c=p
            denom=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(denom)<1e-8:continue
            yy,xx=np.mgrid[ymin:ymax+1,xmin:xmax+1];xx=xx+.5;yy=yy+.5
            w0=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denom
            w1=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denom
            w2=1-w0-w1
            covered=(w0>=-1e-5)&(w1>=-1e-5)&(w2>=-1e-5)
            weights=np.stack([w0,w1,w2],axis=-1)
            height=weights@z
            db=depth[ymin:ymax+1,xmin:xmax+1]
            covered &= height>db
            tuv=weights@uv
            tx=np.floor((tuv[:,:,0]%1)*tex.shape[1]).astype(int)%tex.shape[1]
            ty=np.floor((tuv[:,:,1]%1)*tex.shape[0]).astype(int)%tex.shape[0]
            color=tex[ty,tx].astype(np.float32)/255
            if draw['blend']==0: color[:,:,3]=1
            else: covered &= color[:,:,3]>=.5
            normals=weights@vertices['normal'][tri]
            shade=.65+.35*np.maximum(normals@light,0)
            if draw['flags']&1:shade=np.ones_like(shade)
            color[:,:,:3]*=shade[:,:,None]
            dest=image[ymin:ymax+1,xmin:xmax+1]
            dest[covered]=color[covered];db[covered]=height[covered]
    if not image[:,:,3].any(): raise ValueError(f'No visible {view} triangles')
    pivot=[size/2-center[0]*scale,size/2+center[1]*scale]
    metadata=dict(path=normalize(name),pixels=size,world_xy_bounds=[low.tolist(),high.tolist()],
                  anchor_pixels=[float(v) for v in pivot],pixels_per_world_unit=float(scale),
                  limitations=['static base pose','no billboarding','no particles or ribbons',
                               'single texture per batch','alpha blend approximated by cutout'])
    if texture_overrides:metadata['selected_textures']={str(k):normalize(v) for k,v in texture_overrides.items()}
    if yaw:metadata['yaw_degrees']=yaw
    if view=='front':
        metadata['view']='front';metadata['camera_axes']=['+Y','+Z','+X']
        metadata['projected_bounds']=metadata.pop('world_xy_bounds')
        metadata['padding_pixels']=padding
    return Image.fromarray(np.uint8(np.clip(image,0,1)*255)),metadata


def main():
    parser=argparse.ArgumentParser(description='Inspect static WotLK M2 dependencies and render top-down previews')
    parser.add_argument('command',choices=['audit','preview'])
    parser.add_argument('--packages',required=True)
    parser.add_argument('--model')
    parser.add_argument('--catalog',help='Optional full catalog.jsonl.gz to locate missing dependencies')
    parser.add_argument('--filter',default='ashenvale')
    parser.add_argument('--size',type=int,default=512)
    parser.add_argument('--out',default='output/models')
    args=parser.parse_args()
    try:
        with RawAssets(args.packages) as assets:
            out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
            if args.command=='audit':
                reports=[]
                for name in sorted(assets.files):
                    if name.endswith('.m2') and args.filter.lower() in name:
                        try:reports.append(inspect_model(assets,name))
                        except ValueError as error:reports.append(dict(path=name,error=str(error)))
                if args.catalog:
                    with gzip.open(args.catalog,'rt',encoding='utf-8') as stream:
                        catalog={r['path']:r for r in (json.loads(line) for line in stream)}
                    for report in reports:
                        report['missing_packages']=sorted({catalog[path]['package'] for path in report.get('missing',[]) if path in catalog})
                        report['not_in_catalog']=[path for path in report.get('missing',[]) if path not in catalog]
                (out/'audit.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
                print(f'Inspected {len(reports)} models; see {out / "audit.json"}')
            else:
                if not args.model:raise ValueError('--model is required for preview')
                image,metadata=preview(assets,args.model,args.size)
                image.save(out/'model.png')
                (out/'model.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
                print(out/'model.png')
    except (ValueError,OSError,struct.error) as error:
        print(f'ERROR: {error}');return 1
    return 0


if __name__=='__main__': raise SystemExit(main())
