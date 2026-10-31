import json
from pathlib import Path
import unittest
from wowmap.foundry import compile_scene
from wowmap.navigation import walk_mask,find_path

ROOT=Path(__file__).resolve().parents[1]
class RecoveredCryptTests(unittest.TestCase):
    def plans(self):return {k:json.loads((ROOT/'examples'/('void-'+k+'.json')).read_text(encoding='utf-8')) for k in ('crypt-entrance','crypt-passages','crypt-sanctum')}
    def test_outdoor_approach_and_altar_detour_fit_large_tokens(self):
        plans=self.plans();regions={k:{r['id'] for r in p['foundry']['regions']} for k,p in plans.items()}
        p=plans['crypt-entrance'];s=compile_scene(p,'nav','crypt-entrance',regions,'wowmap/nav/crypt-entrance')
        for token in (1,2):
            mask,step=walk_mask(p,s,token_cells=token)
            self.assertIsNotNone(find_path(mask,step,(20,4),(20,26)),token)
        self.assertFalse(any(d['id']=='memorial-plaque' for d in p['details']))
        self.assertTrue(any(o.get('art_role')=='altar' for o in p['objects']))
    def test_every_transition_region_center_is_reachable(self):
        plans=self.plans();regions={k:{r['id'] for r in p['foundry']['regions']} for k,p in plans.items()}
        starts={'crypt-entrance':(20,4),'crypt-passages':(5.5,20.5),'crypt-sanctum':(7,18)}
        for key,p in plans.items():
            scene=compile_scene(p,'nav',key,regions,'wowmap/nav/'+key)
            mask,step=walk_mask(p,scene)
            for region in p['foundry']['regions']:
                self.assertNotIn('shape',region)
                a,b,c,d=region['shapes'][0]['bounds']
                self.assertIsNotNone(find_path(mask,step,starts[key],((a+c)/2,(b+d)/2)),(key,region['id']))

    def test_ritual_is_a_walkable_decal_and_boss_footprint_stays_clear(self):
        plans=self.plans();regions={k:{r['id'] for r in p['foundry']['regions']} for k,p in plans.items()}
        p=plans['crypt-sanctum'];s=compile_scene(p,'nav','crypt-sanctum',regions,'wowmap/nav/crypt-sanctum')
        rune=next(o for o in p['objects'] if o['id']=='r3-void-ritual')
        self.assertEqual(rune['layer'],'ground');self.assertEqual(rune['art_role'],'ground_decal')
        self.assertFalse(any(d['id'].startswith(('pillar-cap-','pillar-stone-')) for d in p['details']))
        mask,step=walk_mask(p,s,token_cells=3)
        self.assertTrue(mask[int(18/step),int(21/step)])
    def test_all_collision_hulls_survive_native_pixel_rounding(self):
        for p in self.plans().values():
            for b in p['foundry']['barriers']:
                pts=b['points']+([b['points'][0]] if b.get('closed') else [])
                for a,c in zip(pts,pts[1:]):
                    self.assertNotEqual(tuple(round(v*p['pixels_per_cell']) for v in a),tuple(round(v*p['pixels_per_cell']) for v in c),b['id'])

if __name__=='__main__':unittest.main()
