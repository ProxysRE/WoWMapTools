import shutil
import struct
import subprocess
from pathlib import Path
import unittest
import numpy as np
from wowmap.effects import flat_curve, curve_at, constant_track, composite

class EffectTests(unittest.TestCase):
    def test_ribbon_constant_color_and_corrupt_keys(self):
        from wowmap.effects import typed_constant
        data=bytearray(80)
        struct.pack_into('<Hh4I',data,0,1,-1,1,20,1,28)
        struct.pack_into('<II',data,20,1,36);struct.pack_into('<II',data,28,1,44)
        struct.pack_into('<3f',data,44,.25,.5,1)
        np.testing.assert_allclose(typed_constant(data,0,3,'<f4',[0,0,0]),[.25,.5,1])
        struct.pack_into('<II',data,28,4097,44)
        with self.assertRaisesRegex(ValueError,'outside M2'):typed_constant(data,0,3,'<f4',[0,0,0])

    def test_native_animation_wraps_without_losing_global_time(self):
        from unittest.mock import patch
        from wowmap.effects import skeleton_at
        class ShortPose:
            def __init__(self,*args):self.selected={'duration_ms':500}
        with patch('wowmap.effects.Skeleton',ShortPose):pose=skeleton_at(None,'short',1750)
        self.assertEqual(pose.time,250)
        self.assertEqual(pose.global_time,1750)

    def test_lifetime_curve_uses_normalized_age(self):
        data=bytearray(40)
        struct.pack_into('<4I',data,0,2,16,2,24)
        struct.pack_into('<2H',data,16,0,32767)
        struct.pack_into('<2f',data,24,1,0)
        curve=flat_curve(data,0,1,'<f4')
        self.assertAlmostEqual(curve_at(curve,.25,[0])[0],.75)
        self.assertEqual(curve_at(curve,2,[0])[0],0)
        struct.pack_into('<I',data,8,1)
        with self.assertRaises(ValueError):flat_curve(data,0,1,'<f4')

    def test_nonconstant_emission_is_explicitly_rejected(self):
        data=bytearray(64)
        struct.pack_into('<Hh4I',data,0,1,-1,1,20,1,28)
        struct.pack_into('<II',data,20,2,36);struct.pack_into('<II',data,28,2,44)
        struct.pack_into('<2f',data,44,10,20)
        with self.assertRaisesRegex(ValueError,'constant'):constant_track(data,0,0)
        struct.pack_into('<2f',data,44,10,10)
        self.assertEqual(constant_track(data,0,0),10)

    def test_additive_alpha_and_clipping(self):
        canvas=np.zeros((4,4,4),dtype=np.float32);sprite=np.ones((4,4,4),dtype=np.float32);sprite[:,:,3]=.5
        composite(canvas,sprite,0,0,4)
        self.assertEqual(canvas[0,0,3],.5);self.assertEqual(canvas[0,0,0],.5)
        self.assertEqual(canvas[3,3,3],0)
        dark=np.zeros_like(sprite);dark[:,:,3]=1
        previous=canvas.copy();composite(canvas,dark,2,2,4)
        np.testing.assert_array_equal(canvas,previous)

    @unittest.skipUnless(shutil.which('node'),'Node unavailable')
    def test_foundry_adapter(self):
        result=subprocess.run(['node','tests/test_effect_module.mjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
