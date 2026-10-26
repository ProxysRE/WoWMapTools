import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from PIL import Image
from wowmap.icons import IconAssets, PREFIX
from wowmap.population import write_population

ROOT=Path(__file__).resolve().parents[1]


def icon_export(root):
    image=io.BytesIO();Image.new('RGBA',(16,16),(255,50,0,127)).save(image,format='PNG')
    raw=image.getvalue();records=[]
    with ZipFile(root/'icons.zip','w') as archive:
        for name in ['inv_misc_key_01','spell_fire_fireball']:
            member=f'interface/icons/{name}.png';archive.writestr(member,raw)
            records.append(dict(path=member,member=member,package='packages/icons.zip',
                                size=len(raw),id='raw:'+hashlib.sha256(raw).hexdigest()))
    with gzip.open(root/'catalog.jsonl.gz','wt',encoding='utf-8') as stream:
        for record in records:stream.write(json.dumps(record)+'\n')
    return records


class IconTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.assets=self.root/'assets';self.assets.mkdir()
        self.records=icon_export(self.assets)

    def test_search_exact_selection_pixel_preservation_and_deduplication(self):
        icons=IconAssets(self.assets)
        self.assertEqual(icons.search('misc key')['matches'],1)
        original={'img':'original','items':[{'img':'original'}],'prototypeToken':{'texture':{'src':'old'}}}
        built=icons.bind(original,{'/img':'INV_MISC_KEY_01','/items/0/img':'inv_misc_key_01.png',
                                   '/prototypeToken/texture/src':'interface/icons/inv_misc_key_01.png'})
        self.assertEqual(original['img'],'original')
        self.assertEqual(built['img'],built['items'][0]['img'])
        self.assertEqual(built['img'],built['prototypeToken']['texture']['src'])
        self.assertEqual(len(icons.images),1)
        # Equal pixels from different source names share the resulting file too.
        self.assertEqual(icons.select('spell_fire_fireball'),built['img'])
        self.assertEqual(len(icons.media),1)
        icons.write(self.root/'out')
        with Image.open(self.root/'out'/built['img']) as image:
            self.assertEqual(image.convert('RGBA').getpixel((0,0)),(255,50,0,127))

    def test_unknown_ambiguous_unsafe_corrupt_and_nonimage_targets_fail(self):
        icons=IconAssets(self.assets)
        for name in ['unknown','../inv_misc_key_01','/interface/icons/inv_misc_key_01.png']:
            with self.assertRaises(ValueError):icons.select(name)
        for pointer in ['/name','/items/9/img','/items/-1/img','/items/01/img','/bad~2/img']:
            with self.assertRaises(ValueError):icons.bind({'name':'Name','items':[{}]}, {pointer:'inv_misc_key_01'})
        icons.records[self.records[0]['path']]['package']='../outside.zip'
        with self.assertRaisesRegex(ValueError,'Unsafe'):icons.select('inv_misc_key_01')
        icons=IconAssets(self.assets);icons.records[self.records[0]['path']]['id']='raw:'+'0'*64
        with self.assertRaisesRegex(ValueError,'checksum'):icons.select('inv_misc_key_01')
        icons=IconAssets(self.assets);icons.names['inv_misc_key_01'].append('second')
        with self.assertRaisesRegex(ValueError,'exactly once'):icons.select('inv_misc_key_01')

    def test_real_builder_icons_and_scene_population_media_transfer(self):
        spec=importlib.util.spec_from_file_location('icon_batch_adapter',ROOT/'tools/build_foundry_batch.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        request=ROOT/'requests/builder/icons-demo.json'
        out=self.root/'built'
        with self.assertRaisesRegex(ValueError,'--icon-assets'):adapter.build_batch(str(request),out)
        self.assertFalse(out.exists())
        report=adapter.build_batch(str(request),out,self.assets)
        self.assertEqual(len(report['media']),1)
        key=json.loads((out/'pantry-key.json').read_text(encoding='utf-8'))
        pop=json.loads((out/'population.json').read_text(encoding='utf-8'))
        self.assertEqual(pop['actors'][0]['document']['items'][0]['img'],key['img'])
        for row in report['documents']:
            self.assertEqual(hashlib.sha256((out/row['file']).read_bytes()).hexdigest(),row['sha256'])
        export=self.root/'map';folder=export/'wowmap/inn';(folder/'ground').mkdir(parents=True);(folder/'upper').mkdir()
        scene=dict(_id='ground',width=3600,height=3000,grid=dict(size=100),flags={'wowmap':dict(key='ground',package='inn')})
        upper=copy.deepcopy(scene);upper['_id']='upper';upper['flags']['wowmap']['key']='upper'
        original=dict(format='wowmap.foundry/1',mediaRoot='wowmap/inn',scenes=[scene,upper])
        bundle=folder/'bundle.json';bundle.write_text(json.dumps(original),encoding='utf-8')
        for k in ['ground','upper']:(folder/k/'scene.json').write_text('{}')
        media_path=report['media'][0]['file'];source=out/media_path;raw=source.read_bytes()
        source.write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'checksum'):write_population(bundle,out/'population.json')
        self.assertEqual(json.loads(bundle.read_text()),original)
        self.assertFalse((export/media_path).exists())
        source.write_bytes(raw)
        result=write_population(bundle,out/'population.json')
        self.assertEqual(result['actors'],2);self.assertEqual(result['tokens'],2)
        self.assertEqual((export/media_path).read_bytes(),raw)
        self.assertIn(media_path,json.loads(bundle.read_text(encoding='utf-8'))['externalMedia'])

    def test_failed_icon_binding_never_publishes_partial_batch(self):
        spec=importlib.util.spec_from_file_location('bad_icon_batch_adapter',ROOT/'tools/build_foundry_batch.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        # Keep test inputs outside the checkout; patch the established source reader only.
        original=adapter.read_json
        def request_with_missing_icon(path):
            data=original(path)
            if path.name=='icons-demo.json':data['documents'][-1]['icons']['/img']='missing_icon'
            return data
        adapter.read_json=request_with_missing_icon
        out=self.root/'bad'
        with self.assertRaises(ValueError):adapter.build_batch('requests/builder/icons-demo.json',out,self.assets)
        self.assertFalse(out.exists())
