"""Prepare reproducible technical Builder NPCs after checking each real body/item.

This authoring helper records omissions explicitly. The production renderer never
substitutes a missing piece or silently removes a requested item.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from wowmap.characters import CharacterDB,ATTACHMENT_SLOTS
from wowmap.models import RawAssets,inspect_model,mesh_data

NAMES={'human':'Человек','orc':'Орк','dwarf':'Дворф','nightelf':'Ночной эльф','scourge':'Нежить','tauren':'Таурен','gnome':'Гном','troll':'Тролль','goblin':'Гоблин','bloodelf':'Эльф крови','draenei':'Дреней','felorc':'Орк Скверны','naga_':'Нага','broken':'Сломленный','skeleton':'Скелет','vrykul':'Врайкул','tuskarr':'Клыкарр','foresttroll':'Лесной тролль','taunka':'Таунка','northrendskeleton':'Северный скелет','icetroll':'Ледяной тролль'}
PRESET=dict(chest=285,legs=286,boots=287,gloves=718,head=3836,shoulders=4725,main_hand=25,off_hand=143)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dbc-assets',required=True);parser.add_argument('--model-assets',required=True)
    parser.add_argument('--audit',default='output/character-demo-capabilities.json')
    args=parser.parse_args();db=CharacterDB(args.dbc_assets)
    template=json.loads((ROOT/'requests/builder/sources/human-outfits/worker.json').read_text(encoding='utf-8'))
    documents=[];audit=[];directory=ROOT/'requests/builder/sources/all-races';directory.mkdir(exist_ok=True)
    with RawAssets(args.model_assets) as raw:
        capabilities=db.options(raw)
        for body in capabilities['bodies']:
            if not body['available']:continue
            character=dict(race=body['race'],gender=body['gender']);gear={};omitted=[]
            for slot,item in PRESET.items():
                try:
                    assets,model,replacements,geosets,meta=db.assemble(raw,character,{**gear,slot:item})
                    info=inspect_model(assets,model,geosets)
                    if not body['clothing_atlas'] and slot not in ATTACHMENT_SLOTS:raise ValueError('No clothing atlas material')
                    mesh_data(assets,model,{k:v for k,v in replacements.items() if k in info['used_replaceable_texture_types']},geosets)
                    for part in db.attachments(assets,model,meta['character'],meta['equipment']):mesh_data(assets,part['model'],part['textures'])
                    gear[slot]=item
                except ValueError as error:
                    if body['race_id'] in {1,2,3,4,5,6,7,8,10,11}:raise
                    omitted.append(dict(slot=slot,item_id=item,reason=str(error)))
            key=body['race'].rstrip('_')+'-'+body['gender'];name=NAMES[body['race']]+' — '+('мужская' if body['gender']=='male' else 'женская')+' модель'
            actor=copy.deepcopy(template);actor['name']=name;actor['prototypeToken'].update(name=name,disposition=0)
            actor['system']['details']['race']=NAMES[body['race']]
            actor['system']['details']['type']['subtype']=NAMES[body['race']]
            actor['system']['details']['biography']['value']='<p>Техническая проверка внешности и креплений. Все характеристики 10, КД 10, 1 хит; без атак и предметов в листе. Видимое снаряжение задаёт только изображение.</p>'
            source=directory/(key+'.json');source.write_text(json.dumps(actor,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            documents.append(dict(id=key,mode='npc',source=source.relative_to(ROOT).as_posix(),appearance=dict(character=character,equipment=gear,size=256,portrait_size=384)))
            audit.append(dict(id=key,equipment=gear,omitted_from_demo_preset=omitted))
    request=dict(format='foundry-builder.batch/1',documents=documents,placements=[])
    (ROOT/'requests/builder/all-races.json').write_text(json.dumps(request,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    output=Path(args.audit);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(capabilities=capabilities,demo=audit),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(bodies=len(documents),declared_demo_omissions=sum(len(x['omitted_from_demo_preset']) for x in audit))))


if __name__=='__main__':main()
