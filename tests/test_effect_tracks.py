import struct
from types import SimpleNamespace
import unittest
import numpy as np
from wowmap.effects import ScalarTrack,birth_phases

class ScalarTrackTests(unittest.TestCase):
    def pose(self,external=False,mode=1,global_id=-1):
        data=bytearray(80);struct.pack_into('<Hh4I',data,0,mode,global_id,1,20,1,28)
        struct.pack_into('<II',data,20,2,0 if external else 48);struct.pack_into('<II',data,28,2,8 if external else 56)
        keys=struct.pack('<2I2f',0,1000,1,5)
        if not external:data[48:64]=keys
        return SimpleNamespace(data=data,sequence={'index':0},selected={'duration_ms':1000},globals=[1000],source=lambda _:keys if external else data)
    def test_external_scalar_and_native_period(self):
        t=ScalarTrack(self.pose(external=True),0)
        self.assertAlmostEqual(t.at(.25),2)
        self.assertAlmostEqual(t.at(1.25),2)
        self.assertAlmostEqual(t.at(-.75),2)
    def test_step_and_global_scalar(self):
        self.assertEqual(ScalarTrack(self.pose(mode=0),0).at(.9),1)
        self.assertEqual(ScalarTrack(self.pose(global_id=0),0).at(.5),3)
        with self.assertRaisesRegex(ValueError,'global'):ScalarTrack(self.pose(global_id=2),0)
    def test_invalid_keys_are_rejected(self):
        p=self.pose();struct.pack_into('<f',p.data,56,float('nan'))
        with self.assertRaisesRegex(ValueError,'Invalid scalar keys'):ScalarTrack(p,0)
        with self.assertRaisesRegex(ValueError,'interpolation'):ScalarTrack(self.pose(mode=2),0)
    def test_animated_rate_produces_more_births_late(self):
        p=self.pose();struct.pack_into('<2f',p.data,56,0,100);t=ScalarTrack(p,0)
        phases=birth_phases(t,1,np.random.default_rng(4))
        self.assertEqual(len(phases),50);self.assertGreater(np.mean(phases),.6)
        np.testing.assert_equal(phases,birth_phases(t,1,np.random.default_rng(4)))
        p=self.pose();struct.pack_into('<2f',p.data,56,13000,13000)
        with self.assertRaisesRegex(ValueError,'budget'):birth_phases(ScalarTrack(p,0),1,np.random.default_rng(4))
