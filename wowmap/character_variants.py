"""Deterministic, resource-checked appearance batches, independent of NPC stats."""
import argparse
import copy
import itertools
import json
import random
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from .characters import CharacterDB, RACES, SLOTS, character_options, section_allowed
from .models import RawAssets

FIELDS=('skin','face','hair_style','hair_color','facial_hair')


def _choice(values,rng,fixed,key):
    values=sorted(set(values))
    if key in fixed:
        if fixed[key] not in values:raise ValueError('No declared option for '+key+'='+str(fixed[key]))
        return fixed[key]
    if not values:raise ValueError('No declared options for '+key)
    return rng.choice(values)


def candidate_character(db,body,rng):
    """Respect the DBC's skin/face and hairstyle/color relationships."""
    fixed=body.get('character',{})
    character_options(fixed,{}) # Validate names and types, but do not freeze defaults.
    race=next(k for k,v in RACES.items() if v==fixed.get('race','human'))
    sex=0 if fixed.get('gender','male')=='male' else 1
    profile=fixed.get('profile','normal')
    table=db.tables['charsections']
    sections=[k for k,row in db.sections.items() if k[:2]==(race,sex) and section_allowed(table.cell(row,7),profile,race)]
    has_faces=any(k[:3]==(race,sex,1) for k in db.sections)
    faces_for=lambda skin:sorted({k[3] for k in sections if k[2]==1 and k[4]==skin}) if has_faces else [0]
    skins=sorted({k[4] for k in sections if k[2]==0})
    skins=[skin for skin in skins if faces_for(skin) and ('face' not in fixed or fixed['face'] in faces_for(skin))]
    skin=_choice(skins,rng,fixed,'skin')
    face=_choice(faces_for(skin),rng,fixed,'face')
    styles=sorted({k[2] for k in db.hair if k[:2]==(race,sex)})
    has_hair_sections=any(k[:3]==(race,sex,3) for k in db.sections)
    if not styles and not has_hair_sections:styles=[0]
    colors_for=lambda style:sorted({k[4] for k in sections if k[2:4]==(3,style)}) if has_hair_sections else [0]
    def features_for(color):
        features=[k[2] for k in db.facial if k[:2]==(race,sex)]
        return [feature for feature in features if (race,sex,2,feature,color) not in db.sections or section_allowed(table.cell(db.sections[race,sex,2,feature,color],7),profile,race)] or ([0] if not features else [])
    def colors_allowed(style):
        return [color for color in colors_for(style) if features_for(color) and ('facial_hair' not in fixed or fixed['facial_hair'] in features_for(color))]
    styles=[style for style in styles if colors_allowed(style) and ('hair_color' not in fixed or fixed['hair_color'] in colors_allowed(style))]
    hair_style=_choice(styles,rng,fixed,'hair_style')
    hair_color=_choice(colors_allowed(hair_style),rng,fixed,'hair_color')
    facial_hair=_choice(features_for(hair_color),rng,fixed,'facial_hair')
    return dict(race=RACES[race],gender='male' if sex==0 else 'female',profile=profile,skin=skin,face=face,
                hair_style=hair_style,hair_color=hair_color,facial_hair=facial_hair)


