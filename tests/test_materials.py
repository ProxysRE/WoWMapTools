import io
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile
import numpy as np
from PIL import Image
from test_models import fixture
from wowmap.models import RawAssets,inspect_model,preview,additive_composite,sphere_uv,combine_secondary,material_draws,model_info
from wowmap.objects import cached_sprite
from wowmap.catalog import requirements


def png(color, center_only=False):
    image=Image.new('RGBA',(8,8),(0,0,0,255) if center_only else color)
    if center_only:image.putpixel((4,4),color)
    output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()


def unused_reference(model):
    model=bytearray(model);count,offset=struct.unpack_from('<II',model,80)
    rows=bytes(model[offset:offset+count*16]);name=b'world/unneeded/glow.blp\0'
    new_offset=len(model)
    struct.pack_into('<II',model,80,count+1,new_offset)
    model.extend(rows+struct.pack('<4I',0,0,len(name),new_offset+len(rows)+16)+name)
    struct.pack_into('<I',model,68,2)  # LOD 1 is declared, but this render uses LOD 0.
    return model


def overlay_fixture(overlay_z=0, coordinate=0, duplicate=False, blend=4):
    model,skin,_=fixture();model=bytearray(model);skin=bytearray(skin)
    def append(target,header,raw,count):
        struct.pack_into('<II',target,header,count,len(target));target.extend(raw)
    count,off=struct.unpack_from('<II',model,60)
    vertices=bytes(model[off:off+count*48]);back=bytearray(vertices)
    for i in range(3):struct.pack_into('<f',back,i*48+8,overlay_z)
    append(model,60,vertices+back,6)
    names=[b'tileset/test/base.png\0',b'tileset/test/glow.png\0'];start=len(model)+32
    rows=struct.pack('<4I',0,0,len(names[0]),start)+struct.pack('<4I',0,0,len(names[1]),start+len(names[0]))
    append(model,80,rows,2);model.extend(b''.join(names))
    append(model,112,struct.pack('<4H',1,0,17,blend),2)
    append(model,128,struct.pack('<2H',0,1),2)
    append(model,136,struct.pack('<2h',0,coordinate),2)
    append(skin,4,struct.pack('<6H',0,1,2,3,4,5),6)
    triangles=[0,1,2,3,4,5]+([3,4,5] if duplicate else [])
    append(skin,12,struct.pack('<'+'H'*len(triangles),*triangles),len(triangles))
    body=struct.pack('<10H',0,0,0,3,0,3,1,0,1,0)+b'\0'*28
    glow=struct.pack('<10H',0,0,3,3,3,6 if duplicate else 3,1,0,1,0)+b'\0'*28
    append(skin,28,body+glow,2)
    # Glow comes first in the file: the renderer must put it after solid geometry.
    glow_batch=struct.pack('<BB11H',16,0,0,1,1,65535,1,1,1,1,1,0,0)
    body_batch=struct.pack('<BB11H',16,0,0,0,0,65535,0,0,1,0,0,0,0)
    append(skin,36,glow_batch+body_batch,2)
    return model,skin


