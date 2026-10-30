import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import numpy as np
from PIL import Image
from wowmap.corridors import compile_network
from wowmap.burials import render_burials,validate_burials
from wowmap.models import RawAssets,preview
from wowmap.objects import cached_sprite
from wowmap.recover_assets import recover
from wowmap.mpq import PATCH_FILE
from test_models import fixture


class CorridorTests(unittest.TestCase):
    def config(self):
        return dict(wall_asset='wall.blp',floor_asset='floor.blp',corridors=[dict(id='main',width=3,points=[[3.5,3.5],[12.5,3.5],[12.5,12.5],[3.5,12.5],[3.5,3.5]])])

    def test_union_has_hole_and_compact_boundaries(self):
        floors,walls,metrics=compile_network(self.config(),[16,16])
        self.assertEqual(metrics['physical_loops'],1);self.assertEqual(len(floors[0]['shape']['cutouts']),1)
        self.assertEqual(len(walls),8)
        from wowmap.navigation import inside
        self.assertTrue(inside(floors[0]['shape'],np.array([3.5]),np.array([6]))[0])
        self.assertFalse(inside(floors[0]['shape'],np.array([8]),np.array([8]))[0])

    def test_diagonal_disconnected_and_outside_paths_fail(self):
        base=self.config()
        bad=copy.deepcopy(base);bad['corridors'][0]['points']=[[2.5,2.5],[7.5,7.5]]
        with self.assertRaisesRegex(ValueError,'orthogonal'):compile_network(bad,[16,16])
        bad=copy.deepcopy(base);bad['rooms']=[dict(id='island',bounds=[.5,.5,1,1])]
        with self.assertRaisesRegex(ValueError,'Disconnected'):compile_network(bad,[16,16])
        with self.assertRaisesRegex(ValueError,'outside'):compile_network(base,[8,8])

    def test_open_burial_has_depth_and_broken_corner_is_transparent(self):
        p=dict(size_cells=[8,8],burials=[dict(id='test',asset='stone.blp',bounds=[1,1,4,3],state='open')])
        images={'stone.blp':Image.new('RGB',(32,32),(160,140,120))}
        im=render_burials(p,images,(160,160),20)
        self.assertGreater(im.getpixel((21,30))[0],im.getpixel((40,40))[0]);self.assertEqual(im.getpixel((0,0))[3],0)
        p['burials'][0]['state']='broken';broken=render_burials(p,images,(160,160),20)
        self.assertEqual(broken.getpixel((79,20))[3],0)
        p['burials'][0]['bounds']=[1,1,1.2,2]
        with self.assertRaises(ValueError):validate_burials(p)


class ModelTextureTests(unittest.TestCase):
    def test_nonwrapping_material_clamps_while_wrapping_material_repeats(self):
        import struct
        model,skin,_=fixture();model=bytearray(model)
        _,vertices=struct.unpack_from('<II',model,60);_,textures=struct.unpack_from('<II',model,80)
        for i in range(3):struct.pack_into('<2f',model,vertices+i*48+32,-.25,.5)
        pixels=np.zeros((8,8,3),dtype=np.uint8);pixels[:,:4,0]=255;pixels[:,4:,2]=255
        texture=io.BytesIO();Image.fromarray(pixels).save(texture,format='PNG')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for wrap in [0,1]:
                struct.pack_into('<I',model,textures+4,wrap)
                with ZipFile(root/'test.zip','w') as z:z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin);z.writestr('tileset/test/red.png',texture.getvalue())
                with RawAssets(root) as raw:
                    im,_=preview(raw,'world/test.m2',128)
                    self.assertGreater(im.getpixel((64,64))[2 if wrap else 0],150)

    def test_cache_invalidates_when_renderer_fingerprint_changes(self):
        m,s,t=fixture()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with ZipFile(root/'test.zip','w') as z:z.writestr('world/test.m2',m);z.writestr('world/test00.skin',s);z.writestr('tileset/test/red.png',t)
            with RawAssets(root) as raw:
                with patch('wowmap.objects.renderer_fingerprint',return_value='version-a'):
                    self.assertFalse(cached_sprite(raw,'world/test.m2',root/'cache',128)[2]);self.assertTrue(cached_sprite(raw,'world/test.m2',root/'cache',128)[2])
                with patch('wowmap.objects.renderer_fingerprint',return_value='version-b'):
                    self.assertFalse(cached_sprite(raw,'world/test.m2',root/'cache',128)[2])


class FakeArchive:
    def __init__(self,rows):self.rows=rows
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def entries(self,listfile=None,pattern='*'):
        name=pattern.replace('\\','/').lower()
        return [dict(path=p,flags=r[0],locale=0) for p,r in self.rows.items() if p==name]
    def read(self,name,locale=0):return self.rows[name][1]


class RecoveryTests(unittest.TestCase):
    def test_named_resource_recovery_uses_latest_archive_and_reports_missing(self):
        # PNG bytes under an M2 name test archive precedence without requiring BLP fixtures.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'common.MPQ').touch();(root/'patch.MPQ').touch()
            class Storm:
                def open(self,path):return FakeArchive({'test.m2':(0,b'new' if path.name.startswith('patch') else b'old')})
            r=recover(root,root/'out',['test.m2','missing.m2'],storm=Storm())
            self.assertEqual(r['missing'],['missing.m2']);self.assertFalse(r['complete'])
            with ZipFile(root/'out/recovered-crypt-assets.zip') as z:self.assertEqual(z.read('test.m2'),b'new')

    def test_delta_patch_is_never_exported_as_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'common.MPQ').touch()
            class Storm:
                def open(self,path):return FakeArchive({'test.m2':(PATCH_FILE,b'patch blob')})
            r=recover(root,root/'out',['test.m2'],storm=Storm());self.assertTrue(r['blocked']);self.assertIsNone(r['package'])


if __name__=='__main__':unittest.main()
