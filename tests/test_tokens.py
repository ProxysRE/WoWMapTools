import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile
from PIL import Image
from test_models import fixture
from wowmap.models import RawAssets, preview
from wowmap.tokens import AppearanceDB,TokenAssets,index_table
from wowmap.dbc import DBC
from wowmap.population import validate_population,write_population

ROOT=Path(__file__).resolve().parents[1]


def table(fields, rows, strings):
    return struct.pack('<4s4I',b'WDBC',len(rows),fields,fields*4,len(strings))+b''.join(rows)+strings


def appearance_fixture(root):
    dbc=root/'dbc';dbc.mkdir();models=root/'models';(models/'packages').mkdir(parents=True)
    path=b'creature/test/test.mdx\0';skins=b'\0red.png\0blue.png\0'
    model_row=bytearray(28*4);struct.pack_into('<I',model_row,0,43)
    struct.pack_into('<I',model_row,8,1);struct.pack_into('<f',model_row,16,1)
    rows=[]
    for did,texture in [(165,1),(644,9)]:
        row=bytearray(16*4);struct.pack_into('<II',row,0,did,43)
        struct.pack_into('<f',row,16,1);struct.pack_into('<I',row,20,255)
        struct.pack_into('<I',row,24,texture);rows.append(row)
    with ZipFile(dbc/'tables.zip','w') as z:
        z.writestr('dbfilesclient/creaturemodeldata.dbc',table(28,[model_row],b'\0'+path))
        z.writestr('dbfilesclient/creaturedisplayinfo.dbc',table(16,rows,skins))
    model,skin,red=fixture();model=bytearray(model);_,offset=struct.unpack_from('<II',model,80)
    struct.pack_into('<IIII',model,offset,11,0,0,0)
    blue=io.BytesIO();Image.new('RGBA',(8,8),'blue').save(blue,format='PNG')
    with ZipFile(models/'packages/test.zip','w') as z:
        z.writestr('creature/test/test.m2',model);z.writestr('creature/test/test00.skin',skin)
        z.writestr('creature/test/red.png',red);z.writestr('creature/test/blue.png',blue.getvalue())
    return dbc,models


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.dbc,self.models=appearance_fixture(self.root)

    def test_display_links_choose_distinct_skins_without_changing_geometry(self):
        tokens=TokenAssets(self.dbc,self.models)
        self.assertEqual(tokens.db.search('test blue')['matches'],1)
        self.assertEqual(tokens.db.appearance(165)['model'],'creature/test/test.m2')
        red=tokens.select(dict(display_id=165,size=128,yaw=0))
        blue=tokens.select(dict(display_id=644,size=128,yaw=0))
        self.assertNotEqual(red,blue)
        self.assertEqual(tokens.select(dict(display_id=165,size=128,yaw=0)),red)
        self.assertEqual(len(tokens.images),2)
        for path,color in [(red,0),(blue,2)]:
            with Image.open(io.BytesIO(tokens.images[path])) as image:
                self.assertEqual(image.getpixel((0,0))[3],0)
                self.assertGreater(image.getpixel((64,64))[color],150)
            self.assertEqual(hashlib.sha256(tokens.images[path]).hexdigest(),tokens.media[path]['sha256'])
        with RawAssets(self.models) as assets:
            with self.assertRaisesRegex(ValueError,'skin selection'):preview(assets,'creature/test/test.m2',128)
            rotated,meta=preview(assets,'creature/test/test.m2',128,{11:'creature/test/red.png'},90)
            self.assertTrue(rotated.getbbox());self.assertEqual(meta['yaw_degrees'],90)

    def test_unsupported_options_and_display_features_are_explicit_errors(self):
        tokens=TokenAssets(self.dbc,self.models)
        for options in [dict(display_id=True),dict(display_id=0),dict(display_id=999),
                        dict(display_id=165,size=True),dict(display_id=165,yaw=float('nan')),
                        dict(display_id=165,equipment=[1]),dict(display_id=165,actor_image=1)]:
            with self.assertRaises(ValueError):tokens.select(options)
        original=tokens.db.appearance
        for update,message in [({'extended_display_id':1},'Humanoid'),({'geoset_data':1},'geoset'),({'alpha':128},'Translucent')]:
            tokens.db.appearance=lambda did,u=update:{**original(did),**u}
            with self.assertRaisesRegex(ValueError,message):tokens.select(dict(display_id=165))
        self.assertEqual(tokens.images,{})

    def test_mismatched_schema_duplicate_ids_and_missing_model_link_fail(self):
        db=AppearanceDB(self.dbc)
        with self.assertRaisesRegex(ValueError,'layout'):index_table(db.display,28)
        raw=bytearray(db.display.data);struct.pack_into('<I',raw,20+64,165)
        with self.assertRaisesRegex(ValueError,'Duplicate'):index_table(DBC(raw),16)
        db.models.clear()
        with self.assertRaisesRegex(ValueError,'unknown model'):db.appearance(165)

    def test_actual_builder_sets_actor_and_prototype_and_population_copies_token(self):
        spec=importlib.util.spec_from_file_location('token_batch_adapter',ROOT/'tools/build_foundry_batch.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        original_reader=adapter.read_json
        request={'format':'foundry-builder.batch/1','documents':[dict(id='test',mode='npc',
                 source='requests/builder/sources/oren.json',appearance=dict(display_id=165,size=128))],
                 'placements':[dict(id='test',actor='test',scene='ground',position=[2,2])]}
        adapter.read_json=lambda path:copy.deepcopy(request) if path.name=='active.json' else original_reader(path)
        out=self.root/'built'
        with self.assertRaisesRegex(ValueError,'--dbc-assets'):adapter.build_batch('requests/builder/active.json',out)
        result=adapter.build_batch('requests/builder/active.json',out,None,self.dbc,self.models)
        actor=json.loads((out/'test.json').read_text(encoding='utf-8'))
        self.assertEqual(actor['img'],actor['prototypeToken']['texture']['src'])
        self.assertTrue((out/actor['img']).is_file());self.assertEqual(len(result['media']),1)
        pop=json.loads((out/'population.json').read_text(encoding='utf-8'));validate_population(pop)
        scene=dict(_id='ground',width=500,height=500,grid=dict(size=100),flags={'wowmap':dict(key='ground',package='inn')})
        folder=self.root/'map/wowmap/inn';(folder/'ground').mkdir(parents=True)
        bundle=folder/'bundle.json';bundle.write_text(json.dumps(dict(format='wowmap.foundry/1',mediaRoot='wowmap/inn',scenes=[scene])),encoding='utf-8')
        (folder/'ground/scene.json').write_text('{}')
        write_population(bundle,out/'population.json')
        self.assertEqual((self.root/'map'/actor['img']).read_bytes(),(out/actor['img']).read_bytes())
        request['documents'][0]['appearance']['display_id']=999
        with self.assertRaises(ValueError):adapter.build_batch('requests/builder/active.json',self.root/'bad',None,self.dbc,self.models)
        self.assertFalse((self.root/'bad').exists())
        self.assertEqual(actor['system']['details']['race'],'Человек')
