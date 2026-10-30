import struct
import unittest
import numpy as np
from test_models import fixture
from test_poses import MemoryAssets
from wowmap.models import composed_mesh
from wowmap.poses import Skeleton

class MaterialVisibilityTests(unittest.TestCase):
    def test_alpha_linear_and_global_time(self):
        data=bytearray(20)
        def append(blob):
            p=len(data);data.extend(blob);return p
        times=append(struct.pack('<2I',0,1000));keys=append(struct.pack('<2h',0,32767))
        ot=append(struct.pack('<II',2,times));ov=append(struct.pack('<II',2,keys))
        struct.pack_into('<Hh4I',data,0,1,-1,1,ot,1,ov)
        s=Skeleton.__new__(Skeleton);s.data=bytes(data);s.globals=[];s.global_time=1250;s.source=lambda seq:s.data
        np.testing.assert_allclose(s.track(0,'alpha',[1],{'index':0},500),[.5])
        # Global material animation uses the global clock, independently of pose time.
        struct.pack_into('<h',data,2,0);s.data=bytes(data);s.globals=[1000]
        np.testing.assert_allclose(s.track(0,'alpha',[1],{'index':0},0),[.25])

    def test_hidden_whole_body_batch_is_removed_in_bind_and_posed_views(self):
        model,skin,texture=fixture();data=bytearray(model);skin=bytearray(skin)
        count,start=struct.unpack_from('<II',data,60)
        for i in range(count):data[start+i*48+12:start+i*48+16]=bytes(4)
        def append(blob):
            p=len(data);data.extend(blob);return p
        seq=bytearray(64);struct.pack_into('<HHI',seq,0,0,0,1000);struct.pack_into('<I',seq,12,0x20)
        struct.pack_into('<II',data,28,1,append(seq))
        colors=bytearray(80)
        for i in range(2):
            struct.pack_into('<Hh',colors,i*40,0,-1);struct.pack_into('<Hh',colors,i*40+20,0,-1)
        off=append(colors);struct.pack_into('<II',data,72,2,off)
        for i,alpha in enumerate([32767,0]):
            t=append(struct.pack('<I',0));v=append(struct.pack('<h',alpha));ot=append(struct.pack('<II',1,t));ov=append(struct.pack('<II',1,v))
            struct.pack_into('<II',data,off+i*40+24,1,ot);struct.pack_into('<II',data,off+i*40+32,1,ov)
        batches=b''.join(struct.pack('<BB11H',0,0,0,0,0,i,0,0,1,0,0,0,0) for i in range(2))
        struct.pack_into('<II',skin,36,2,len(skin));skin.extend(batches)
        a=MemoryAssets({'test.m2':bytes(data),'test00.skin':bytes(skin),'tileset/test/red.png':texture})
        for pose in [None,'idle']:
            _,draws,info=composed_mesh(a,'test.m2',pose=pose)
            self.assertEqual(len(draws),1);self.assertEqual(info['hidden_material_batches'],[1]);self.assertEqual(draws[0]['material_alpha'],1)

if __name__=='__main__':unittest.main()
