import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
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
    _,vertices_offset=struct.unpack_from('<II',model,60)
    struct.pack_into('<f',model,vertices_offset+48+8,1)  # A non-flat triangle is visible from both cameras.
    blue=io.BytesIO();Image.new('RGBA',(8,8),'blue').save(blue,format='PNG')
    with ZipFile(models/'packages/test.zip','w') as z:
        z.writestr('creature/test/test.m2',model);z.writestr('creature/test/test00.skin',skin)
        z.writestr('creature/test/red.png',red);z.writestr('creature/test/blue.png',blue.getvalue())
    return dbc,models


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.dbc,self.models=appearance_fixture(self.root)

    def test_variants_are_exported_and_builder_preserves_normal_images(self):
        # Bind snapshots let this integration check focus on packaging/flags,
        # independently of skeleton arithmetic tested with real-format tracks.
        spec=importlib.util.spec_from_file_location('pose_batch_adapter',ROOT/'tools/build_foundry_batch.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        options=dict(display_id=165,size=128,portrait_size=128,pose_variants={'normal':'bind','combat':'bind'})
        request=dict(format='foundry-builder.batch/1',documents=[dict(id='wolf',mode='npc',source='requests/builder/sources/oren.json',appearance=options)],placements=[])
        request_file=ROOT/'requests/builder/test-pose-fixture.json'
        try:
            request_file.write_text(json.dumps(request),encoding='utf-8')
            output=self.root/'variant-build';adapter.build_batch(request_file.relative_to(ROOT).as_posix(),output,dbc_assets=self.dbc,model_assets=self.models)
            actor=json.loads((output/'wolf.json').read_text(encoding='utf-8'))
            variants=actor['flags']['wowmap']['poseVariants']
            self.assertEqual(actor['prototypeToken']['texture']['src'],variants['normal']['token'])
            self.assertEqual(actor['img'],variants['normal']['portrait'])
            self.assertEqual(actor['prototypeToken']['flags']['wowmap']['pose'],'normal')
            for pair in variants.values():
                for path in pair.values():self.assertTrue((output/path).is_file())
            tokens=TokenAssets(self.dbc,self.models)
            for invalid in [True,{}, {'normal':'bind'}, {'normal':'bind','combat':'bind','extra':'bind'}]:
                with self.assertRaisesRegex(ValueError,'normal and combat'):tokens.variants({**options,'pose_variants':invalid})
        finally:request_file.unlink(missing_ok=True)

    def test_session_shares_archives_between_views_and_variants_and_closes_on_failure(self):
        tokens=TokenAssets(self.dbc,self.models)
        options=dict(display_id=165,size=128,portrait_size=128)
        with patch('wowmap.tokens.RawAssets',wraps=RawAssets) as opened:
            with tokens.session():
                first=tokens.pair(options)
                tokens.pair({**options,'display_id':644})
                assets=tokens._assets
                self.assertEqual(opened.call_count,1)
            self.assertFalse(assets.archives);self.assertIsNone(tokens._assets)
            self.assertEqual(first,tokens.pair(options))
            self.assertEqual(opened.call_count,1)  # Cached pairs never reopen ZIPs.
            with self.assertRaisesRegex(RuntimeError,'render failed'):
                with tokens.session(), patch('wowmap.tokens.preview',side_effect=RuntimeError('render failed')):
                    tokens.select({**options,'yaw':30})
            self.assertIsNone(tokens._assets);self.assertIsNone(tokens._stack)
        (self.models/'packages/test.zip').unlink()

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

    def test_token_provenance_does_not_require_unused_declared_resources(self):
        from test_materials import unused_reference
        package=self.models/'packages/test.zip'
        with ZipFile(package) as z:files={name:z.read(name) for name in z.namelist()}
        files['creature/test/test.m2']=unused_reference(files['creature/test/test.m2'])
        with ZipFile(package,'w') as z:
            for name,data in files.items():z.writestr(name,data)
        tokens=TokenAssets(self.dbc,self.models)
        pair=tokens.pair(dict(display_id=165,size=128,portrait_size=128))
        for path in pair.values():
            variant=tokens.media[path]['appearances'][0]
            self.assertIn('world/unneeded/glow.blp',variant['render']['unused_missing_resources'])
            self.assertNotIn('world/unneeded/glow.blp',[r['path'] for r in variant['sources']])

    def test_pair_front_camera_is_not_mirrored_and_has_transparent_margins(self):
        tokens=TokenAssets(self.dbc,self.models)
        pair=tokens.pair(dict(display_id=165,size=128,portrait_size=128))
        self.assertNotEqual(pair['token'],pair['portrait'])
        self.assertIn('/tokens/',pair['token']);self.assertIn('/portraits/',pair['portrait'])
        self.assertEqual(pair['token'],tokens.select(dict(display_id=165,size=128,yaw=-90)))
        self.assertNotEqual(pair['token'],tokens.select(dict(display_id=165,size=128,yaw=90)))
        self.assertEqual(pair,tokens.pair(dict(display_id=165,size=128,portrait_size=128)))
        with Image.open(io.BytesIO(tokens.images[pair['portrait']])) as portrait:
            self.assertGreater(portrait.getpixel((15,70))[3],0)  # +Y projects right, not left.
            self.assertEqual(portrait.getpixel((100,70))[3],0)
            bbox=portrait.getbbox();self.assertGreaterEqual(min(bbox[:2]),8)
            self.assertLessEqual(max(bbox[2:]),120)
            self.assertEqual(portrait.getpixel((0,0))[3],0)
        self.assertIsNone(tokens.pair(dict(display_id=165,actor_image=False))['portrait'])

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
        self.assertNotEqual(actor['img'],actor['prototypeToken']['texture']['src'])
        self.assertTrue((out/actor['img']).is_file());self.assertEqual(len(result['media']),2)
        pop=json.loads((out/'population.json').read_text(encoding='utf-8'));validate_population(pop)
        scene=dict(_id='ground',width=500,height=500,grid=dict(size=100),flags={'wowmap':dict(key='ground',package='inn')})
        folder=self.root/'map/wowmap/inn';(folder/'ground').mkdir(parents=True)
        bundle=folder/'bundle.json';bundle.write_text(json.dumps(dict(format='wowmap.foundry/1',mediaRoot='wowmap/inn',scenes=[scene])),encoding='utf-8')
        (folder/'ground/scene.json').write_text('{}')
        write_population(bundle,out/'population.json')
        self.assertEqual((self.root/'map'/actor['img']).read_bytes(),(out/actor['img']).read_bytes())
        token=actor['prototypeToken']['texture']['src']
        self.assertEqual((self.root/'map'/token).read_bytes(),(out/token).read_bytes())
        request['documents'][0]['appearance']['actor_image']=False
        preserved=self.root/'preserved'
        without_portrait=adapter.build_batch('requests/builder/active.json',preserved,None,self.dbc,self.models)
        self.assertEqual(len(without_portrait['media']),1)
        self.assertEqual(json.loads((preserved/'test.json').read_text(encoding='utf-8'))['img'],'icons/svg/mystery-man.svg')
        request['documents'][0]['appearance']['display_id']=999
        with self.assertRaises(ValueError):adapter.build_batch('requests/builder/active.json',self.root/'bad',None,self.dbc,self.models)
        self.assertFalse((self.root/'bad').exists())
        self.assertEqual(actor['system']['details']['race'],'Человек')
