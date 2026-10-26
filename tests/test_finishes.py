import unittest
from PIL import Image,ImageDraw
from wowmap.finishes import validate_finishes,wall_underlay,draw_details
from wowmap.objects import validate_objects,transform_sprite


class FinishTests(unittest.TestCase):
    def test_bounds_center_anchor_removes_model_origin_offset_under_rotation(self):
        image=Image.new('RGBA',(40,40));d=ImageDraw.Draw(image)
        d.rectangle((18,18,22,22),fill='red');d.rectangle((28,18,32,22),fill='blue')
        meta=dict(world_xy_bounds=[[0,0],[40,40]],pixels_per_world_unit=1,anchor_pixels=[5,30])
        obj=dict(id='chair',model='chair.m2',position=[50,50],size_cells=40,position_anchor='bounds-center',rotation=90)
        validate_objects([obj]);patch,pos,record=transform_sprite(image,meta,obj,1,(100,100))
        canvas=Image.new('RGBA',(100,100));canvas.alpha_composite(patch,pos)
        self.assertGreater(canvas.getpixel((50,50))[0],200)
        self.assertGreater(canvas.getpixel((50,60))[2],200)
        self.assertEqual(record['position_anchor'],'bounds-center')
        obj['position_anchor']='unknown'
        with self.assertRaisesRegex(ValueError,'position_anchor'):validate_objects([obj])

    def test_finishes_preserve_door_gap_and_have_no_effect_by_default(self):
        walls=Image.new('RGBA',(160,80));d=ImageDraw.Draw(walls)
        d.rectangle((0,35,59,45),fill='#888888');d.rectangle((100,35,159,45),fill='#888888')
        self.assertIsNone(wall_underlay(walls,20,{}).getbbox())
        result=wall_underlay(walls,20,dict(outline_cells=.05,shadow_cells=.1,shadow_opacity=.5))
        self.assertGreater(result.getpixel((20,34))[3],0)
        self.assertEqual(result.getpixel((80,40))[3],0)

    def test_details_use_cells_and_alpha_without_touching_other_pixels(self):
        p=dict(details=[dict(id='trim',type='rectangle',bounds=[1,1,2,2],fill='#ff0000',opacity=.5)])
        validate_finishes(p);im=draw_details(p,(80,80),20)
        self.assertEqual(im.getpixel((30,30)),(255,0,0,128));self.assertEqual(im.getpixel((5,5))[3],0)
        p['details']*=2
        with self.assertRaisesRegex(ValueError,'unique'):validate_finishes(p)
        with self.assertRaisesRegex(ValueError,'shadow_cells'):validate_finishes(dict(architecture=dict(shadow_cells=-.1)))


if __name__=='__main__':unittest.main()
