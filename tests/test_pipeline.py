import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image
from wowmap.assets import Assets, import_zip
from wowmap.render import render, validate


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.assets = self.root / 'assets'
        self.source = self.root / 'textures.zip'
        with zipfile.ZipFile(self.source, 'w') as z:
            for name, color in [('grass', (25,100,35)), ('dirt',(110,70,30))]:
                image = Image.new('RGB',(32,32),color)
                data = io.BytesIO(); image.save(data,format='PNG')
                z.writestr(f'common.MPQ/tileset/test/{name}.png',data.getvalue())
        import_zip(self.source,self.assets)
        self.plan = dict(format='wowmap.scene/1',seed=42,size_cells=[8,6],pixels_per_cell=20,
                         base=dict(id='grass',asset='common.MPQ/tileset/test/grass.png'),
                         layers=[dict(id='trail',asset='common.MPQ/tileset/test/dirt.png',
                                      shape=dict(type='path',points=[[0,3],[8,3]],width=1,feather=.2,roughness=.4))])

    def test_end_to_end_reproducible_but_variable(self):
        for name in ['a','b']:
            render(self.plan,self.assets,self.root/name)
        self.assertEqual((self.root/'a/map.png').read_bytes(), (self.root/'b/map.png').read_bytes())
        changed = copy.deepcopy(self.plan); changed['seed'] += 1
        render(changed,self.assets,self.root/'c')
        self.assertNotEqual((self.root/'a/map.png').read_bytes(),(self.root/'c/map.png').read_bytes())
        with Image.open(self.root/'a/map.png') as image:
            self.assertEqual(image.size,(160,120))
            self.assertGreater(image.getpixel((80,60))[0], image.getpixel((80,0))[0])
        metadata=json.loads((self.root/'a/render.json').read_text())
        self.assertFalse(metadata['foundry_scene_export'])

    def test_zip_escape_rejected_before_writing(self):
        bad = self.root/'bad.zip'
        with zipfile.ZipFile(bad,'w') as z:
            z.writestr('../escape.png',b'bad')
        with self.assertRaises(ValueError):
            import_zip(bad,self.root/'new')
        self.assertFalse((self.root/'new').exists())

    def test_repeat_import_and_missing_asset(self):
        import_zip(self.source,self.assets)
        self.assertEqual(len(Assets(self.assets).records),2)
        self.plan['base']['asset']='missing'
        with self.assertRaisesRegex(ValueError,'Asset not found'):
            render(self.plan,self.assets,self.root/'bad-output')
        self.assertFalse((self.root/'bad-output').exists())

    def test_invalid_size_and_geometry(self):
        for key,value in [('pixels_per_cell',0),('size_cells',[100000,100000])]:
            plan=copy.deepcopy(self.plan);plan[key]=value
            with self.assertRaises(ValueError): validate(plan)
        self.plan['layers'][0]['shape']['width']=-1
        with self.assertRaises(ValueError): validate(self.plan)


if __name__ == '__main__':
    unittest.main()
