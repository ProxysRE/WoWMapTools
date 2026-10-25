import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
import numpy as np
from PIL import Image
from wowmap.geometry import mask_shape,signed_distance
from wowmap.planning import expand
from wowmap.structures import wall_parts
from wowmap.render import render
from wowmap.catalog import requirements,search


class GeneralSceneTests(unittest.TestCase):
    def test_smooth_path_and_hole_use_shared_geometry(self):
        shape=dict(type='rectangle',bounds=[1,1,9,9],feather=0,cutouts=[dict(type='ellipse',bounds=[4,4,6,6],feather=0)])
        mask=mask_shape(shape,(100,100),10,np.random.default_rng(1))
        self.assertEqual(mask[50,50],0);self.assertEqual(mask[20,20],1)
        self.assertLess(signed_distance(shape,[5,5]),0);self.assertGreater(signed_distance(shape,[2,2]),0)
        path=dict(type='path',points=[[1,5],[3,2],[7,8],[9,5]],width=1,smooth=True,feather=0)
        self.assertGreater(signed_distance(path,[3,2]),0)
        self.assertEqual(mask_shape(path,(100,100),10,np.random.default_rng(1))[20,30],1)

    def test_scatter_obeys_clearance_and_is_reproducible(self):
        plan=dict(seed=25,size_cells=[20,20],objects=[],floors=[],walls=[],scatter=[dict(id='trees',count=20,
            region=dict(type='rectangle',bounds=[0,0,20,20]),radius=.8,size_range=[2,3],
            exclude=[dict(type='path',points=[[0,10],[20,10]],width=4)],prototypes=[dict(model='world/tree.m2',layer='overhead')])])
        a,report=expand(plan);b,_=expand(plan)
        self.assertEqual(a,b);self.assertEqual(report[0]['placed'],20)
        for i,obj in enumerate(a['objects']):
            self.assertGreaterEqual(abs(obj['position'][1]-10),2.8)
            for other in a['objects'][:i]:self.assertGreaterEqual(np.linalg.norm(np.array(obj['position'])-other['position']),1.6)
        impossible=copy.deepcopy(plan);impossible['scatter'][0]['radius']=30
        with self.assertRaisesRegex(ValueError,'constraints cannot be satisfied'):expand(impossible)

    def test_floor_opening_export_and_no_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);packs=root/'packages';packs.mkdir()
            with ZipFile(packs/'test.zip','w') as archive:
                for name,color in [('grass','green'),('floor','blue'),('wall','red')]:
                    raw=io.BytesIO();Image.new('RGB',(16,16),color).save(raw,format='PNG')
                    archive.writestr(name+'.png',raw.getvalue())
            plan=dict(format='wowmap.scene/1',seed=1,size_cells=[10,8],pixels_per_cell=20,surface_variation=0,
                      base=dict(id='base',asset='grass.png'),floors=[dict(id='floor',asset='floor.png',shape=dict(type='rectangle',bounds=[1,1,9,7],feather=0))],
                      walls=[dict(id='wall',asset='wall.png',points=[[1,3],[9,3]],thickness=.4,openings=[dict(id='gap',type='passage',at=4,width=2)])])
            out=root/'scene';out.mkdir();(out/'map-grid.png').write_text('obsolete')
            render(plan,root/'none',out,packages=packs)
            self.assertFalse((out/'map-grid.png').exists())
            with Image.open(out/'map.png') as image:
                self.assertGreater(image.getpixel((40,60))[0],100)
                self.assertGreater(image.getpixel((100,60))[2],200)
            geometry=json.loads((out/'scene-geometry.json').read_text())['elements']
            opening=next(e for e in geometry if e['type']=='passage')
            self.assertEqual(opening['points'],[[4,3],[6,3]])
            self.assertFalse(json.loads((out/'render.json').read_text())['grid_baked'])

    def test_webp_export_is_lossless_and_has_no_grid_variant(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);packs=root/'packages';packs.mkdir()
            source=Image.new('RGB',(16,16),(30,70,110));blob=io.BytesIO();source.save(blob,format='PNG')
            with ZipFile(packs/'test.zip','w') as archive:archive.writestr('ground.png',blob.getvalue())
            plan=dict(format='wowmap.scene/1',seed=1,size_cells=[4,3],pixels_per_cell=20,surface_variation=0,
                      export_format='webp',base=dict(id='base',asset='ground.png'))
            result=render(plan,root/'none',root/'out',packages=packs)
            with Image.open(root/'out/map.webp') as image:self.assertEqual(image.getpixel((10,10)),(30,70,110))
            self.assertEqual(result['image'],'map.webp')
            self.assertFalse(any('grid' in file.name for file in (root/'out').iterdir()))

    def test_opening_overlap_is_rejected(self):
        wall=dict(points=[[0,0],[10,0]],openings=[dict(at=3,width=4),dict(at=5,width=2)])
        with self.assertRaisesRegex(ValueError,'overlap'):wall_parts(wall)

    def test_catalog_reports_incomplete_model_dependencies(self):
        plan=dict(format='wowmap.scene/1',seed=1,size_cells=[10,10],pixels_per_cell=20,
                  base=dict(id='base',asset='ground.blp'),objects=[dict(id='tree',model='tree.m2',position=[2,2],size_cells=3)])
        records={p:dict(path=p,package=p+'.zip',id='raw:test') for p in ['ground.blp','tree.m2']}
        report=requirements(plan,records)
        self.assertFalse(report['dependencies_complete']);self.assertEqual(report['models_needing_inspection'],['tree.m2'])
        self.assertEqual(search(records,'tree','.m2')[0]['path'],'tree.m2')


if __name__=='__main__':unittest.main()
