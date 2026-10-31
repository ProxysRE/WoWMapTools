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
from test_tokens import appearance_fixture,table,standing_model
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
    for data in list(sections):
        values=list(struct.unpack('<10I',data));values[0]+=100;values[1]=2;sections.append(struct.pack('<10I',*values))
    section_bytes=table(10,sections,bytes(strings));strings=bytearray(b'\0')
    displays=[]
    for did,flags in [(10,(0,0,0)),(11,(1,0,1)),(12,(1,0,0))]:
        row=[0]*25;row[0]=did;row[7:10]=flags
        for col,name in [(15,'sleeve_au'),(16,'sleeve_al'),(17,'glove_ha'),(18,'chest_tu'),(19,'chest_tl'),(20,'pant_lu'),(21,'pant_ll'),(22,'boot_fo')]:row[col]=string(name)
        displays.append(struct.pack('<25I',*row))
    for did in range(13,17):
        row=[0]*25;row[0]=did;row[1]=string('test.mdx');row[3]=string('test_skin')
        if did==14:row[2]=string('test.mdx');row[4]=string('test_skin')
        if did==13:row[13:15]=[1,1]
        displays.append(struct.pack('<25I',*row))
    row=[0]*25;row[0]=17;row[3]=string('cape_test');row[7]=2;displays.append(struct.pack('<25I',*row))
    display_bytes=table(25,displays,bytes(strings))
    with ZipFile(dbc/'tables.zip','a') as z:
        race_strings=b'\0Hu\0Or\0'
        races=[]
        for race,prefix in [(1,1),(2,4)]:
            row=[0]*69;row[0]=race;row[6]=prefix;races.append(struct.pack('<69I',*row))
        z.writestr('dbfilesclient/chrraces.dbc',table(69,races,race_strings))
        z.writestr('dbfilesclient/helmetgeosetvisdata.dbc',table(8,[struct.pack('<8I',1,2,2,2,2,2,0,0)],b'\0'))
        z.writestr('dbfilesclient/charsections.dbc',section_bytes)
        z.writestr('dbfilesclient/charhairgeosets.dbc',table(6,[struct.pack('<6I',i+1,1,i,1,0,1) for i in [0,1]]+[struct.pack('<6I',10+i,2,i,1,0,1) for i in [0,1]],b'\0'))
        z.writestr('dbfilesclient/characterfacialhairstyles.dbc',table(8,[struct.pack('<8I',1,sex,0,0,0,0,0,0) for sex in [0,1]],b'\0'))
        z.writestr('dbfilesclient/itemdisplayinfo.dbc',display_bytes)
        z.writestr('dbfilesclient/item.dbc',table(8,[struct.pack('<8I',100,4,0,0,0,10,4,0),struct.pack('<8I',101,4,0,0,0,11,20,0),struct.pack('<8I',102,4,0,0,0,12,10,0)]+[struct.pack('<8I',103+i,4,0,0,0,13+i,inv,0) for i,inv in enumerate([1,3,21,14])]+[struct.pack('<8I',107,2,0,0,0,15,17,0),struct.pack('<8I',108,4,0,0,0,17,16,0)],b'\0'))
    model,skin,_=fixture();model=bytearray(model);_,offset=struct.unpack_from('<II',model,80);struct.pack_into('<IIII',model,offset,1,0,0,0)
    _,offset=struct.unpack_from('<II',model,60);struct.pack_into('<f',model,offset+48+8,1)
    struct.pack_into('<II',model,80,2,len(model));model.extend(struct.pack('<8I',1,0,0,0,2,0,0,0))
    struct.pack_into('<II',model,128,2,len(model));model.extend(struct.pack('<2H',0,1))
    sections=[];batches=[]
    for i,geoset in enumerate([0,802,1302,402,702,1503]):
        sections.append(struct.pack('<10H',geoset,0,0,3,0,3,1,0,1,0)+b'\0'*28)
        batches.append(struct.pack('<BB11H',0,0,0,i,0,65535,0,0,1,1 if geoset==1503 else 0,0,0,0))
    skin=bytearray(skin)
    for header,data,count in [(28,b''.join(sections),len(sections)),(36,b''.join(batches),len(batches))]:
        struct.pack_into('<II',skin,header,count,len(skin));skin.extend(data)
    # Real-size header with attachment and bone arrays; move the triangle payload.
    original=model;model=bytearray(original[:160]+b'\0'*144+original[160:])
    for header in [60,80,112,128]:
        count,offset=struct.unpack_from('<II',model,header);struct.pack_into('<II',model,header,count,offset+144)
    model=standing_model(model)
    points=[0,1,2,5,6,11]
    struct.pack_into('<II',model,240,len(points),len(model))
    for point in points:model.extend(struct.pack('<II3f',point,0,point*.1,0,1)+b'\0'*20)
    struct.pack_into('<II',model,248,12,len(model))
    model.extend(struct.pack('<12h',*[points.index(i) if i in points else -1 for i in range(12)]))
    from wowmap.characters import FOLDERS
    with ZipFile(models/'human.zip','w') as z:
        for race in ['human','orc']:
            for sex in ['male','female']:
                prefix='character/'+race+'/'+sex+'/'+race+sex
                z.writestr(prefix+'.m2',model);z.writestr(prefix+'00.skin',skin)
        part,part_skin,texture=fixture();part=bytearray(part)
        _,texture_offset=struct.unpack_from('<II',part,80);struct.pack_into('<IIII',part,texture_offset,2,0,0,0)
        for folder in ['head','shoulder','weapon','shield']:
            z.writestr('item/objectcomponents/'+folder+'/test_skin.blp',texture)
            for stem in (['test_hum','test_huf','test_orm','test_orf'] if folder=='head' else ['test']):
                prefix='item/objectcomponents/'+folder+'/'+stem
                z.writestr(prefix+'.m2',part);z.writestr(prefix+'00.skin',part_skin)
        z.writestr('tileset/test/red.png',texture)
        z.writestr('item/objectcomponents/cape/cape_test.blp',png((0,30,200,255)))
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
        for character,equipment in [({'race':'worgen'},{}),({},dict(head=100)),({},dict(shirt=True)),({},dict(shirt=999)),({},dict(chest=100)),({'face':999},{'shirt':100})]:
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
            variant=media['appearances'][0];self.assertEqual(variant['assembly'],'character-equipment/2')
            self.assertIn('charsections',variant['dbc_sha256'])
            self.assertNotIn(ATLAS,[s['path'] for s in variant['sources']])
        spec=importlib.util.spec_from_file_location('human_batch',ROOT/'tools/build_foundry_batch.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        reader=adapter.read_json
        request=dict(format='foundry-builder.batch/1',require_item_icons=False,documents=[dict(id='human',mode='npc',source='requests/builder/sources/oren.json',appearance=options)],placements=[])
        adapter.read_json=lambda path:copy.deepcopy(request) if path.name=='active.json' else reader(path)
        result=adapter.build_batch('requests/builder/active.json',self.root/'built',None,self.dbc,self.models)
        actor=json.loads((self.root/'built/human.json').read_text(encoding='utf-8'))
        self.assertEqual(actor['system']['details']['race'],'Человек');self.assertEqual(actor['system']['attributes']['hp']['max'],11)
        self.assertNotEqual(actor['img'],actor['prototypeToken']['texture']['src']);self.assertEqual(len(result['media']),2)
        request['documents'][0]['appearance']['equipment']['shirt']=999
        with self.assertRaises(ValueError):adapter.build_batch('requests/builder/active.json',self.root/'bad',None,self.dbc,self.models)
        self.assertFalse((self.root/'bad').exists())

    def test_attachment_lookup_race_helmet_variants_and_shared_depth_render(self):
        db=CharacterDB(self.dbc)
        gear=dict(head=103,shoulders=104,main_hand=105,off_hand=106)
        with RawAssets(self.models) as raw:
            assets,model,_,geo,meta=db.assemble(raw,{},gear)
            self.assertNotIn(702,geo)  # Helmet's race mask hides ears.
            parts=db.attachments(assets,model,meta['character'],meta['equipment'])
            self.assertEqual([p['attachment_id'] for p in parts],[11,6,5,1,0])
            self.assertAlmostEqual(parts[0]['position'][0],1.1)
            self.assertTrue(parts[0]['model'].endswith('test_hum.m2'))
            image,render,_,sources=db.render(raw,{},gear,128,0,'front')
            self.assertEqual(len(render['attachments']),5)
            self.assertTrue(any('/shield/' in p['path'] for p in sources))
            self.assertEqual(image.getpixel((0,0))[3],0)
            a,m,_,_,meta=db.assemble(raw,dict(race='orc',gender='female'),dict(head=103))
            part=db.attachments(a,m,meta['character'],meta['equipment'])[0]
            self.assertTrue(part['model'].endswith('test_orf.m2'))

    def test_two_handed_conflict_and_missing_replacement_texture_are_rejected(self):
        db=CharacterDB(self.dbc)
        with RawAssets(self.models) as raw:
            with self.assertRaisesRegex(ValueError,'Two-handed'):
                db.render(raw,{},dict(main_hand=107,off_hand=106),128,0,'front')
            raw.files.pop('item/objectcomponents/weapon/test_skin.blp')
            with self.assertRaisesRegex(ValueError,'Missing attachment texture'):
                db.render(raw,{},dict(main_hand=105),128,0,'front')

    def test_missing_attachment_and_race_helmet_fail_without_substitution(self):
        db=CharacterDB(self.dbc)
        with RawAssets(self.models) as raw:
            raw.files.pop('item/objectcomponents/head/test_huf.m2')
            with self.assertRaisesRegex(ValueError,'Missing race/sex equipment model'):
                db.render(raw,dict(gender='female'),dict(head=103),128,0,'front')
            a,m,_,_,meta=db.assemble(raw,{},dict(main_hand=105))
            data=bytearray(a.read(m));_,offset=struct.unpack_from('<II',data,248)
            struct.pack_into('<h',data,offset+2,-1)
            read=a.read;a.read=lambda name:bytes(data) if name==m else read(name)
            with self.assertRaisesRegex(ValueError,'Missing attachment point'):
                db.attachments(a,m,meta['character'],meta['equipment'])

    def test_cape_geometry_texture_and_missing_parts(self):
        db=CharacterDB(self.dbc)
        with RawAssets(self.models) as raw:
            with self.assertRaisesRegex(ValueError,'head covering'):db.assemble(raw,dict(race='tuskarr'),dict(cape=108))
            a,m,re,geosets,meta=db.assemble(raw,{},dict(cape=108))
            self.assertIn(1503,geosets)
            self.assertEqual(re[2],'item/objectcomponents/cape/cape_test.blp')
            _,_,_,bare,_=db.assemble(raw,{},{});self.assertNotIn(1503,bare)
            _,report,_,sources=db.render(raw,{},dict(cape=108),128,180,'front')
            self.assertIn(re[2],report['used_textures'])
            self.assertIn(re[2],[row['path'] for row in sources])
            raw.files.pop(re[2])
            with self.assertRaisesRegex(ValueError,'Missing cape texture'):db.assemble(raw,{},dict(cape=108))
        # A valid cape with a length absent from this body is never dropped silently.
        with RawAssets(self.models) as raw:
            original=db.equipment
            def absent(slot,item):
                gear=original(slot,item);gear['geosets']=[5,0,0];return gear
            db.equipment=absent
            with self.assertRaisesRegex(ValueError,'no requested cape geoset'):db.assemble(raw,{},dict(cape=108))

    def test_token_views_share_one_assembly_without_camera_or_metadata_mutation(self):
        from unittest.mock import patch
        tokens=TokenAssets(self.dbc,self.models)
        options=dict(character={},equipment=dict(cape=108,shoulders=104),size=128,portrait_size=128)
        original=CharacterDB.prepare;calls=[]
        def prepare(db,*args):calls.append(1);return original(db,*args)
        with patch.object(CharacterDB,'prepare',prepare),tokens.session():
            tokens.pair(options)
            self.assertEqual(len(calls),1)
            prepared=tokens._prepared[1];vertices=prepared['mesh'][0].copy()
            first=tokens.character_db.render_prepared(prepared,128,180,'front')
            second=tokens.character_db.render_prepared(prepared,128,-90,'top')
            first[2]['character']['skin']=999;first[3].clear()
            again=tokens.character_db.render_prepared(prepared,128,180,'front')
            self.assertTrue(np.array_equal(vertices,prepared['mesh'][0]))
            self.assertTrue(np.array_equal(np.asarray(first[0]),np.asarray(again[0])))
            self.assertEqual(again[2]['character']['skin'],0);self.assertTrue(again[3])
            other=dict(options,equipment=dict(cape=108))
            tokens.pair(other);self.assertEqual(len(calls),2)
            self.assertIsNot(tokens._prepared[1],prepared)
        self.assertIsNone(tokens._prepared)

    def test_selected_geosets_must_have_visible_triangles(self):
        db=CharacterDB(self.dbc)
        with RawAssets(self.models) as raw:
            assets,model,replacements,_,_=db.assemble(raw,{},dict(shirt=100))
            with self.assertRaisesRegex(ValueError,'no triangles'):preview(assets,model,128,replacements,geosets=set())