def validate_request(request):
    if not isinstance(request,dict) or set(request)-{'format','seed','count','bodies','outfits','portrait_yaw'}:
        raise ValueError('Unsupported variant request fields')
    if request.get('format')!='wowmap.character-variants.request/1':raise ValueError('Expected wowmap.character-variants.request/1')
    if type(request.get('seed')) is not int:raise ValueError('seed must be an integer')
    if type(request.get('count')) is not int or not 1<=request['count']<=24:raise ValueError('count must be 1..24')
    for name in ('bodies','outfits'):
        rows=request.get(name)
        if not isinstance(rows,list) or not 1<=len(rows)<=24:raise ValueError(name+' must contain 1..24 entries')
        ids=set()
        for row in rows:
            if not isinstance(row,dict):raise ValueError(name+' entries must be objects')
            identifier=row.get('id')
            if not isinstance(identifier,str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,47}',identifier) or identifier in ids:raise ValueError('Unique ASCII '+name+' IDs required')
            ids.add(identifier)
            allowed={'id','character'} if name=='bodies' else {'id','equipment','equipment_pools','pose'}
            if set(row)-allowed:raise ValueError('Unsupported '+name+' fields')
            if name=='bodies':character_options(row.get('character',{}),{})
            else:
                character_options({},row.get('equipment',{}))
                pools=row.get('equipment_pools',{})
                if not isinstance(pools,dict) or set(pools)-set(SLOTS):raise ValueError('Unknown equipment_pools slot')
                if set(pools)&set(row.get('equipment',{})):raise ValueError('A slot cannot be both fixed and in equipment_pools')
                for slot,choices in pools.items():
                    if not isinstance(choices,list) or not 1<=len(choices)<=100:raise ValueError('equipment_pools requires 1..100 choices per slot')
                    if any(item is not None and (type(item) is not int or not 0<item<=0xffffffff) for item in choices):raise ValueError('equipment_pools accepts positive uint32 Item IDs or null')
                    if len(set(choices))!=len(choices):raise ValueError('Duplicate equipment_pools choices would bias random selection')
                from .poses import pose_options
                pose_options('calm' if row.get('pose') is None else row['pose'])
    yaw=request.get('portrait_yaw',30)
    if isinstance(yaw,bool) or not isinstance(yaw,(int,float)) or not -180<=yaw<=180:raise ValueError('portrait_yaw must be finite degrees -180..180')


def balanced_pairs(bodies,outfits,count,rng):
    """Prefer unused pairs and underrepresented bodies/outfits; seeded tie breaks."""
    body_counts=Counter();outfit_counts=Counter();pairs=list(itertools.product(bodies,outfits));remaining=[];result=[]
    for _ in range(count):
        if not remaining:remaining=list(pairs)
        def score(pair):
            b,o=pair;bc=body_counts[b['id']];oc=outfit_counts[o['id']]
            return (bc+oc,max(bc,oc))
        best=min(map(score,remaining));eligible=[pair for pair in remaining if score(pair)==best]
        pair=rng.choice(eligible);remaining.remove(pair);result.append(pair)
        body_counts[pair[0]['id']]+=1;outfit_counts[pair[1]['id']]+=1
    return result


def candidate_equipment(outfit,rng):
    equipment=copy.deepcopy(outfit.get('equipment',{}))
    for slot,choices in sorted(outfit.get('equipment_pools',{}).items()):
        item=rng.choice(choices)
        if item is not None:equipment[slot]=item
    return equipment


def plan_variants(db,raw,request):
    validate_request(request)
    rng=random.Random(request['seed']);count=request['count'];variants=[];seen=set();rejections=Counter()
    pairs=balanced_pairs(request['bodies'],request['outfits'],count,rng)
    current_pair=-1;pair_attempts=0
    for attempt in range(count*80):
        if current_pair!=len(variants):current_pair=len(variants);pair_attempts=0
        pair_attempts+=1
        if pair_attempts>80:break
        body,outfit=pairs[len(variants)]
        try:
            character=candidate_character(db,body,rng)
            appearance=dict(character=character,equipment=candidate_equipment(outfit,rng),
                            pose=copy.deepcopy('calm' if outfit.get('pose') is None else outfit['pose']),yaw=-90,
                            portrait_yaw=request.get('portrait_yaw',30),size=512,portrait_size=640)
            identity=json.dumps(appearance,sort_keys=True)
            if identity in seen:continue
            seen.add(identity)
            prepared=db.prepare(raw,character,appearance['equipment'],appearance['pose'])
            omitted=prepared['metadata'].get('omitted_optional_overlays',[])
            # Secondary scalp blends can be absent in original DBC/client sets.
            # Primary body/hair materials still pass the actual mesh resolver.
            blocked=[row for row in omitted if row.get('kind') not in ('scalp_overlay','facial_overlay')]
            if blocked:raise ValueError('Selected appearance has omitted overlays: '+str(blocked))
        except (ValueError,KeyError) as error:
            rejections[str(error)]+=1;continue
        variants.append(dict(id='variant-'+str(len(variants)+1).zfill(2),body=body['id'],outfit=outfit['id'],appearance=appearance,warnings=omitted))
        if len(variants)==count:break
    if len(variants)!=count:
        raise ValueError('Only '+str(len(variants))+'/'+str(count)+' distinct valid variants; reduce count or expand choices. Rejections: '+json.dumps(dict(rejections),ensure_ascii=False))
    return dict(format='wowmap.character-variants/1',algorithm='balanced-conditional/2',seed=request['seed'],variants=variants,
                coverage=dict(bodies=dict(Counter(r['body'] for r in variants)),outfits=dict(Counter(r['outfit'] for r in variants))),
                rejections=dict(rejections),validation='assembled resources and requested skeletal pose; visual review still required')


