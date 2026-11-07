import struct
import unittest
import numpy as np
from wowmap.beams import chain_record,beam_frame

class BeamTests(unittest.TestCase):
    def table(self,path=b'spells/beam.blp\0'):
        data=bytearray(20+177+1+len(path))
        struct.pack_into('<4s4I',data,0,b'WDBC',1,48,177,1+len(path))
        p=20;struct.pack_into('<I',data,p,326);struct.pack_into('<f',data,p+8,.25)
        struct.pack_into('<f',data,p+16,1);struct.pack_into('<I',data,p+28,1)
        data[p+156:p+161]=bytes([255,88,214,220,3]);data[20+177:]=b'\0'+path
        return data

    def test_packed_dbc_colors_and_strings(self):
        row=chain_record(self.table(),326)
        self.assertEqual(row['texture'],'spells/beam.blp')
        np.testing.assert_allclose(row['color'],np.array([88,214,220])/255)
        bad=self.table();struct.pack_into('<I',bad,12,192)
        with self.assertRaises(ValueError):chain_record(bad,326)
        with self.assertRaises(ValueError):chain_record(self.table(b'../beam.blp\0'),326)
        with self.assertRaises(ValueError):chain_record(self.table(),999)

    def test_black_atlas_padding_stays_transparent(self):
        texture=np.zeros((8,16,4),dtype=np.uint8);texture[:,:,3]=255
        record=chain_record(self.table(),326)
        self.assertFalse(beam_frame(texture,record,.2,1,width=64,height=16).any())
        texture[3:5,:,0]=255
        frame=beam_frame(texture,record,.2,1,width=64,height=16)
        self.assertGreater(frame[:,:,3].max(),0)
        self.assertFalse(frame[:,0,3].any());self.assertFalse(frame[:,-1,3].any())

    def test_flow_reversal_and_seamless_time_cycle(self):
        rng=np.random.default_rng(5);texture=rng.integers(0,256,(8,16,4),dtype=np.uint8)
        record=chain_record(self.table(),326)
        a=beam_frame(texture,record,0,1,width=64,height=16)
        b=beam_frame(texture,record,1,1,width=64,height=16)
        np.testing.assert_array_equal(a,b)
        self.assertFalse(np.array_equal(beam_frame(texture,record,.2,1),beam_frame(texture,record,.2,-1)))
