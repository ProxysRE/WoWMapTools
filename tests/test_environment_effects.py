import copy,struct,unittest
import numpy as np
from PIL import Image
from wowmap.effects import effect_features
from wowmap.effect_loops import smoke_frame
from wowmap.models import combine_secondary,multiplicative_composite
from wowmap.review import verify_decisions
from wowmap.foundry import compile_scene
from test_foundry import plan

class EnvironmentEffectTests(unittest.TestCase):
    def test_effect_declarations_are_reported_without_claiming_to_render_them(self):
        data=bytearray(304);data[:4]=b'MD20';struct.pack_into('<I',data,4,264)
        struct.pack_into('<I',data,296,2);struct.pack_into('<I',data,288,1)
        result=effect_features(bytes(data));self.assertTrue(result['inspected'])
        self.assertEqual(result['particles'],2);self.assertEqual(result['ribbons'],1)
        self.assertTrue(any('not rendered' in w for w in result['warnings']))
        with self.assertRaises(ValueError):effect_features(b'MD20')

    def test_single_effect_dependent_object_needs_visual_review(self):
        row=dict(style=dict(model='smoke.m2'),count=1,signature='one',effect_features=dict(warnings=['particles are not rendered']))
        review=dict(objects=[row],dependencies_complete=True)
        with self.assertRaisesRegex(ValueError,'unreviewed'):
            verify_decisions(review,dict(format='wowmap.visual-decisions/1',accepted={}))
        self.assertTrue(verify_decisions(review,dict(format='wowmap.visual-decisions/1',accepted={'one':'Static base separately checked; missing smoke is supplied by overlay.'})))

    def test_modulation_preserves_alpha_and_does_not_invent_background_coverage(self):
        base=np.array([[[.4,.2,.6,1],[0,0,0,0]]],dtype=np.float32)
        overlay=np.array([[[.5,.5,.5,1],[1,1,1,1]]],dtype=np.float32)
        np.testing.assert_allclose(multiplicative_composite(base,overlay),base)
        overlay[0,0,:3]=0;self.assertEqual(multiplicative_composite(base,overlay)[0,0,3],1)
        second=np.array([[[.5,.25,1,.5]]]);first=np.array([[[.2,.4,.6,.8]]])
        np.testing.assert_allclose(combine_secondary(first,second,1),[[[.1,.1,.6,.4]]])
        np.testing.assert_allclose(combine_secondary(first,second,4),[[[.2,.2,1,.4]]])

    def test_smoke_is_a_deterministic_loop_with_transparent_background(self):
        texture=Image.new('RGBA',(16,16),(128,128,128,255))
        first=np.asarray(smoke_frame(texture,0,size=64));last=np.asarray(smoke_frame(texture,48,size=64))
        np.testing.assert_array_equal(first,last);self.assertEqual(first[0,0,3],0);self.assertGreater(first[...,3].max(),0)
        self.assertLess(first[...,3].max(),180)

    def test_video_tiles_export_without_animating_entire_background(self):
        source=plan();source['foundry']['tiles']=[dict(id='mist',path='wowmap/content/effects/mist.webm',position=[2,2],size_cells=[3,3],opacity=.4,video=dict(autoplay=True,loop=True,volume=0))]
        scene=compile_scene(source,'test','ground',dict(ground={'stairs'},upper={'landing'}),'wowmap/test/ground')
        self.assertEqual(scene['tiles'][0]['video'],dict(autoplay=True,loop=True,volume=0));self.assertEqual(scene['tiles'][0]['alpha'],.4)
        source['foundry']['tiles'][0]['video']['loop']='yes'
        with self.assertRaises(ValueError):compile_scene(source,'test','ground',dict(ground={'stairs'},upper={'landing'}),'wowmap/test/ground')

if __name__=='__main__':unittest.main()
