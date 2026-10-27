"""WotLK character equipment assembly: original texture layers and selected M2 geosets.

Schemas are pinned to 3.3.5.12340 (WoWDBDefs). Atlas regions and equipment
ordering follow the legacy client layout documented in WoW Model Viewer.
Attachments use original M2 attachment lookup positions in the unanimated bind pose.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import numpy as np
from PIL import Image

from .dbc import DBC
from .models import RawAssets, array_at, model_info, preview, mesh_data
from .pack import normalize

SCHEMA='3.3.5.12340'
ATLAS='generated/character-body-atlas.png'
# Coordinates in the original 256-unit WotLK layout, composed at 512px.
REGIONS={
    'arm_upper':(0,0,128,64), 'arm_lower':(0,64,128,64), 'hand':(0,128,128,32),
    'face_upper':(0,160,128,32), 'face_lower':(0,192,128,64),
    'torso_upper':(128,0,128,64), 'torso_lower':(128,64,128,32),
    'leg_upper':(128,96,128,64), 'leg_lower':(128,160,128,64), 'foot':(128,224,128,32),
}
COMPONENTS=['arm_upper','arm_lower','hand','torso_upper','torso_lower','leg_upper','leg_lower','foot']
FOLDERS=['ArmUpperTexture','ArmLowerTexture','HandTexture','TorsoUpperTexture',
         'TorsoLowerTexture','LegUpperTexture','LegLowerTexture','FootTexture']
RACES={1:'human',2:'orc',3:'dwarf',4:'nightelf',5:'scourge',6:'tauren',7:'gnome',8:'troll',9:'goblin',10:'bloodelf',11:'draenei',12:'felorc',13:'naga_',14:'broken',15:'skeleton',16:'vrykul',17:'tuskarr',18:'foresttroll',19:'taunka',20:'northrendskeleton',21:'icetroll'}
ATTACHMENT_SLOTS={'head':{1},'shoulders':{3},'main_hand':{13,17,21,15,25,26},'off_hand':{13,14,22,23}}
SLOTS={'shirt':{4},'chest':{5,20},'legs':{7},'boots':{8},'gloves':{10},'belt':{6},'bracers':{9}}
SLOTS.update(ATTACHMENT_SLOTS)
TABLES={'charsections':10,'charhairgeosets':6,'characterfacialhairstyles':8,'itemdisplayinfo':25,'item':8,'chrraces':69,'helmetgeosetvisdata':8}


def integer(value,label):
    if type(value) is not int or not 0<=value<=0xffffffff:raise ValueError(label+' must be a nonnegative integer')
    return value


def character_options(character,equipment):
    if not isinstance(character,dict) or set(character)-{'race','gender','skin','face','hair_style','hair_color','facial_hair'}:
        raise ValueError('character contains unsupported appearance fields')
    if character.get('race','human') not in RACES.values():raise ValueError('Unknown WotLK customization race')
    if character.get('gender','male') not in ('male','female'):raise ValueError('gender must be male or female')
    result=dict(race=character.get('race','human'),gender=character.get('gender','male'))
    for field,default in [('skin',0),('face',0),('hair_style',1 if result['race'] in {'human','orc','dwarf','nightelf','scourge','tauren','gnome','troll','bloodelf','draenei'} else 0),('hair_color',0),('facial_hair',0)]:
        result[field]=integer(character.get(field,default),field)
    if not isinstance(equipment,dict) or set(equipment)-set(SLOTS):
        raise ValueError('Unknown equipment slot')
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
        self.sections={};self.hair={};self.facial={};self.items={};self.displays={};self.races={};self.helmets={}
        for name,target in [('chrraces',self.races),('helmetgeosetvisdata',self.helmets)]:
            t=self.tables[name]
            for row in range(t.records):target[t.cell(row,0)]=row
        for name,target in [('item',self.items),('itemdisplayinfo',self.displays)]:
            table=self.tables[name]
            for row in range(table.records):
                key=table.cell(row,0)
                if key in target:raise ValueError('Duplicate '+name+' ID')
                target[key]=row
        for name,target,cols in [('charsections',self.sections,(1,2,3,8,9)),
                                ('charhairgeosets',self.hair,(1,2,3)),
                                ('characterfacialhairstyles',self.facial,(0,1,2))]:
            table=self.tables[name]
            for row in range(table.records):
                if name=='charsections' and not table.cell(row,7)&9:continue
                key=tuple(table.cell(row,c) for c in cols)
                if key in target:
                    if name=='charhairgeosets':
                        if all(table.cell(row,c)==table.cell(target[key],c) for c in (1,2,3,4,5)):continue
                        if key[0]==9:continue  # Legacy goblin rows describe fixed scalp pieces, not selectable hairstyles.
                    if name=='charsections' and bool(table.cell(row,7)&1)!=bool(table.cell(target[key],7)&1):
                        if table.cell(row,7)&1:target[key]=row
                        continue
                    raise ValueError('Ambiguous '+name+' selection')
                target[key]=row

    def section(self,gender,kind,variation,color,required=True,race=1):
        row=self.sections.get((race,gender,kind,variation,color))
        if row is None:
            if required:raise ValueError(f'Unknown race {race} appearance section: {kind}/{variation}/{color}')
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
        if slot not in ATTACHMENT_SLOTS and any(d.cell(r,c,'string') for c in (1,2)):
            raise ValueError(f'Item {item_id} has separate models outside supported attachment slots')
        return dict(item_id=item_id,display_id=display_id,inventory_type=inventory,
                    geosets=[d.cell(r,c) for c in (7,8,9)],icon=d.cell(r,5,'string'),
                    textures=[d.cell(r,c,'string') for c in range(15,23)],models=[d.cell(r,c,'string') for c in (1,2)],model_textures=[d.cell(r,c,'string') for c in (3,4)],helmet_visibility=[d.cell(r,c) for c in (13,14)],visual_id=d.cell(r,23),particle_color_id=d.cell(r,24))

    def options(self,raw):
        from .models import inspect_model
        result=[]
        for race,name in RACES.items():
            for gender,sex in [('male',0),('female',1)]:
                row=dict(race=name,race_id=race,gender=gender)
                row['skins']=sorted({k[4] for k,r in self.sections.items() if k[:3]==(race,sex,0) and raw.has(self.tables['charsections'].cell(r,4,'string'))})
                row['hair_styles']=sorted({k[2] for k in self.hair if k[:2]==(race,sex)})
                row['faces_by_skin']={str(skin):sorted({k[3] for k in self.sections if k[:3]==(race,sex,1) and k[4]==skin}) for skin in row['skins']}
                row['hair_colors_by_style']={str(style):sorted({k[4] for k in self.sections if k[:4]==(race,sex,3,style)}) for style in row['hair_styles']}
                row['facial_features']=sorted({k[2] for k in self.facial if k[:2]==(race,sex)})
                try:
                    assets,model,replacements,geosets,meta=self.assemble(raw,dict(race=name,gender=gender),{})
                    info=inspect_model(assets,model,geosets)
                    if info['missing']:raise ValueError('Missing dependencies: '+', '.join(info['missing']))
                    if set(info['used_replaceable_texture_types'])-set(replacements):raise ValueError('Unbound body material')
                    mesh_data(assets,model,{k:v for k,v in replacements.items() if k in info['used_replaceable_texture_types']},geosets)
                    row.update(available=True,model=model,clothing_atlas=1 in info['used_replaceable_texture_types'],omitted_optional_overlays=meta['omitted_optional_overlays'])
                    data=assets.read(model);count,start=array_at(data,248,2)
                    row['attachment_points']=[i for i in range(count) if struct.unpack_from('<h',data,start+i*2)[0]>=0]
                except ValueError as error:row.update(available=False,reason=str(error))
                result.append(row)
        return dict(schema=SCHEMA,bodies=result,note='Availability describes the default body, not every style or item. Missing race/sex helmet models and attachment points are explicit errors.')

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
            text=' '.join(d.cell(r,c,'string') for c in [1,2,3,4,5,*range(15,23)]).lower()
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
        race=next(k for k,v in RACES.items() if v==character['race'])
        def section(kind,variation,color,required=True):return self.section(gender,kind,variation,color,required,race)
        base=section(0,0,skin)
        atlas=Image.fromarray(assets.image(base[0])).convert('RGBA')
        if atlas.size not in ((256,256),(512,512)):raise ValueError('Unsupported body atlas dimensions')
        atlas=atlas.resize((512,512),Image.Resampling.LANCZOS)
        layers=[dict(region='base',path=base[0])];omitted=[]
        gear={slot:self.equipment(slot,item) for slot,item in equipment.items()}
        hide_hair=False;hidden_groups=set()
        if 'head' in gear:
            visibility=gear['head']['helmet_visibility'][gender]
            if visibility:
                if visibility not in self.helmets:raise ValueError('Unknown HelmetGeosetVisData ID')
                row=self.helmets[visibility];t=self.tables['helmetgeosetvisdata'];mask=1<<race
                hide_hair=bool(t.cell(row,1)&mask)
                for col,group in [(2,1),(3,2),(4,3),(5,7)]:
                    if t.cell(row,col)&mask:hidden_groups.add(group)

        def add(path,region):
            if not path:return
            if not assets.has(path):
                omitted.append(dict(region=region,path=path,reason='optional DBC overlay absent from client'));return
            composite_layer(atlas,Image.fromarray(assets.image(path)),region);layers.append(dict(region=region,path=path))
        underwear=section(4,0,skin,required=False)
        for texture,region in zip(underwear,['leg_upper','torso_upper']):add(texture,region)
        has_faces=any(k[:3]==(race,gender,1) for k in self.sections)
        if not has_faces and character['face']:raise ValueError('This body has no selectable face overlays')
        face=section(1,character['face'],skin,required=has_faces)
        for texture,region in zip(face,['face_lower','face_upper']):add(texture,region)
        facial_row=self.facial.get((race,gender,character['facial_hair']))
        if facial_row is None and character['facial_hair']!=0:raise ValueError('Unknown facial hair / feature style')
        facial=section(2,character['facial_hair'],hair_color,required=False)
        if 1 not in hidden_groups:
            for texture,region in zip(facial,['face_lower','face_upper']):add(texture,region)
        hair_row=self.hair.get((race,gender,hair_style))
        if hair_row is None and any(k[:2]==(race,gender) for k in self.hair):raise ValueError('Unknown hairstyle')
        if hair_row is None and (hair_style not in (0,1) or hair_color):raise ValueError('This model has no selectable hairstyles')
        hair_table=self.tables['charhairgeosets'];hair_geoset=hair_table.cell(hair_row,4) if hair_row is not None else 0
        bald=bool(hair_table.cell(hair_row,5)) if hair_row is not None else True
        has_hair_sections=any(k[:3]==(race,gender,3) for k in self.sections)
        if not has_hair_sections and hair_color:raise ValueError('This body has no selectable hair colors')
        hair=section(3,hair_style,hair_color,required=has_hair_sections) or ['','','']
        if not bald and not hide_hair:
            for texture,region in zip(hair[1:],['face_lower','face_upper']):add(texture,region)
        groups={n:1 for n in range(1,19)}
        groups.update({1:0,2:0,3:0,7:2,15:0,17:0})
        if facial_row is not None:
            t=self.tables['characterfacialhairstyles']
            groups.update({1:t.cell(facial_row,3),3:t.cell(facial_row,4),2:t.cell(facial_row,5)})
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
            elif slot=='boots':groups[5]=1+flags[0];indices=[6] if race in {6,8,11,13,14,18,19,21} else [6,7]
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
        model='character/'+character['race']+'/'+character['gender']+'/'+character['race']+character['gender']+'.m2'
        info=model_info(assets.read(model),model);skin_path=info['skins'][0]
        skin_bytes=assets.read(skin_path);count,offset=array_at(skin_bytes,28,48)
        available={struct.unpack_from('<H',skin_bytes,offset+i*48)[0] for i in range(count)}
        for group,value in groups.items():
            if group not in {1,2,3,7} and value>1 and group*100+value not in available:
                if group==5 and race in {6,19}:
                    omitted.append(dict(geoset=group*100+value,reason='hoof body has no requested boot mesh; lower-leg texture retained'))
                else:raise ValueError(f'Equipment requests absent body geoset {group*100+value}')
        for group in hidden_groups:groups[group]=0
        selected={0}
        if bald or hide_hair:selected.add(1)
        elif hair_geoset and not hide_hair:
            if hair_geoset not in available:
                if race<=11 or hair_style!=0:raise ValueError('Hairstyle geoset is absent')
                omitted.append(dict(geoset=hair_geoset,reason='default NPC hairstyle geoset absent from client model'))
            else:selected.add(hair_geoset)
        selected|={group*100+value for group,value in groups.items() if value and group*100+value in available}
        selected&=available
        replacements={1:ATLAS}
        if hair[0]:replacements[6]=hair[0]
        if len(base)>1 and base[1]:replacements[8]=base[1]
        if race==13 and set(gear)&{'legs','boots'}:raise ValueError('Naga bodies have no wearable legs or boots')
        assets.atlas=np.asarray(atlas).copy()
        metadata=dict(assembly='character-equipment/2',schema=SCHEMA,character=character,equipment=gear,
                      layers=layers,atlas_sha256=hashlib.sha256(assets.atlas.tobytes()).hexdigest(),atlas_size=list(atlas.size),omitted_optional_overlays=omitted)
        return assets,model,replacements,selected,metadata

    def attachments(self,assets,model,character,gear):
        if not set(gear)&set(ATTACHMENT_SLOTS):return []
        data=assets.read(model)
        count,start=array_at(data,240,40);lookup_count,lookup_start=array_at(data,248,2)
        bones,_=array_at(data,44,88)
        race=next(k for k,v in RACES.items() if v==character['race'])
        if race not in self.races:raise ValueError('Missing ChrRaces entry')
        prefix=self.tables['chrraces'].cell(self.races[race],6,'string').lower()
        sex='m' if character['gender']=='male' else 'f'
        parts=[]
        def attach(slot,index,point,folder):
            g=gear[slot];name=g['models'][index]
            if not name:return
            name=normalize(name)
            if '/' in name:raise ValueError('Unexpected path in attachment ModelName')
            stem=str(PurePosixPath(name).with_suffix(''))
            if slot=='head':stem+='_'+prefix+sex
            path='item/objectcomponents/'+folder+'/'+stem+'.m2'
            if not assets.has(path):raise ValueError('Missing race/sex equipment model: '+path)
            if point>=lookup_count:raise ValueError('Model has no requested attachment lookup')
            entry=struct.unpack_from('<h',data,lookup_start+point*2)[0]
            if not 0<=entry<count:raise ValueError(f'Missing attachment point {point} on {model}')
            actual,bone,*position=struct.unpack_from('<II3f',data,start+entry*40)
            if actual!=point or bone>=bones or not np.isfinite(position).all():raise ValueError('Invalid attachment record')
            texture=g['model_textures'][index]
            from .models import inspect_model
            info=inspect_model(assets,path)
            overrides={}
            if info['used_replaceable_texture_types']:
                if set(info['used_replaceable_texture_types'])!={2} or not texture:raise ValueError('Unsupported attachment replacement textures')
                if '/' in texture or '\\' in texture:raise ValueError('Unexpected attachment texture path')
                texture_path='item/objectcomponents/'+folder+'/'+texture.lower()+'.blp'
                if not assets.has(texture_path):raise ValueError('Missing attachment texture: '+texture_path)
                overrides[2]=texture_path
            parts.append(dict(slot=slot,attachment_id=point,bone=bone,model=path,textures=overrides,position=position))
        for slot in ATTACHMENT_SLOTS:
            if slot not in gear:continue
            if slot=='head':attach(slot,0,11,'head')
            elif slot=='shoulders':
                attach(slot,0,6,'shoulder');attach(slot,1,5,'shoulder')
            elif slot=='off_hand' and gear[slot]['inventory_type']==14:attach(slot,0,0,'shield')
            else:attach(slot,0,1 if slot=='main_hand' else 2,'weapon')
            if not any(p['slot']==slot for p in parts):raise ValueError('Item has no attachment model: '+str(gear[slot]['item_id']))
        if gear.get('main_hand',{}).get('inventory_type')==17 and 'off_hand' in gear:
            raise ValueError('Two-handed equipment cannot be combined with an off-hand item')
        return parts

    def render(self,raw,character,equipment,size,yaw,view):
        assets,model,replacements,geosets,metadata=self.assemble(raw,character,equipment)
        # Only selected parts request replacements; an unused hair type need not be bound.
        from .models import inspect_model
        info=inspect_model(assets,model,geosets)
        if 1 not in info['used_replaceable_texture_types'] and set(equipment)-set(ATTACHMENT_SLOTS):
            raise ValueError('This body has no clothing atlas material; texture clothing would be invisible')
        overrides={k:v for k,v in replacements.items() if k in info['used_replaceable_texture_types']}
        attachments=self.attachments(assets,model,metadata['character'],metadata['equipment'])
        image,render=preview(assets,model,size,overrides,yaw,view,geosets=geosets,attachments=attachments)
        sources=[dict(path=p,sha256=hashlib.sha256(raw.read(p)).hexdigest()) for p in sorted(assets.used)]
        metadata['model']=model
        render['limitations']+=['bind-pose attachments; hands remain in base pose','no item visual/enchantment particle effects','underwear layer retained where available']
        return image,render,metadata,sources


def main():
    parser=argparse.ArgumentParser(description='Inspect WotLK character options, search Item IDs, or render equipped characters')
    parser.add_argument('command',choices=['search','options','render']);parser.add_argument('--dbc-assets',required=True)
    parser.add_argument('--model-assets');parser.add_argument('--query',default='cloth');parser.add_argument('--slot',choices=list(SLOTS))
    parser.add_argument('--limit',type=int,default=30);parser.add_argument('--request');parser.add_argument('--out',default='output/character-outfit')
    args=parser.parse_args()
    try:
        if args.command=='search':result=CharacterDB(args.dbc_assets).search(args.query,args.slot,args.limit)
        elif args.command=='options':
            if not args.model_assets:raise ValueError('Options needs --model-assets')
            with RawAssets(args.model_assets) as raw:result=CharacterDB(args.dbc_assets).options(raw)
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
