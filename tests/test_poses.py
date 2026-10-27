import math
import struct
import unittest
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch
import numpy as np
from wowmap.poses import Skeleton, pose_options, quaternion, rotation_matrix, slerp, choose_sequence


class MemoryAssets:
    def __init__(self, files): self.files=files;self.reads=[]
    def has(self, path): return path in self.files
    def read(self, path): self.reads.append(path);return self.files[path]


def skeleton_fixture(external=False):
    data=bytearray(304);data[:4]=b'MD20';struct.pack_into('<I',data,4,264);struct.pack_into('<I',data,68,1)
    def append(blob):
        offset=len(data);data.extend(blob);return offset
    seq=bytearray(64);struct.pack_into('<HHI',seq,0,26,0,1000);struct.pack_into('<I',seq,12,0 if external else 0x20)
    struct.pack_into('<II',data,28,1,append(seq))
    bones=bytearray(176)
    struct.pack_into('<h',bones,8,-1);struct.pack_into('<h',bones,88+8,0)
    struct.pack_into('<3f',bones,76,1,0,0)
    start=append(bones);struct.pack_into('<II',data,44,2,start)
    # No animation on the child means its transform still inherits the parent.
    for i in range(2):
        for track in (16,36,56):struct.pack_into('<Hh',data,start+88*i+track,1,-1)
    anim=bytearray(512)
    # Rotate a point (2,0,0) 90 degrees around pivot (1,0,0).
    times=struct.pack('<2I',0,1000)
    keys=struct.pack('<8h',32767,32767,32767,-1,32767,32767,-9599,-9599)
    if external:
        anim[32:40]=times;anim[64:80]=keys;tstart,vstart=32,64
    else:tstart,vstart=append(times),append(keys)
    ot=append(struct.pack('<II',2,tstart));ov=append(struct.pack('<II',2,vstart))
    struct.pack_into('<II',data,start+36+4,1,ot);struct.pack_into('<II',data,start+36+12,1,ov)
    return MemoryAssets({'test.m2':bytes(data),'test0026-00.anim':bytes(anim)}),start


def vertices():
    result=np.zeros(3,dtype=[('position','f4',3),('normal','f4',3),('weights','u1',4),('bones','u1',4)])
    result['position']=(2,0,0);result['normal']=(1,0,0)
    result['weights'][:,0]=255;result['bones'][1,0]=1
    result['weights'][2]=0
    return result


class PoseTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is needed for module checks')
    def test_foundry_module(self):
        subprocess.run(['node',str(Path(__file__).with_name('test_pose_module.mjs'))],check=True)

    def test_pivot_parent_inheritance_normals_and_zero_weights(self):
        assets,_=skeleton_fixture();s=Skeleton(assets,'test.m2',{'animation_id':26,'time_ms':1000})
        v=vertices();before=v.copy();out=s.skin(v)
        np.testing.assert_allclose(out['position'][:2],[(1,1,0)]*2,atol=1e-4)
        np.testing.assert_allclose(out['normal'][:2],[(0,1,0)]*2,atol=1e-4)
        np.testing.assert_array_equal(v,before)
        np.testing.assert_array_equal(out['position'][2],v['position'][2])

    def test_slerp_halfway_and_quaternion_sign(self):
        q=slerp([0,0,0,1],[0,0,1,0],.5)
        np.testing.assert_allclose(rotation_matrix(q)@[1,0,0],[0,1,0],atol=1e-7)
        np.testing.assert_allclose(slerp(q,-q,.25),q,atol=1e-7)

    def test_attachment_uses_parent_transform_after_local_translation(self):
        from wowmap.models import composed_mesh
        assets,_=skeleton_fixture();v=vertices()[:1]
        body=(v.copy(),[],{'unused_missing':[]});part=(v.copy(),[],{'unused_missing':[]})
        with patch('wowmap.models.mesh_data',side_effect=[body,part]):
            out,_,info=composed_mesh(assets,'test.m2',attachments=[{'model':'sword.m2','bone':1,'position':[1,0,0]}],pose={'animation_id':26,'time_ms':1000})
        np.testing.assert_allclose(out['position'],[[1,1,0],[1,2,0]],atol=1e-4)
        self.assertEqual(info['pose']['animation_id'],26)

    def test_step_track_and_global_sequence_use_embedded_keys(self):
        assets,start=skeleton_fixture();data=bytearray(assets.files['test.m2'])
        struct.pack_into('<H',data,start+36,0);assets.files['test.m2']=bytes(data)
        s=Skeleton(assets,'test.m2',{'animation_id':26,'time_ms':500})
        np.testing.assert_allclose(s.skin(vertices())['position'][0],[2,0,0],atol=1e-4)
        # Track keys stay embedded even when the sequence itself is external.
        data=bytearray(skeleton_fixture()[0].files['test.m2'])
        duration_offset=len(data);data.extend(struct.pack('<I',500));struct.pack_into('<II',data,20,1,duration_offset)
        _,sequence_offset=struct.unpack_from('<II',data,28);struct.pack_into('<I',data,sequence_offset+12,0)
        struct.pack_into('<h',data,start+36+2,0)
        assets=MemoryAssets({'test.m2':bytes(data)})
        s=Skeleton(assets,'test.m2',{'animation_id':26,'time_ms':750})
        out=s.skin(vertices());expected=[1+math.cos(math.pi/8),math.sin(math.pi/8),0]
        np.testing.assert_allclose(out['position'][0],expected,atol=1e-4)
        self.assertEqual(s.metadata()['external_sources'],[])

    def test_external_animation_uses_anim_offsets_even_when_inside_m2_bounds(self):
        assets,_=skeleton_fixture(True);s=Skeleton(assets,'test.m2',{'animation_id':26,'time_ms':1000})
        np.testing.assert_allclose(s.skin(vertices())['position'][0],[1,1,0],atol=1e-4)
        self.assertEqual(s.metadata()['external_sources'],['test0026-00.anim'])

    def test_missing_external_and_truncated_keys_fail_explicitly(self):
        assets,_=skeleton_fixture(True);del assets.files['test0026-00.anim']
        with self.assertRaisesRegex(ValueError,'Missing external'): Skeleton(assets,'test.m2',{'animation_id':26}).skin(vertices())
        assets,_=skeleton_fixture(True);assets.files['test0026-00.anim']=b'\0'*70
        with self.assertRaisesRegex(ValueError,'outside source'):Skeleton(assets,'test.m2',{'animation_id':26}).skin(vertices())

    def test_cycle_invalid_bone_and_zero_scale(self):
        assets,start=skeleton_fixture();data=bytearray(assets.files['test.m2']);struct.pack_into('<h',data,start+8,1);assets.files['test.m2']=bytes(data)
        with self.assertRaisesRegex(ValueError,'Cyclic'):Skeleton(assets,'test.m2',{'animation_id':26}).skin(vertices())
        assets,_=skeleton_fixture();v=vertices();v['bones'][0,0]=250
        with self.assertRaisesRegex(ValueError,'invalid skeleton bone'):Skeleton(assets,'test.m2',{'animation_id':26}).skin(v)
        # Collapsed eye-glow bones are valid, not singular-matrix build failures.
        s=Skeleton(assets,'test.m2',{'animation_id':26});s.matrices=[np.zeros((4,4)),np.eye(4)]
        self.assertTrue(np.isfinite(s.skin(vertices())['position']).all())

    def test_pose_validation_and_time_bounds(self):
        for value in [True,{},'walk',{'animation_id':-1},{'animation_id':26,'fraction':float('nan')},
                      {'animation_id':26,'fraction':.5,'time_ms':0},{'animation_id':26,'close_hands':1}]:
            with self.subTest(value=value),self.assertRaises(ValueError):pose_options(value)
        assets,_=skeleton_fixture()
        with self.assertRaisesRegex(ValueError,'duration'):Skeleton(assets,'test.m2',{'animation_id':26,'time_ms':1001})

    def test_alias_cycles_missing_animation_and_combat_selection(self):
        rows=[dict(index=0,animation_id=26,variation=0,flags=0x40,alias=1),dict(index=1,animation_id=17,variation=0,flags=0x20,alias=0)]
        requested,resolved=choose_sequence(rows,{'preset':'combat'},{'main_hand':{'inventory_type':13}})
        self.assertEqual((requested['animation_id'],resolved['animation_id']),(26,17))
        rows[1]['flags']=0x40
        with self.assertRaisesRegex(ValueError,'alias'):choose_sequence(rows,{'animation_id':26})
        with self.assertRaisesRegex(ValueError,'no requested'):choose_sequence(rows,{'animation_id':999})


if __name__=='__main__':unittest.main()