class MaterialTests(unittest.TestCase):
    def test_material_layer_is_not_the_uv_lookup_index(self):
        model,skin,texture=fixture();model=bytearray(model);skin=bytearray(skin)
        struct.pack_into('<II',model,136,1,len(model));model.extend(struct.pack('<h',0))
        n,off=struct.unpack_from('<II',skin,36)
        struct.pack_into('<H',skin,off+12,9)  # materialLayer=9; only UV lookup 0 exists
        with tempfile.TemporaryDirectory() as temp:
            with ZipFile(Path(temp)/'assets.zip','w') as z:
                z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin);z.writestr('tileset/test/red.png',texture)
            with RawAssets(temp) as raw:
                im,_=preview(raw,'world/test.m2',64)
                self.assertTrue(im.getbbox())

    def test_two_stage_material_dependencies_and_mod2x_no_alpha(self):
        original,skin,_=fixture();model=bytearray(original[:160]+b'\0'*152+original[160:]);skin=bytearray(skin)
        for header in (60,80,112,128):
            n,off=struct.unpack_from('<II',original,header);struct.pack_into('<II',model,header,n,off+152)
        n,off=struct.unpack_from('<II',model,80)
        pathlen,pathoff=struct.unpack_from('<II',model,off+8)
        struct.pack_into('<I',model,off+12,pathoff+152)
        name=b'tileset/test/second.png\0';records=bytes(model[off:off+16]);newoff=len(model)
        struct.pack_into('<II',model,80,2,newoff)
        model.extend(records+struct.pack('<4I',0,0,len(name),newoff+32)+name)
        for header,raw,count in [(128,struct.pack('<2H',0,1),2),(136,struct.pack('<2h',0,-1),2),(304,struct.pack('<2H',1,6),2)]:
            struct.pack_into('<II',model,header,count,len(model));model.extend(raw)
        struct.pack_into('<I',model,16,8)
        _,off=struct.unpack_from('<II',skin,36);struct.pack_into('<H',skin,off+14,2)
        with tempfile.TemporaryDirectory() as temp:
            with ZipFile(Path(temp)/'assets.zip','w') as z:
                z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin)
                z.writestr('tileset/test/red.png',png((0,100,0,255)))
            with RawAssets(temp) as raw:
                info=inspect_model(raw,'world/test.m2')
                self.assertEqual(info['missing'],['tileset/test/second.png'])
            with ZipFile(Path(temp)/'assets.zip','a') as z:z.writestr('tileset/test/second.png',png((128,128,128,0)))
            with RawAssets(temp) as raw:
                im,meta=preview(raw,'world/test.m2',128)
                self.assertEqual(len(meta['used_textures']),2)
                self.assertEqual(im.getpixel((64,64))[3],255,'Mod2xNA must not erase opaque body with transparent reflection map')
        base=np.array([[[.2,.4,.6,.7]]]);second=np.array([[[.5,.25,1,0]]])
        np.testing.assert_allclose(combine_secondary(base,second,6),[[[.2,.2,1,.7]]])
        np.testing.assert_allclose(combine_secondary(base,second,3),[[[.7,.65,1,.7]]])

    def test_additive_light_preserves_opaque_alpha_and_black_does_not_cover_background(self):
        base=np.array([[[.2,.3,.4,1],[0,0,0,0]]],dtype=np.float32)
        source=np.array([[[.6,.2,0,.5],[0,0,0,1]]],dtype=np.float32)
        out=additive_composite(base,source)
        np.testing.assert_allclose(out[0,0],[.5,.4,.4,1],atol=1e-6)
        np.testing.assert_array_equal(out[0,1],[0,0,0,0])
        glow=additive_composite(np.zeros((1,1,4)),np.array([[[1,0,0,.5]]]))
        np.testing.assert_allclose(glow[0,0],[1,0,0,.5])

    def test_sphere_mapping_uses_camera_space_normals_and_is_finite_at_pole(self):
        normals=np.array([[0,0,1],[1,0,0],[0,0,0],[1,0,1],[-1,0,1]],dtype=float)
        uv=sphere_uv(normals)
        self.assertTrue(np.isfinite(uv).all())
        np.testing.assert_allclose(uv[:3],[[.5,.5]]*3)
        self.assertAlmostEqual(uv[3,0],.5+1/(2*np.sqrt(2)))
        self.assertAlmostEqual(uv[4,0],.5-1/(2*np.sqrt(2)))

    def render_overlay(self, temp, **kwargs):
        center_only=kwargs.pop('center_only',False)
        model,skin=overlay_fixture(**kwargs)
        with ZipFile(Path(temp)/'assets.zip','w') as z:
            z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin)
            z.writestr('tileset/test/base.png',png((0,100,0,255)))
            z.writestr('tileset/test/glow.png',png((100,0,0,128),center_only))
        with RawAssets(temp) as assets:return preview(assets,'world/test.m2',128)

    def test_coplanar_glow_is_added_once_even_when_triangles_repeat(self):
        with tempfile.TemporaryDirectory() as temp:
            image,meta=self.render_overlay(temp,duplicate=True)
        r,g,b,a=image.getpixel((64,64))
        self.assertAlmostEqual(r,50,delta=1);self.assertEqual((g,b,a),(100,0,255))
        self.assertEqual(image.getpixel((0,0)),(0,0,0,0))
        self.assertEqual(meta['blend_modes'],[0,4])

    def test_glow_behind_solid_geometry_is_occluded(self):
        with tempfile.TemporaryDirectory() as temp:image,_=self.render_overlay(temp,overlay_z=-1)
        self.assertEqual(image.getpixel((64,64)),(0,100,0,255))

    def test_sphere_coordinate_layer_uses_reflection_map_instead_of_mesh_uv(self):
        with tempfile.TemporaryDirectory() as temp:image,meta=self.render_overlay(temp,coordinate=-1,center_only=True)
        self.assertAlmostEqual(image.getpixel((45,85))[0],50,delta=1)
        self.assertEqual(meta['environment_mapping'],'orthographic sphere map')

    def test_unsupported_blend_is_still_an_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'Unsupported preview blend mode: 5'):
                self.render_overlay(temp,blend=5)

    def test_unused_texture_and_other_lod_do_not_block_render_cache_or_catalog(self):
        model,skin,texture=fixture();model=unused_reference(model)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with ZipFile(root/'assets.zip','w') as z:
                z.writestr('world/test.m2',model);z.writestr('world/test00.skin',skin)
                z.writestr('tileset/test/red.png',texture)
                z.writestr('ground.blp',texture)
            with RawAssets(root) as assets:
                info=inspect_model(assets,'world/test.m2')
                self.assertEqual(info['missing'],[])
                self.assertEqual(info['unused_missing'],['world/test01.skin','world/unneeded/glow.blp'])
                image,meta=preview(assets,'world/test.m2',128)
                self.assertTrue(image.getbbox());self.assertNotIn('world/unneeded/glow.blp',meta['used_textures'])
                _,_,cached=cached_sprite(assets,'world/test.m2',root/'cache',128);self.assertFalse(cached)
                _,_,cached=cached_sprite(assets,'world/test.m2',root/'cache',128);self.assertTrue(cached)
                plan=dict(format='wowmap.scene/1',seed=1,size_cells=[10,10],pixels_per_cell=20,
                          base=dict(id='base',asset='ground.blp'),objects=[dict(id='obj',model='world/test.m2',position=[2,2],size_cells=2)])
                names=['ground.blp','world/test.m2','world/test00.skin','tileset/test/red.png']
                records={name:dict(path=name,id='raw:test',package='pack.zip') for name in names}
                result=requirements(plan,records,assets)
                self.assertTrue(result['dependencies_complete']);self.assertEqual(result['not_in_catalog'],[])

    def test_missing_selected_skin_is_required_before_catalog_can_be_complete(self):
        model,_,_=fixture()
        with tempfile.TemporaryDirectory() as temp:
            with ZipFile(Path(temp)/'assets.zip','w') as z:z.writestr('world/test.m2',model)
            with RawAssets(temp) as assets:
                info=inspect_model(assets,'world/test.m2')
                self.assertFalse(info['inspection_complete']);self.assertEqual(info['missing'],['world/test00.skin'])
                with self.assertRaisesRegex(ValueError,'Missing dependencies'):preview(assets,'world/test.m2',128)
