import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from PIL import Image,ImageDraw
from wowmap.objects import transform_sprite,validate_objects,compose_objects
from wowmap.render import render
from test_models import fixture


class ObjectTests(unittest.TestCase):
    def test_off_center_origin_is_fixed_under_clockwise_rotation(self):
        image=Image.new('RGBA',(32,32));draw=ImageDraw.Draw(image)
        draw.rectangle((6,22,10,26),fill='red');draw.rectangle((18,22,22,26),fill='blue')
        meta=dict(world_xy_bounds=[[0,0],[32,32]],pixels_per_world_unit=1,anchor_pixels=[8,24])
        obj=dict(id='marker',model='world/test.m2',position=[40,40],size_cells=32,rotation=90)
        sprite,position,record=transform_sprite(image,meta,obj,1,(100,100))
        canvas=Image.new('RGBA',(100,100));canvas.alpha_composite(sprite,position)
        self.assertGreater(canvas.getpixel((40,40))[0],200)
        self.assertGreater(canvas.getpixel((40,52))[2],200)
        self.assertEqual(record['position_pixels'],[40,40])
        obj['position']=[-500,-500]
        self.assertIsNone(transform_sprite(image,meta,obj,1,(100,100))[0])

    def test_layer_and_explicit_order_control_overlap(self):
        meta=dict(world_xy_bounds=[[0,0],[8,8]],pixels_per_world_unit=1,anchor_pixels=[4,4])
        def sprite(raw,model,cache):
            return Image.new('RGBA',(8,8),'red' if 'red' in model else 'blue'),meta,False
        base=dict(position=[10,10],size_cells=8)
        objects=[dict(base,id='front',model='red.m2',order=2),dict(base,id='back',model='blue.m2',order=1)]
        with patch('wowmap.objects.cached_sprite',side_effect=sprite):
            ground,overhead,_=compose_objects(objects,None,(20,20),1,'unused',progress=lambda *a,**k:None)
        self.assertEqual(ground.getpixel((10,10)),(255,0,0,255))
        self.assertIsNone(overhead.getbbox())
        objects[1]['layer']='overhead'
        with patch('wowmap.objects.cached_sprite',side_effect=sprite):
            ground,overhead,_=compose_objects(objects,None,(20,20),1,'unused',progress=lambda *a,**k:None)
        self.assertEqual(Image.alpha_composite(ground,overhead).getpixel((10,10)),(0,0,255,255))

    def test_raw_scene_end_to_end_and_cache_reuse(self):
        model,skin,texture=fixture()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);packs=root/'packages';packs.mkdir()
            green=io.BytesIO();Image.new('RGB',(16,16),'green').save(green,format='PNG')
            with ZipFile(packs/'test.zip','w') as archive:
                for name,data in [('world/test.m2',model),('world/test00.skin',skin),('tileset/test/red.png',texture),('tileset/test/grass.png',green.getvalue())]:
                    archive.writestr(name,data)
            plan=dict(format='wowmap.scene/1',seed=1,size_cells=[8,6],pixels_per_cell=20,surface_variation=0,
                      base=dict(id='grass',asset='tileset/test/grass.png'),
                      objects=[dict(id='tree',model='world/test.m2',position=[4,3],size_cells=2,layer='overhead',rotation=30)])
            for run in ['a','b']:render(plan,root/'absent-assets',root/run,packages=packs)
            self.assertEqual((root/'a/map.png').read_bytes(),(root/'b/map.png').read_bytes())
            self.assertNotEqual((root/'a/map.png').read_bytes(),(root/'a/map-ground.png').read_bytes())
            report=json.loads((root/'b/objects.json').read_text())
            self.assertEqual(report['sprites_from_cache'],1)
            plan['objects'][0]['model']='world/missing.m2'
            with self.assertRaises(ValueError):render(plan,root/'absent-assets',root/'bad',packages=packs)
            self.assertFalse((root/'bad').exists())

    def test_invalid_object_values_fail_early(self):
        original=dict(id='x',model='world/test.m2',position=[1,2],size_cells=2)
        for key,value in [('position',[float('nan'),0]),('scale',0),('rotation',float('inf')),('opacity',2),('layer','unknown')]:
            obj=copy.deepcopy(original);obj[key]=value
            with self.assertRaises(ValueError):validate_objects([obj])
        with self.assertRaises(ValueError):validate_objects([original,original])


if __name__=='__main__':unittest.main()