def build_variants(request,dbc_assets,model_assets,out):
    """Stage all images; failed generation never publishes a partial batch."""
    validate_request(request);out=Path(out).resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):raise ValueError('Output must be empty')
    db=CharacterDB(dbc_assets)
    with RawAssets(model_assets) as raw:result=plan_variants(db,raw,request)
    from .tokens import TokenAssets
    tokens=TokenAssets(dbc_assets,model_assets)
    with tokens.session():
        for row in result['variants']:row['images']=tokens.pair(row['appearance'])
    result['media']=list(tokens.media.values());result['dbc_sha256']=db.hashes
    grouped={}
    for row in result['variants']:grouped.setdefault(tuple(row['images'].values()),[]).append(row['id'])
    result['same_rendered_images']=[ids for ids in grouped.values() if len(ids)>1]
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.variants-',dir=out.parent) as temporary:
        stage=Path(temporary);tokens.write(stage)
        (stage/'variants.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (stage/'request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2)+'\n')
        contact_sheet(stage,result)
        if out.exists():out.rmdir()
        shutil.move(str(stage),str(out))
    return result


def contact_sheet(root,result):
    from PIL import Image,ImageDraw,ImageFont
    font=None
    for name in ('DejaVuSans.ttf','arial.ttf'):
        try:font=ImageFont.truetype(name,14);break
        except OSError:pass
    if font is None:font=ImageFont.load_default(size=14)
    rows=result['variants'];sheet=Image.new('RGB',(1200,((len(rows)+2)//3)*400),'#252a35');draw=ImageDraw.Draw(sheet)
    for i,row in enumerate(rows):
        x=i%3*400;y=i//3*400
        image=Image.open(root/row['images']['portrait']).convert('RGBA');image.thumbnail((260,280));sheet.paste(image,(x+(270-image.width)//2,y+5),image)
        token=Image.open(root/row['images']['token']).convert('RGBA');token.thumbnail((110,110));sheet.paste(token,(x+280+(110-token.width)//2,y+85),token)
        c=row['appearance']['character']
        def label(text,line,color='#c5cfdd'):
            while draw.textlength(text,font=font)>380:text=text[:-4]+'...'
            draw.text((x+8,y+288+line*19),text,font=font,fill=color)
        label(row['id']+' / '+row['body'],0,'white')
        label('outfit: '+row['outfit'],1)
        label('skin/face/hair/color/feature: '+ '/'.join(str(c[k]) for k in FIELDS),2)
        label('pose '+(str(row['appearance']['pose']) if isinstance(row['appearance']['pose'],str) else 'animation '+str(row['appearance']['pose']['animation_id']))+' / token yaw -90',3)
        if row.get('warnings'):label(str(len(row['warnings']))+' optional overlay warnings; see variants.json',4,'#f0c060')
    sheet.save(root/'variants-review.jpg',quality=95)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True);parser.add_argument('--dbc-assets',required=True)
    parser.add_argument('--model-assets',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args()
    try:
        path=Path(args.request)
        if path.stat().st_size>1024*1024:raise ValueError('Request exceeds one MiB')
        result=build_variants(json.loads(path.read_text(encoding='utf-8-sig')),args.dbc_assets,args.model_assets,args.out)
        print(json.dumps(dict(variants=len(result['variants']),media=len(result['media']),out=str(Path(args.out).resolve()))))
    except (ValueError,KeyError,OSError) as error:parser.exit(1,'ERROR: '+str(error)+'\n')

if __name__=='__main__':main()
