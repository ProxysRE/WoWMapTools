"""Place static model sprites in a scene without losing the model's ground origin."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from .models import inspect_model, preview

LAYERS = ('ground', 'props', 'overhead')
CACHE_VERSION = 'm2-topdown-4'


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return value


def pair(value, label):
    if not isinstance(value, (list,tuple)) or len(value)!=2:
        raise ValueError(f'{label} must contain two coordinates')
    return [finite(v,label) for v in value]


def validate_objects(objects):
    if not isinstance(objects,list) or len(objects)>2000:
        raise ValueError('objects must be a list of up to 2000 entries')
    ids=set()
    for obj in objects:
        if not isinstance(obj.get('id'),str) or not obj['id'] or obj['id'] in ids:
            raise ValueError('Objects need unique nonempty string ids')
        ids.add(obj['id'])
        if not isinstance(obj.get('model'),str) or not obj['model'].lower().endswith('.m2'):
            raise ValueError('Each object needs a model M2 path')
        pair(obj['position'],'position')
        if obj.get('position_anchor','origin') not in ('origin','bounds-center'):raise ValueError('Invalid position_anchor')
        if finite(obj['size_cells'],'size_cells')<=0 or obj['size_cells']>200:
            raise ValueError('size_cells must be in (0, 200]')
        if not 0<finite(obj.get('scale',1),'scale')<=20:
            raise ValueError('scale must be in (0, 20]')
        finite(obj.get('rotation',0),'rotation');finite(obj.get('order',0),'order')
        if obj.get('layer','props') not in LAYERS:
            raise ValueError('layer must be ground, props or overhead')
        if not 0<=finite(obj.get('opacity',1),'opacity')<=1:
            raise ValueError('opacity must be in [0, 1]')
        shadow=obj.get('shadow',False)
        if shadow is not False:
            if not isinstance(shadow,dict): raise ValueError('shadow must be false or an object')
            pair(shadow.get('offset_cells',[.15,.2]),'shadow offset_cells')
            if not 0<=finite(shadow.get('opacity',.22),'shadow opacity')<=1:
                raise ValueError('shadow opacity must be in [0, 1]')
            if not 0<=finite(shadow.get('blur_cells',.15),'shadow blur_cells')<=3:
                raise ValueError('shadow blur_cells must be in [0, 3]')


def cached_sprite(assets, model, cache, resolution=768):
    info=inspect_model(assets,model)
    if info['missing']: raise ValueError('Missing model dependencies: '+', '.join(info['missing']))
    paths=[info['path']]+info['required_skins']+info['required_textures']
    digest=hashlib.sha256((CACHE_VERSION+str(resolution)).encode())
    for path in sorted(set(paths)):
        digest.update(path.encode());digest.update(hashlib.sha256(assets.read(path)).digest())
    key=digest.hexdigest();cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    png=cache/(key+'.png');meta=cache/(key+'.json')
    if png.exists() and meta.exists():
        try:
            metadata=json.loads(meta.read_text(encoding='utf-8'))
            if hashlib.sha256(png.read_bytes()).hexdigest()!=metadata['png_sha256']:
                raise ValueError('Damaged sprite cache')
            with Image.open(png) as image:
                image.load();return image.convert('RGBA'),metadata,True
        except (OSError,ValueError,KeyError): pass
    image,metadata=preview(assets,model,resolution)
    temp=png.with_suffix('.tmp');image.save(temp,format='PNG');temp.replace(png)
    metadata['png_sha256']=hashlib.sha256(png.read_bytes()).hexdigest()
    temp=meta.with_suffix('.tmp');temp.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(meta)
    return image,metadata,False


def transform_sprite(image, metadata, obj, ppc, canvas_size):
    """Inverse affine transform: rotation is clockwise in map coordinates.

    size_cells scales the maximum geometric XY extent (before rotation), not the padded PNG.
    The M2 origin remains fixed at position, even for an off-centre model.
    """
    position=np.array(obj['position'],dtype=float)*ppc
    bounds=np.asarray(metadata['world_xy_bounds'],dtype=float)
    geometry_span=float(np.max(bounds[1]-bounds[0]))*metadata['pixels_per_world_unit']
    if geometry_span<=0: raise ValueError('Invalid sprite projection metadata')
    scale=obj['size_cells']*obj.get('scale',1)*ppc/geometry_span
    angle=math.radians(obj.get('rotation',0)%360)
    c,s=math.cos(angle),math.sin(angle)
    matrix=np.array([[c,-s],[s,c]])*scale
    anchor=np.array(metadata['anchor_pixels'],dtype=float)
    if obj.get('position_anchor')=='bounds-center':anchor=np.array([image.width/2,image.height/2],dtype=float)
    corners=np.array([[0,0],[image.width,0],[image.width,image.height],[0,image.height]],dtype=float)
    transformed=(corners-anchor)@matrix.T+position
    low=np.floor(transformed.min(axis=0)).astype(int);high=np.ceil(transformed.max(axis=0)).astype(int)
    unclipped=[int(low[0]),int(low[1]),int(high[0]),int(high[1])]
    left=max(0,int(low[0]));top=max(0,int(low[1]))
    right=min(canvas_size[0],int(high[0]));bottom=min(canvas_size[1],int(high[1]))
    record=dict(id=obj['id'],model=obj['model'],position_pixels=position.tolist(),
                rotation_clockwise=obj.get('rotation',0)%360,layer=obj.get('layer','props'),
                position_anchor=obj.get('position_anchor','origin'),order=obj.get('order',0),size_cells=obj['size_cells'],scale=obj.get('scale',1),
                bounds_pixels=unclipped,visible=right>left and bottom>top)
    if not record['visible']:return None,(left,top),record
    inv=np.array([[c,s],[-s,c]])/scale
    offset=anchor+inv@(np.array([left,top])-position)
    affine=(inv[0,0],inv[0,1],offset[0],inv[1,0],inv[1,1],offset[1])
    patch=image.transform((right-left,bottom-top),Image.Transform.AFFINE,affine,resample=Image.Resampling.BICUBIC)
    opacity=obj.get('opacity',1)
    if opacity!=1:patch.putalpha(patch.getchannel('A').point(lambda value:round(value*opacity)))
    return patch,(left,top),record


def compose_objects(objects, raw, canvas_size, ppc, cache, progress=print):
    validate_objects(objects)
    prepared=defaultdict(list);placements=[];memo={};created=hits=0
    for index,obj in enumerate(objects):
        model=obj['model']
        if model not in memo:
            image,metadata,hit=cached_sprite(raw,model,cache)
            memo[model]=(image,metadata)
            hits+=int(hit);created+=int(not hit)
            progress(f"Model {len(memo)}: {Path(model).name} ({'cache' if hit else 'rendered'})",flush=True)
        image,metadata=memo[model]
        patch,position,record=transform_sprite(image,metadata,obj,ppc,canvas_size)
        placements.append(record)
        if patch is not None: prepared[obj.get('layer','props')].append((obj.get('order',0),index,obj,patch,position))
    ground=Image.new('RGBA',canvas_size);overhead=Image.new('RGBA',canvas_size)
    for layer in LAYERS:
        target=overhead if layer=='overhead' else ground
        rows=sorted(prepared[layer],key=lambda item:(item[0],item[1]))
        # Draw the layer's shadows first so they do not darken its own props.
        for _,_,obj,patch,position in rows:
            shadow=obj.get('shadow',False)
            if shadow is not False:
                blur=shadow.get('blur_cells',.15)*ppc
                pad=math.ceil(blur*3)+2
                alpha=Image.new('L',(patch.width+pad*2,patch.height+pad*2))
                alpha.paste(patch.getchannel('A'),(pad,pad))
                alpha=alpha.filter(ImageFilter.GaussianBlur(blur))
                alpha=alpha.point(lambda value:round(value*shadow.get('opacity',.22)))
                shade=Image.new('RGBA',alpha.size,(0,0,0,0));shade.putalpha(alpha)
                dx,dy=shadow.get('offset_cells',[.15,.2])
                target.alpha_composite(shade,(round(position[0]+dx*ppc)-pad,round(position[1]+dy*ppc)-pad))
        for _,_,obj,patch,position in rows: target.alpha_composite(patch,position)
    return ground,overhead,dict(objects=placements,unique_models=len(memo),sprites_rendered=created,sprites_from_cache=hits,
                               rotation='clockwise degrees',size_semantics='maximum unrotated model XY span in cells',
                               origin='top-left; Y down; object position is model origin',
                               overhead='whole objects assigned to overhead, not automatically separated crowns',
                               shadows='decorative baked drop shadows, not Foundry light occlusion')
