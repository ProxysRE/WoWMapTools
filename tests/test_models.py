import io
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile
from PIL import Image
from wowmap.models import RawAssets, inspect_model, model_info, preview


def fixture():
    # One real-format WotLK triangle with a static red texture.
    model=bytearray(160)
    model[:4]=b'MD20';struct.pack_into('<I',model,4,264)
    def append_array(header,data,count):
        struct.pack_into('<II',model,header,count,len(model));model.extend(data)
    vertices=b''
    for xyz,uv in [((-1,-1,0),(0,0)),((1,-1,0),(1,0)),((0,1,0),(.5,1))]:
        vertices+=struct.pack('<3f4B4B3f2f2f',*xyz,255,0,0,0,0,0,0,0,0,0,1,*uv,0,0)
    append_array(60,vertices,3)
    struct.pack_into('<I',model,68,1)
    string=b'tileset/test/red.png\0'
    offset=len(model)+16
    append_array(80,struct.pack('<IIII',0,0,len(string),offset),1)
    model.extend(string)
    append_array(112,struct.pack('<HH',0,0),1)
    append_array(128,struct.pack('<H',0),1)
    skin=bytearray(48);skin[:4]=b'SKIN'
    def skin_array(header,data,count):
        struct.pack_into('<II',skin,header,count,len(skin));skin.extend(data)
    skin_array(4,struct.pack('<3H',0,1,2),3)
    skin_array(12,struct.pack('<3H',0,1,2),3)
    section=struct.pack('<10H',0,0,0,3,0,3,1,0,1,0)+b'\0'*28
    skin_array(28,section,1)
    skin_array(36,struct.pack('<BB11H',0,0,0,0,0,65535,0,0,1,0,0,0,0),1)
    texture=io.BytesIO();Image.new('RGB',(8,8),'red').save(texture,format='PNG')
    return bytes(model),bytes(skin),texture.getvalue()


class ModelTests(unittest.TestCase):
    def test_preview_geometry_transparency_and_missing_dependency(self):
        model,skin,texture=fixture()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with ZipFile(root/'assets.zip','w') as z:
                z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin)
                z.writestr('tileset/test/red.png',texture)
            with RawAssets(root) as assets:
                info=inspect_model(assets,'world/test.m2')
                self.assertEqual(info['missing'],[])
                image,metadata=preview(assets,'world/test.m2',128)
                self.assertGreater(image.getpixel((64,64))[0],150)
                self.assertEqual(image.getpixel((0,0))[3],0)
                self.assertEqual(metadata['anchor_pixels'],[64,64])
            (root/'assets.zip').unlink()
            with ZipFile(root/'assets.zip','w') as z:
                z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin)
            with RawAssets(root) as assets:
                with self.assertRaisesRegex(ValueError,'Missing dependencies'):
                    preview(assets,'world/test.m2',128)

    def test_negative_near_zero_uv_does_not_index_outside_texture(self):
        model,skin,texture=fixture()
        model=bytearray(model);count,offset=struct.unpack_from('<II',model,60)
        for i in range(count): struct.pack_into('<2f',model,offset+i*48+32,-1e-12,-1e-12)
        with tempfile.TemporaryDirectory() as temp:
            with ZipFile(Path(temp)/'assets.zip','w') as z:
                z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin)
                z.writestr('tileset/test/red.png',texture)
            with RawAssets(temp) as assets:
                image,_=preview(assets,'world/test.m2',128)
                self.assertGreater(image.getpixel((64,64))[0],150)

    def test_malformed_model_rejected(self):
        with self.assertRaises(ValueError):model_info(b'bad','world/test.m2')
        model,_,_=fixture();bad=bytearray(model)
        struct.pack_into('<II',bad,80,100,0xffffffff)
        with self.assertRaises(ValueError):model_info(bad,'world/test.m2')

    def test_unsafe_zip_members_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with ZipFile(Path(temp)/'bad.zip','w') as z:z.writestr('../test.m2',b'bad')
            with self.assertRaises(ValueError):RawAssets(temp)


if __name__=='__main__':unittest.main()
