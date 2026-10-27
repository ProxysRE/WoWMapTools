import copy
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile
import numpy as np
from PIL import Image
from test_models import fixture
from test_tokens import appearance_fixture,table
from wowmap.characters import CharacterDB,REGIONS,ATLAS,character_options
from wowmap.models import RawAssets,preview
from wowmap.tokens import TokenAssets

ROOT=Path(__file__).resolve().parents[1]


def character_fixture(root):
    dbc,models=appearance_fixture(root);strings=bytearray(b'\0')
    def string(value):
        offset=len(strings);strings.extend(value.encode()+b'\0');return offset
    def png(color):
        stream=io.BytesIO();Image.new('RGBA',(512,512),color).save(stream,format='PNG');return stream.getvalue()
    sections=[]
    for sex in [0,1]:
        for kind,variation,textures in [(0,0,['base.png']),(1,0,['face.png','face.png']),(4,0,['base.png']),(3,1,[])]:
            row=[len(sections)+1,1,sex,kind,*[string(t) for t in textures],*[0]*(3-len(textures)),1,variation,0]
            sections.append(struct.pack('<10I',*row))
    section_bytes=table(10,sections,bytes(strings));strings=bytearray(b'\0')
    displays=[]
    for did,flags in [(10,(0,0,0)),(11,(1,0,1)),(12,(1,0,0))]:
        row=[0]*25;row[0]=did;row[7:10]=flags
        for col,name in [(15,'sleeve_au'),(16,'sleeve_al'),(17,'glove_ha'),(18,'chest_tu'),(19,'chest_tl'),(20,'pant_lu'),(21,'pant_ll'),(22,'boot_fo')]:row[col]=string(name)
        displays.append(struct.pack('<25I',*row))
    display_bytes=table(25,displays,bytes(strings))
    with ZipFile(dbc/'tables.zip','a') as z:
        z.writestr('dbfilesclient/charsections.dbc',section_bytes)
        z.writestr('dbfilesclient/charhairgeosets.dbc',table(6,[struct.pack('<6I',i+1,1,i,1,0,1) for i in [0,1]],b'\0'))
        z.writestr('dbfilesclient/characterfacialhairstyles.dbc',table(8,[struct.pack('<8I',1,sex,0,0,0,0,0,0) for sex in [0,1]],b'\0'))
        z.writestr('dbfilesclient/itemdisplayinfo.dbc',display_bytes)
        z.writestr('dbfilesclient/item.dbc',table(8,[struct.pack('<8I',100,4,0,0,0,10,4,0),struct.pack('<8I',101,4,0,0,0,11,20,0),struct.pack('<8I',102,4,0,0,0,12,10,0)],b'\0'))
    model,skin,_=fixture();model=bytearray(model);_,offset=struct.unpack_from('<II',model,80);struct.pack_into('<IIII',model,offset,1,0,0,0)
    _,offset=struct.unpack_from('<II',model,60);struct.pack_into('<f',model,offset+48+8,1)
    sections=[];batches=[]
    for i,geoset in enumerate([0,802,1302,402,702]):
        sections.append(struct.pack('<10H',geoset,0,0,3,0,3,1,0,1,0)+b'\0'*28)
        batches.append(struct.pack('<BB11H',0,0,0,i,0,65535,0,0,1,0,0,0,0))
    skin=bytearray(skin)
    for header,data,count in [(28,b''.join(sections),len(sections)),(36,b''.join(batches),len(batches))]:
        struct.pack_into('<II',skin,header,count,len(skin));skin.extend(data)
    from wowmap.characters import FOLDERS
    with ZipFile(models/'human.zip','w') as z:
        for sex in ['male','female']:
            prefix='character/human/'+sex+'/human'+sex
            z.writestr(prefix+'.m2',model);z.writestr(prefix+'00.skin',skin)
        z.writestr('base.png',png((100,100,100,255)));z.writestr('face.png',png((100,100,100,0)))
        for folder,name in zip(FOLDERS,['sleeve_au','sleeve_al','glove_ha','chest_tu','chest_tl','pant_lu','pant_ll','boot_fo']):
            # Same texture requested by both sexes; explicit unisex fallback.
            z.writestr('item/texturecomponents/'+folder.lower()+'/'+name+'_u.blp',png((200,0,0,128)))
    return dbc,models


class CharacterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.dbc,self.models=character_fixture(self.root)

    def test_body_composition_uses_atlas_regions_and_does_not_mutate_source_images(self):
        db=CharacterDB(self.dbc)
        with RawAssets(self.models) as raw:
            original=raw.image('base.png').copy()
            assets,model,replacements,geosets,meta=db.assemble(raw,{},dict(shirt=100))
            x,y,w,h=REGIONS['torso_upper'];pixel=assets.atlas[(y+h//2)*2,(x+w//2)*2]
            self.assertEqual(pixel.tolist(),[150,50,50,255])
            self.assertTrue(np.array_equal(original,raw.image('base.png')))
            self.assertEqual(replacements,{1:ATLAS});self.assertNotIn(1302,geosets)
            self.assertTrue(meta['layers']);self.assertIn('base.png',assets.used)

    def test_robe_and_gloves_select_geometry_and_hide_sleeve_cuffs(self):
        db=CharacterDB(self.dbc)
        with RawAssets(self.models) as raw:
            _,_,_,geosets,_=db.assemble(raw,{},dict(chest=101))
            self.assertIn(1302,geosets);self.assertIn(802,geosets)
            _,_,_,geosets,_=db.assemble(raw,{},dict(chest=101,gloves=102))
            self.assertIn(1302,geosets);self.assertIn(402,geosets);self.assertNotIn(802,geosets)

    def test_invalid_slots_ids_races_styles_and_missing_textures_fail_explicitly(self):
        db=CharacterDB(self.dbc)
        for character,equipment in [({'race':'orc'},{}),({},dict(head=100)),({},dict(shirt=True)),({},dict(shirt=999)),({},dict(chest=100)),({'face':999},{'shirt':100})]:
            with RawAssets(self.models) as raw,self.assertRaises(ValueError):db.assemble(raw,character,equipment)
        with RawAssets(self.models) as raw:
            path=next(p for p in raw.files if 'chest_tu' in p);raw.files.pop(path)
            with self.assertRaisesRegex(ValueError,'Missing clothing'):db.assemble(raw,{},dict(shirt=100))

    def test_token_pair_and_builder_preserve_gameplay_and_export_both_views(self):
        tokens=TokenAssets(self.dbc,self.models)
        options=dict(character=dict(gender='female'),equipment=dict(shirt=100),size=128,portrait_size=128)
        pair=tokens.pair(options)
        self.assertNotEqual(pair['token'],pair['portrait']);self.assertEqual(pair,tokens.pair(copy.deepcopy(options)))
        for media in tokens.media.values():
            variant=media['appearances'][0];self.assertEqual(variant['assembly'],'human-clothing/1')
            self.assertIn('charsections',variant['dbc_sha256'])
            self.assertNotIn(ATLAS,[s['path'] for s in variant['sources']])
        spec=importlib.util.spec_from_file_location('human_batch',ROOT/'tools/build_foundry_batch.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        reader=adapter.read_json
        request=dict(format='foundry-builder.batch/1',documents=[dict(id='human',mode='npc',source='requests/builder/sources/oren.json',appearance=options)],placements=[])
        adapter.read_json=lambda path:copy.deepcopy(request) if path.name=='active.json' else reader(path)
        result=adapter.build_batch('requests/builder/active.json',self.root/'built',None,self.dbc,self.models)
        actor=json.loads((self.root/'built/human.json').read_text(encoding='utf-8'))
        self.assertEqual(actor['system']['details']['race'],'Человек');self.assertEqual(actor['system']['attributes']['hp']['max'],11)
        self.assertNotEqual(actor['img'],actor['prototypeToken']['texture']['src']);self.assertEqual(len(result['media']),2)
        request['documents'][0]['appearance']['equipment']['shirt']=999
        with self.assertRaises(ValueError):adapter.build_batch('requests/builder/active.json',self.root/'bad',None,self.dbc,self.models)
        self.assertFalse((self.root/'bad').exists())

    def test_selected_geosets_must_have_visible_triangles(self):
        db=CharacterDB(self.dbc)
        with RawAssets(self.models) as raw:
            assets,model,replacements,_,_=db.assemble(raw,{},dict(shirt=100))
            with self.assertRaisesRegex(ValueError,'no triangles'):preview(assets,model,128,replacements,geosets=set())
