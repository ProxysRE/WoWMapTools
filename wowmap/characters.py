"""WotLK human clothing assembly: original texture layers and selected M2 geosets.

Schemas are pinned to 3.3.5.12340 (WoWDBDefs). Atlas regions and equipment
ordering follow the legacy client layout documented in WoW Model Viewer.
This module does not guess attachments, bone poses, or unsupported races.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import numpy as np
from PIL import Image

from .dbc import DBC
from .models import RawAssets, array_at, model_info, preview
from .pack import normalize

SCHEMA='3.3.5.12340'
ATLAS='generated/human-body-atlas.png'
# Coordinates in the original 256-unit layout; original human skins are 512px.
REGIONS={
    'arm_upper':(0,0,128,64), 'arm_lower':(0,64,128,64), 'hand':(0,128,128,32),
    'face_upper':(0,160,128,32), 'face_lower':(0,192,128,64),
    'torso_upper':(128,0,128,64), 'torso_lower':(128,64,128,32),
    'leg_upper':(128,96,128,64), 'leg_lower':(128,160,128,64), 'foot':(128,224,128,32),
}
COMPONENTS=['arm_upper','arm_lower','hand','torso_upper','torso_lower','leg_upper','leg_lower','foot']
FOLDERS=['ArmUpperTexture','ArmLowerTexture','HandTexture','TorsoUpperTexture',
         'TorsoLowerTexture','LegUpperTexture','LegLowerTexture','FootTexture']
SLOTS={'shirt':{4},'chest':{5,20},'legs':{7},'boots':{8},'gloves':{10},'belt':{6},'bracers':{9}}
TABLES={'charsections':10,'charhairgeosets':6,'characterfacialhairstyles':8,'itemdisplayinfo':25,'item':8}


def integer(value,label):
    if type(value) is not int or not 0<=value<=0xffffffff:raise ValueError(label+' must be a nonnegative integer')
    return value


def character_options(character,equipment):
    if not isinstance(character,dict) or set(character)-{'race','gender','skin','face','hair_style','hair_color','facial_hair'}:
        raise ValueError('character contains unsupported appearance fields')
    if character.get('race','human')!='human':raise ValueError('Character assembly currently supports human only')
    if character.get('gender','male') not in ('male','female'):raise ValueError('gender must be male or female')
    result=dict(race='human',gender=character.get('gender','male'))
    for field,default in [('skin',0),('face',0),('hair_style',1),('hair_color',0),('facial_hair',0)]:
        result[field]=integer(character.get(field,default),field)
    if not isinstance(equipment,dict) or set(equipment)-set(SLOTS):
        raise ValueError('Equipment supports shirt, chest, legs, boots, gloves, belt and bracers only; attachments are not implemented')
    return result,{s:integer(i,'equipment item ID') for s,i in sorted(equipment.items())}


def composite_layer(atlas,image,region):
    x,y,w,h=REGIONS[region];factor=atlas.width//256
    layer=image.convert('RGBA').resize((w*factor,h*factor),Image.Resampling.LANCZOS)
    atlas.alpha_composite(layer,(x*factor,y*factor))


class AssemblyAssets:
    """Virtual atlas plus original resource access, recording actual dependencies."""
    def __init__(self,raw,atlas=None):
        self.raw=raw;self.atlas=atlas;self.used=set()

    def has(self,name):return name==ATLAS and self.atlas is not None or self.raw.has(name)

    def read(self,name):
        name=normalize(name);self.used.add(name)
        return self.raw.read(name)

    def image(self,name):
        name=normalize(name)
        if name==ATLAS and self.atlas is not None:return self.atlas
        self.used.add(name)
        return self.raw.image(name)


class CharacterDB:
    def __init__(self,folder):
        self.tables={};self.hashes={}
        with RawAssets(folder) as raw:
            for name,fields in TABLES.items():
                data=raw.read('dbfilesclient/'+name+'.dbc');table=DBC(data)
                if table.fields!=fields or table.record_size!=fields*4:
                    raise ValueError(name+' does not match supported 3.3.5 schema')
                self.tables[name]=table;self.hashes[name]=hashlib.sha256(data).hexdigest()
        self.sections={};self.hair={};self.facial={};self.items={};self.displays={}
        for name,target in [('item',self.items),('itemdisplayinfo',self.displays)]:
            table=self.tables[name]
            for row in range(table.records):
                key=table.cell(row,0)
                if key in target:raise ValueError('Duplicate '+name+' ID')
                target[key]=row
        for name,target,cols in [('charsections',self.sections,(2,3,8,9)),
                                ('charhairgeosets',self.hair,(2,3)),
                                ('characterfacialhairstyles',self.facial,(1,2))]:
            table=self.tables[name];race_column=0 if name=='characterfacialhairstyles' else 1
            for row in range(table.records):
                if table.cell(row,race_column)!=1:continue
                if name=='charsections' and not table.cell(row,7)&1:continue
                key=tuple(table.cell(row,c) for c in cols)
                if key in target:raise ValueError('Ambiguous human '+name+' selection')
                target[key]=row

    def section(self,gender,kind,variation,color,required=True):
        row=self.sections.get((gender,kind,variation,color))
        if row is None:
            if required:raise ValueError(f'Unknown human appearance section: {kind}/{variation}/{color}')
            return []
        return [normalize(s) if s else '' for s in (self.tables['charsections'].cell(row,c,'string') for c in (4,5,6))]

    def equipment(self,slot,item_id):
        if type(item_id) is not int or item_id<=0 or item_id not in self.items:raise ValueError('Unknown positive equipment Item ID')
        item=self.tables['item'];row=self.items[item_id];inventory=item.cell(row,6)
        if inventory not in SLOTS[slot]:raise ValueError(f'Item {item_id} does not belong in slot {slot}')
        display_id=item.cell(row,5)
        if display_id not in self.displays:raise ValueError('Item references an unknown ItemDisplayInfo ID')
        d=self.tables['itemdisplayinfo'];r=self.displays[display_id]
        # Separate component models / item visuals need an attachment/effect implementation.
        if any(d.cell(r,c,'string') for c in (1,2)) or d.cell(r,23) or d.cell(r,24):
            raise ValueError(f'Item {item_id} includes model attachments or visual effects; not implemented')
        return dict(item_id=item_id,display_id=display_id,inventory_type=inventory,
                    geosets=[d.cell(r,c) for c in (7,8,9)],icon=d.cell(r,5,'string'),
                    textures=[d.cell(r,c,'string') for c in range(15,23)])

    def search(self,query,slot=None,limit=30):
        if not isinstance(query,str) or not query.strip() or type(limit) is not int or not 1<=limit<=100:
            raise ValueError('Search needs text and limit 1..100')
        if slot is not None and slot not in SLOTS:raise ValueError('Unsupported clothing slot')
        words=query.lower().split();matches=[];d=self.tables['itemdisplayinfo'];items=self.tables['item']
        allowed=SLOTS[slot] if slot else set.union(*SLOTS.values())
        for item_id,row in self.items.items():
            if items.cell(row,6) not in allowed:continue
            display=items.cell(row,5);r=self.displays.get(display)
            if r is None:continue
            text=' '.join(d.cell(r,c,'string') for c in [5,*range(15,23)]).lower()
            if all(w in text for w in words):
                matches.append(dict(item_id=item_id,display_id=display,inventory_type=items.cell(row,6),icon=d.cell(r,5,'string')))
        return dict(matches=len(matches),items=sorted(matches,key=lambda r:r['item_id'])[:limit],
                    note='Search uses original icon/component filenames, not localized item names; assembly validates support separately.')

    @staticmethod
    def texture(raw,index,name,gender):
        if not name:return None
        if '/' in name or '\\' in name or '.' in name:raise ValueError('Unsupported equipment texture component name')
        stem='item/texturecomponents/'+FOLDERS[index].lower()+'/'+name.lower()
        sex='m' if gender==0 else 'f'
        candidates=[stem+'_'+suffix+'.blp' for suffix in (['u',sex] if name.lower().endswith('_ll') else [sex,'u'])]+[stem+'.blp']
        for candidate in candidates:
            if raw.has(candidate):return candidate
        raise ValueError('Missing clothing texture; expected one of: '+', '.join(candidates))

    def assemble(self,raw,character,equipment):
        character,equipment=character_options(character,equipment);gender=0 if character['gender']=='male' else 1
        assets=AssemblyAssets(raw);skin=character['skin'];hair_color=character['hair_color'];hair_style=character['hair_style']
        base=self.section(gender,0,0,skin)
        atlas=Image.fromarray(assets.image(base[0])).convert('RGBA')
        if atlas.size not in ((256,256),(512,512)):raise ValueError('Unsupported human body atlas dimensions')
        atlas=atlas.resize((512,512),Image.Resampling.LANCZOS)
        layers=[dict(region='base',path=base[0])]
        def add(path,region):
            if not path:return
            composite_layer(atlas,Image.fromarray(assets.image(path)),region);layers.append(dict(region=region,path=path))
        underwear=self.section(gender,4,0,skin)
        for texture,region in zip(underwear,['leg_upper','torso_upper']):add(texture,region)
        face=self.section(gender,1,character['face'],skin)
        for texture,region in zip(face,['face_lower','face_upper']):add(texture,region)
        facial_row=self.facial.get((gender,character['facial_hair']))
        if facial_row is None and character['facial_hair']!=0:raise ValueError('Unknown human facial hair / feature style')
        facial=self.section(gender,2,character['facial_hair'],hair_color,required=False)
        for texture,region in zip(facial,['face_lower','face_upper']):add(texture,region)
        hair_row=self.hair.get((gender,hair_style))
        if hair_row is None:raise ValueError('Unknown human hairstyle')
        hair_table=self.tables['charhairgeosets'];hair_geoset=hair_table.cell(hair_row,4);bald=bool(hair_table.cell(hair_row,5))
        hair=self.section(gender,3,hair_style,hair_color)
        if not bald:
            for texture,region in zip(hair[1:],['face_lower','face_upper']):add(texture,region)
        groups={n:1 for n in range(1,19)}
        groups.update({1:0,2:0,3:0,7:2,15:0,17:0})
        if facial_row is not None:
            t=self.tables['characterfacialhairstyles']
            groups.update({1:t.cell(facial_row,3),3:t.cell(facial_row,4),2:t.cell(facial_row,5)})
        gear={slot:self.equipment(slot,item) for slot,item in equipment.items()}
        robe=any(g['geosets'][2]==1 or g['inventory_type']==20 for g in gear.values())
        order=['shirt','legs','boots','chest','belt','bracers','gloves']
        if robe:
            order=['shirt','boots','legs','bracers','chest','gloves','belt']
            if 'gloves' in gear and gear['gloves']['geosets'][0]==0:order[4:6]=['gloves','chest']
        for slot in order:
            if slot not in gear:continue
            g=gear[slot];flags=g['geosets']
            if slot in ('shirt','chest'):
                groups[8]=1+flags[0];indices=[0,1,3,4]
                if g['inventory_type']==20 or flags[2]==1:indices+=[5,6]
            elif slot=='legs':groups[9]=1+flags[1];indices=[5,6]
            elif slot=='boots':groups[5]=1+flags[0];indices=[6,7]
            elif slot=='gloves':groups[4]=1+flags[0];indices=[1,2]
            elif slot=='belt':indices=[4,5]
            else:indices=[1]
            if flags[2] not in (0,1):raise ValueError('Unsupported robe geoset flag')
            if groups[13]==1:groups[13]=1+flags[2]
            for i in indices:
                path=self.texture(raw,i,g['textures'][i],gender)
                if path:add(path,COMPONENTS[i])
        if robe:groups[13]=2;groups[5]=0;groups[12]=0
        if groups[4]>1:groups[8]=0
        model='character/human/'+character['gender']+'/human'+character['gender']+'.m2'
        info=model_info(assets.read(model),model);skin_path=info['skins'][0]
        skin_bytes=assets.read(skin_path);count,offset=array_at(skin_bytes,28,48)
        available={struct.unpack_from('<H',skin_bytes,offset+i*48)[0] for i in range(count)}
        for group,value in groups.items():
            if value>1 and group*100+value not in available:
                raise ValueError(f'Equipment requests absent human geoset {group*100+value}')
        selected={0}
        if bald:selected.add(1)
        elif hair_geoset:
            if hair_geoset not in available:raise ValueError('Hairstyle geoset is absent')
            selected.add(hair_geoset)
        selected|={group*100+value for group,value in groups.items() if value and group*100+value in available}
        selected&=available
        replacements={1:ATLAS}
        if not bald and hair[0]:replacements[6]=hair[0]
        assets.atlas=np.asarray(atlas).copy()
        metadata=dict(assembly='human-clothing/1',schema=SCHEMA,character=character,equipment=gear,
                      layers=layers,atlas_sha256=hashlib.sha256(assets.atlas.tobytes()).hexdigest(),atlas_size=list(atlas.size))
        return assets,model,replacements,selected,metadata

    def render(self,raw,character,equipment,size,yaw,view):
        assets,model,replacements,geosets,metadata=self.assemble(raw,character,equipment)
        # Only selected parts request replacements; an unused hair type need not be bound.
        from .models import inspect_model
        info=inspect_model(assets,model,geosets)
        overrides={k:v for k,v in replacements.items() if k in info['used_replaceable_texture_types']}
        image,render=preview(assets,model,size,overrides,yaw,view,geosets=geosets)
        sources=[dict(path=p,sha256=hashlib.sha256(raw.read(p)).hexdigest()) for p in sorted(assets.used)]
        metadata['model']=model
        render['limitations']+=['human clothing only; no equipment attachments','underwear layer retained']
        return image,render,metadata,sources


def main():
    parser=argparse.ArgumentParser(description='Search clothing Item IDs or render an explicit human outfit')
    parser.add_argument('command',choices=['search','render']);parser.add_argument('--dbc-assets',required=True)
    parser.add_argument('--model-assets');parser.add_argument('--query',default='cloth');parser.add_argument('--slot',choices=list(SLOTS))
    parser.add_argument('--limit',type=int,default=30);parser.add_argument('--request');parser.add_argument('--out',default='output/human-outfit')
    args=parser.parse_args()
    try:
        if args.command=='search':result=CharacterDB(args.dbc_assets).search(args.query,args.slot,args.limit)
        else:
            if not args.model_assets or not args.request:raise ValueError('Rendering needs --request and --model-assets')
            path=Path(args.request)
            if path.stat().st_size>1024*1024:raise ValueError('Appearance request exceeds one MiB')
            options=json.loads(path.read_text(encoding='utf-8-sig'))
            from .tokens import TokenAssets
            tokens=TokenAssets(args.dbc_assets,args.model_assets);out=Path(args.out)
            if out.exists() and any(out.iterdir()):raise ValueError('Output must be empty')
            pair=tokens.pair(options);tokens.write(out)
            result=dict(format='wowmap.tokens/1',image=pair['token'],portrait=pair['portrait'],media=list(tokens.media.values()))
            (out/'token-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError) as error:parser.exit(1,f'ERROR: {error}\n')


if __name__=='__main__':main()
