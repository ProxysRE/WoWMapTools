"""Dependency diagnostics and proof sheets at the actual map scale.

Visible triangles and numerical metrics cannot certify artistic readability.
Optional decision signatures record an author's visual choice, and expire when
rendered source pixels or placement appearance change. No user approval UI.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from .catalog import load,requirements
from .models import RawAssets
from .objects import cached_sprite,transform_sprite
from .planning import expand


def review_plans(plans,raw,output,records=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if records is None:
        records={p:dict(path=p,id=p,package=Path(a.filename).name) for p,(a,_) in raw.files.items()}
    diagnostics={key:requirements(plan,records,raw) for key,plan in plans.items()}
    variants={}
    for key,source in plans.items():
        plan=expand(source)[0]
        for obj in plan.get('objects',[]):
            style={k:obj.get(k,default) for k,default in [('model',None),('size_cells',None),('scale',1),('rotation',0),('opacity',1)]}
            style['pixels_per_cell']=plan['pixels_per_cell']
            identity=json.dumps(style,sort_keys=True)
            if identity not in variants:variants[identity]=dict(style=style,instances=[])
            variants[identity]['instances'].append(dict(scene=key,id=obj['id']))
    entries=[];tiles=[]
    for identity,row in sorted(variants.items()):
        style=row['style'];model=style['model'];record=dict(**row,count=len(row['instances']))
        try:
            sprite,metadata,_=cached_sprite(raw,model,output/'.sprite-cache')
            extent=style['size_cells']*style['scale']*style['pixels_per_cell']
            side=max(64,int(np.ceil(extent*1.5+32)))
            if side>4096:raise ValueError('Proof image exceeds 4096px; reduce review scale explicitly')
            obj=dict(style,id='proof',position=[side/(2*style['pixels_per_cell'])]*2,position_anchor='bounds-center')
            actual,position,_=transform_sprite(sprite,metadata,obj,style['pixels_per_cell'],(side,side))
            if actual is None:raise ValueError('No visible proof sprite')
            transparent=Image.new('RGBA',(side,side));transparent.alpha_composite(actual,position)
            bbox=transparent.getbbox()
            if bbox is None:raise ValueError('Proof sprite is transparent')
            transparent=transparent.crop(bbox)
            alpha=np.asarray(transparent.getchannel('A'))>127
            luminance=np.asarray(transparent.convert('RGB'),dtype=np.float32).mean(axis=-1)[alpha]
            variation=float(np.std(luminance)) if len(luminance) else 0
            record.update(visible_pixels=int(alpha.sum()),pixel_bounds=list(transparent.size),luminance_std=round(variation,3),warnings=[])
            record['effect_features']=metadata.get('effect_features',{})
            record['warnings'].extend(record['effect_features'].get('warnings',[]))
            if 6 in metadata.get('blend_modes',[]):record['warnings'].append('Mod2x is flattened over object coverage only; inspect against map')
            if min(transparent.size)<16:record['warnings'].append('projected narrow dimension below 16 pixels')
            if variation<8:record['warnings'].append('low top-down tonal variation; inspect manually')
            signature=hashlib.sha256(identity.encode()+str(transparent.size).encode()+transparent.tobytes()).hexdigest()
            record['signature']=signature;record['image']='objects/'+signature+'.png'
            path=output/record['image'];path.parent.mkdir(exist_ok=True);transparent.save(path)
            tile=Image.new('RGB',(640,410),'#303640');draw=ImageDraw.Draw(tile)
            draw.text((12,10),Path(model).name,fill='white')
            draw.text((12,28),f"{style['size_cells']} cells x {style['scale']}; {style['pixels_per_cell']} px/cell; rot {style['rotation']}; instances {record['count']}",fill='white')
            fit=transparent.copy();fit.thumbnail((290,270));tile.paste(fit,(12+(290-fit.width)//2,70+(270-fit.height)//2),fit)
            draw.text((12,350),'Fitted preview',fill='white')
            w,h=transparent.size;left=max(0,(w-300)//2);top=max(0,(h-270)//2)
            native=transparent.crop((left,top,min(w,left+300),min(h,top+270)))
            tile.paste(native,(330+(300-native.width)//2,70+(270-native.height)//2),native)
            draw.text((330,350),'Actual map pixels'+(' (crop)' if w>300 or h>270 else ''),fill='white')
            draw.text((12,375),'ID: '+signature[:20],fill='#bdd4ee');tiles.append(tile)
        except (ValueError,KeyError) as error:record['error']=str(error)
        entries.append(record)
    pages=[]
    for page in range(0,len(tiles),8):
        subset=tiles[page:page+8];sheet=Image.new('RGB',(1280,410*((len(subset)+1)//2)),'#202630')
        for i,tile in enumerate(subset):sheet.paste(tile,((i%2)*640,(i//2)*410))
        name=f'objects-{page//8+1:02d}.jpg';sheet.save(output/name,quality=94);pages.append(name)
    result=dict(format='wowmap.visual-review/1',diagnostics=diagnostics,objects=entries,pages=pages,
                dependencies_complete=all(x['dependencies_complete'] for x in diagnostics.values()),
                note='Inspect sheets at native map scale before selecting models. Metrics do not certify readability.')
    (output/'review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def verify_decisions(review,decisions,repeat_threshold=8):
    if decisions.get('format')!='wowmap.visual-decisions/1':raise ValueError('Invalid visual decisions format')
    accepted=decisions.get('accepted',{})
    if not isinstance(accepted,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() for k,v in accepted.items()):
        raise ValueError('Visual decisions need signature -> nonempty review note')
    counts=defaultdict(int)
    for row in review['objects']:counts[row['style']['model']]+=row['count']
    failures=[]
    for row in review['objects']:
        if row.get('error'):failures.append(row['style']['model']+': '+row['error'])
        elif (counts[row['style']['model']]>=repeat_threshold or row.get('effect_features',{}).get('warnings') or any('Mod2x' in w for w in row.get('warnings',[]))) and row['signature'] not in accepted:
            failures.append(row['style']['model']+': unreviewed or stale appearance '+row['signature'])
    if not review['dependencies_complete']:failures.append('Resource dependencies are incomplete; inspect review.json')
    if failures:raise ValueError('Visual review failed: '+'; '.join(failures))
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',action='append',required=True)
    parser.add_argument('--packages',required=True);parser.add_argument('--catalog')
    parser.add_argument('--out',required=True);parser.add_argument('--decisions')
    args=parser.parse_args()
    try:
        plans={str(Path(p)):json.loads(Path(p).read_text(encoding='utf-8-sig')) for p in args.plan}
        with RawAssets(args.packages) as raw:result=review_plans(plans,raw,args.out,load(args.catalog) if args.catalog else None)
        if args.decisions:verify_decisions(result,json.loads(Path(args.decisions).read_text(encoding='utf-8-sig')))
        print(json.dumps(dict(report=str(Path(args.out)/'review.json'),appearances=len(result['objects']),pages=len(result['pages']),dependencies_complete=result['dependencies_complete'])))
        return 0 if result['dependencies_complete'] and not any(r.get('error') for r in result['objects']) else 1
    except (OSError,ValueError,KeyError) as error:parser.exit(1,f'ERROR: {error}\n')


if __name__=='__main__':raise SystemExit(main())
