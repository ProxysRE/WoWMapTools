import unittest
import numpy as np
from PIL import Image
from wowmap.water import validate_water, shoreline_distance, water_surface
from wowmap.render import render
from pathlib import Path
import tempfile

class WaterTests(unittest.TestCase):
    def layer(self):
        return dict(id='river',asset='bed.png',tile_cells=1,shape=dict(type='polygon',points=[[2,0],[8,0],[8,10],[2,10]],feather=0),water=dict(depth_cells=3,ripple_strength=0))

    def test_inlet_does_not_become_a_shore(self):
        d=shoreline_distance(self.layer()['shape'],(100,100),10)
        self.assertAlmostEqual(float(d[0,50]),float(d[50,50]),places=5)
        self.assertGreater(d[0,50],2.8)
        self.assertLess(d[50,20],.1)

    def test_island_cutout_adds_shore(self):
        layer=self.layer();layer['shape']['cutouts']=[dict(type='rectangle',bounds=[4,4,6,6])]
        d=shoreline_distance(layer['shape'],(100,100),10)
        self.assertLess(d[35,50],.5)

    def test_depth_shallow_hint_and_reproducibility(self):
        layer=self.layer();bed=Image.new('RGB',(100,100),'#998866')
        out=np.array(water_surface(bed,layer,10,np.random.default_rng(7)))
        np.testing.assert_array_equal(out,np.array(water_surface(bed,layer,10,np.random.default_rng(7))))
        self.assertGreater(out[50,21].mean(),out[50,50].mean())
        layer['water']['shallow_shapes']=[dict(type='rectangle',bounds=[4,3,6,7],feather=0)]
        shallow=np.array(water_surface(bed,layer,10,np.random.default_rng(7)))
        self.assertGreater(shallow[50,50].mean(),out[50,50].mean()+5)

    def test_invalid_options(self):
        for key,value in [('depth_cells',0),('ripple_cells',float('nan')),('ripple_strength',True),('flow',[0,0]),('shore_color','#aabbccdd')]:
            layer=self.layer();layer['water'][key]=value
            with self.assertRaises(ValueError):validate_water(layer)

    def test_renderer_clips_material_and_keeps_original_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);assets=root/'assets';assets.mkdir();Image.new('RGB',(8,8),'#987654').save(assets/'bed.png')
            import json
            (assets/'catalog.json').write_text(json.dumps(dict(records=[dict(id='bed.png',source='bed.png',file='bed.png')])))
            base=dict(id='land',asset='bed.png',tile_cells=1)
            plan=dict(format='wowmap.scene/1',name='water-test',seed=3,size_cells=[10,10],pixels_per_cell=10,base=base,floors=[self.layer()],surface_variation=0)
            render(plan,assets,root/'wet')
            plan2=dict(plan,floors=[]);render(plan2,assets,root/'dry')
            wet=np.array(Image.open(root/'wet/map.png'));dry=np.array(Image.open(root/'dry/map.png'))
            np.testing.assert_array_equal(wet[:,:19],dry[:,:19])
            self.assertFalse(np.array_equal(wet[:,30:70],dry[:,30:70]))
            self.assertEqual(json.loads((root/'wet/scene-plan.json').read_text())['floors'][0]['shape'],plan['floors'][0]['shape'])

if __name__=='__main__':unittest.main()
