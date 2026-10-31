import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
import numpy as np
from PIL import Image
from wowmap.stairs import validate_stairs,render_stairs
from wowmap.render import render,resource_names,validate
from wowmap.models import RawAssets
from wowmap.review import review_plans,verify_decisions
from wowmap.catalog import requirements
from test_models import fixture


def plan():
    return dict(format='wowmap.scene/1',seed=1,size_cells=[8,8],pixels_per_cell=20,surface_variation=0,
                base=dict(id='base',asset='tileset/test/red.png'),objects=[])


class StairsTests(unittest.TestCase):
    def source(self):
        a=np.empty((40,80,3),dtype=np.uint8);a[:20]=(180,160,130);a[20:]=(70,60,50)
        return Image.fromarray(a)

    def test_cardinal_directions_depth_and_no_pixels_outside_flight(self):
        p=plan();s=dict(id='flight',asset='stairs.png',bounds=[2,2,6,6],steps=4,depth_shade=.4)
        images={s['asset']:self.source()};p['stairs']=[s]
        south=render_stairs(p,images,(160,160),20)
        self.assertEqual(south.getbbox(),(40,40,120,120));self.assertLess(south.getpixel((70,107))[0],south.getpixel((70,47))[0])
        for direction,rotation in [('north',Image.Transpose.ROTATE_180),('east',Image.Transpose.ROTATE_90),('west',Image.Transpose.ROTATE_270)]:
            s['down']=direction;actual=render_stairs(p,images,(160,160),20)
            np.testing.assert_array_equal(np.asarray(actual.crop((40,40,120,120))),np.asarray(south.crop((40,40,120,120)).transpose(rotation)))

    def test_rectangular_flight_and_invalid_bounds_direction_steps(self):
        p=plan();s=dict(id='flight',asset='stairs.png',bounds=[1,2,7,4],steps=5,down='east');p['stairs']=[s]
        self.assertEqual(render_stairs(p,{'stairs.png':self.source()},(160,160),20).getbbox(),(20,40,140,80))
        for change in [dict(bounds=[-1,2,7,4]),dict(bounds=[1,2,9,4]),dict(steps=True),dict(steps=0),dict(down='diagonal'),dict(depth_shade=float('nan'))]:
            with self.subTest(change=change),self.assertRaises(ValueError):validate_stairs({**p,'stairs':[{**s,**change}]})

    def test_terrain_resource_resolution_and_deterministic_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);packs=root/'packs';packs.mkdir();_,_,red=fixture()
            stairs=io.BytesIO();self.source().save(stairs,format='PNG')
            with ZipFile(packs/'test.zip','w') as z:z.writestr('tileset/test/red.png',red);z.writestr('stairs.png',stairs.getvalue())
            p=plan();p['stairs']=[dict(id='flight',asset='stairs.png',bounds=[2,2,6,6],steps=4)]
            self.assertIn('stairs.png',resource_names(p));validate(p)
            for name in ['a','b']:render(p,root/'unused',root/name,packages=packs)
            self.assertEqual((root/'a/map-vtt.webp').read_bytes(),(root/'b/map-vtt.webp').read_bytes())
            with Image.open(root/'a/map-vtt.webp') as im:
                self.assertEqual(im.getpixel((5,5)),(255,0,0));self.assertNotEqual(im.getpixel((70,70)),(255,0,0))


class ReviewTests(unittest.TestCase):
    def assets(self,root,missing_texture=False):
        model,skin,texture=fixture()
        with ZipFile(root/'test.zip','w') as z:
            z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin)
            z.writestr('ground.png',texture)
            if not missing_texture:z.writestr('tileset/test/red.png',texture)

    def test_proofs_and_repeated_model_decisions_expire_on_scale_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.assets(root);p=plan()
            p['objects']=[dict(id=str(i),model='world/test.m2',position=[1+i*.2,2],size_cells=2,rotation=90 if i<4 else 0) for i in range(8)]
            with RawAssets(root) as raw:
                report=review_plans({'test':p},raw,root/'review')
                self.assertEqual(len(report['objects']),2);self.assertTrue(report['dependencies_complete'])
                self.assertTrue((root/'review'/report['pages'][0]).is_file())
                with self.assertRaisesRegex(ValueError,'unreviewed'):verify_decisions(report,dict(format='wowmap.visual-decisions/1',accepted={}))
                decisions=dict(format='wowmap.visual-decisions/1',accepted={r['signature']:'Inspected native proof' for r in report['objects']})
                self.assertTrue(verify_decisions(report,decisions))
                p['pixels_per_cell']=21
                changed=review_plans({'test':p},raw,root/'changed')
                with self.assertRaisesRegex(ValueError,'stale'):verify_decisions(changed,decisions)

    def test_missing_texture_distinguishes_downloadable_and_absent_from_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.assets(root,True);p=plan();p['base']['asset']='ground.png'
            p['objects']=[dict(id='obj',model='world/test.m2',position=[2,2],size_cells=2)]
            records={n:dict(path=n,id=n,package='base.zip') for n in ['ground.png','world/test.m2','world/test00.skin']}
            with RawAssets(root) as raw:
                absent=requirements(p,records,raw)
                self.assertIn('tileset/test/red.png',absent['not_in_catalog']);self.assertFalse(absent['dependencies_complete'])
                records['tileset/test/red.png']=dict(path='tileset/test/red.png',id='texture',package='textures.zip')
                downloadable=requirements(p,records,raw)
                self.assertEqual(downloadable['missing_packages'],['textures.zip']);self.assertFalse(downloadable['dependencies_complete'])
                report=review_plans({'test':p},raw,root/'review',records)
                self.assertIn('Missing model dependencies',report['objects'][0]['error'])

    def test_missing_floor_must_not_report_dependencies_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.assets(root);p=plan();p['base']['asset']='absent.png'
            with RawAssets(root) as raw:
                records={'absent.png':dict(path='absent.png',id='floor',package='floor.zip')}
                report=requirements(p,records,raw)
                self.assertFalse(report['dependencies_complete']);self.assertEqual(report['unavailable_resources'],['absent.png'])


if __name__=='__main__':unittest.main()
