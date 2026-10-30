import io,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from zipfile import ZipFile
from PIL import Image
from wowmap.asset_index import build_index,FILENAME
from wowmap.models import RawAssets,preview
from test_models import fixture


class AssetIndexTests(unittest.TestCase):
    def packages(self,root):
        model,skin,texture=fixture()
        with ZipFile(root/'model.zip','w') as z:
            z.writestr('World/Test.M2',model);z.writestr('World/Test00.skin',skin)
        with ZipFile(root/'texture.zip','w') as z:z.writestr('tileset/test/red.png',texture)
        with ZipFile(root/'unused.zip','w') as z:z.writestr('unused.bin',b'x')

    def test_lazy_open_and_render_bytes_match_without_index(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.packages(root)
            with RawAssets(root) as raw:
                before,_=preview(raw,'world/test.m2',64);self.assertFalse(raw.indexed)
            result=build_index(root);self.assertEqual(result['resources'],4)
            with RawAssets(root) as raw:
                self.assertTrue(raw.indexed);self.assertEqual(len(raw.archives),0)
                self.assertTrue(raw.has('WORLD/TEST.M2'));self.assertEqual(len(raw.archives),0)
                after,_=preview(raw,'world/test.m2',64);self.assertEqual(after.tobytes(),before.tobytes())
                self.assertEqual(len(raw.archives),2)
                self.assertEqual(set(raw.files),{'world/test.m2','world/test00.skin','tileset/test/red.png','unused.bin'})
            self.assertEqual(raw.files,{});self.assertIsNone(raw._index_connection)
            for p in root.glob('*.zip'):p.unlink()

    def test_changed_added_missing_and_corrupt_index_fall_back_safely(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.packages(root);build_index(root)
            os.utime(root/'unused.zip',ns=(1,2))
            with RawAssets(root) as raw:self.assertFalse(raw.indexed)
            build_index(root)
            with ZipFile(root/'extra.zip','w') as z:z.writestr('new.bin',b'new')
            with RawAssets(root) as raw:self.assertFalse(raw.indexed);self.assertEqual(raw.read('new.bin'),b'new')
            build_index(root);(root/'extra.zip').unlink()
            with RawAssets(root) as raw:self.assertFalse(raw.indexed);self.assertFalse(raw.has('new.bin'))
            (root/FILENAME).write_bytes(b'not sqlite')
            with RawAssets(root) as raw:self.assertFalse(raw.indexed)

    def test_verification_bypasses_index_and_duplicate_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.packages(root);build_index(root)
            with RawAssets(root,verify_archives=True) as raw:self.assertFalse(raw.indexed);self.assertEqual(len(raw.archives),3)
            with ZipFile(root/'duplicate.zip','w') as z:z.writestr('WORLD/TEST.M2',b'bad')
            original=(root/FILENAME).read_bytes()
            with self.assertRaisesRegex(ValueError,'Duplicate'):build_index(root)
            self.assertEqual((root/FILENAME).read_bytes(),original,'Failed rebuild must preserve previous index')


if __name__=='__main__':unittest.main()
