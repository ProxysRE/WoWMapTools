import copy,random,unittest
from collections import Counter
from wowmap.character_variants import balanced_pairs,candidate_character,candidate_equipment,validate_request
from test_character_variants import request

class Catalog:
    sections={(1,0,0,0,2):0,(1,0,0,0,5):0,(1,0,1,7,2):0,(1,0,1,9,5):0,
              (1,0,3,1,3):0,(1,0,3,4,6):0}
    hair={(1,0,1):0,(1,0,4):0};facial={(1,0,0):0}
    class Table:
        def cell(self,row,column):return 1
    tables={'charsections':Table()}

class RandomnessTests(unittest.TestCase):
    def test_short_batches_cover_bodies_and_full_cycle_covers_every_pair(self):
        bodies=[{'id':'male'},{'id':'female'}];outfits=[{'id':'a'},{'id':'b'},{'id':'c'}]
        samples=set()
        for seed in range(100):
            first=balanced_pairs(bodies,outfits,6,random.Random(seed))
            self.assertEqual(first,balanced_pairs(bodies,outfits,6,random.Random(seed)))
            self.assertEqual(len({(b['id'],o['id']) for b,o in first}),6)
            self.assertEqual(len({b['id'] for b,o in first[:2]}),2)
            self.assertEqual(len({o['id'] for b,o in first[:3]}),3)
            samples.add(tuple((b['id'],o['id']) for b,o in first))
        self.assertGreater(len(samples),20)

    def test_fixed_child_fields_constrain_parent_options_without_lucky_retries(self):
        for seed in range(100):
            c=candidate_character(Catalog(),{'character':{'face':9,'hair_color':6}},random.Random(seed))
            self.assertEqual((c['skin'],c['face'],c['hair_style'],c['hair_color']),(5,9,4,6))
        with self.assertRaisesRegex(ValueError,'No declared option'):
            candidate_character(Catalog(),{'character':{'skin':2,'face':9}},random.Random(1))

    def test_equipment_pools_are_reproducible_diverse_and_allow_an_empty_slot(self):
        outfit={'equipment':{'shirt':100},'equipment_pools':{'cape':[1190,1270,None]}}
        original=copy.deepcopy(outfit);counts=Counter()
        for seed in range(900):
            first=candidate_equipment(outfit,random.Random(seed))
            self.assertEqual(first,candidate_equipment(outfit,random.Random(seed)))
            self.assertEqual(first['shirt'],100);counts[first.get('cape')]+=1
        self.assertEqual(outfit,original);self.assertEqual(set(counts),{1190,1270,None})
        self.assertTrue(all(200<n<400 for n in counts.values()),counts)

    def test_pool_schema_rejects_ambiguous_or_biased_choices(self):
        for pools in [{'cape':[1,1]},{'cape':[]},{'cape':[True]},{'cape':[0]},{'cape':[-1]},{'cape':[0x100000000]},{'invented':[1]}]:
            r=request();r['outfits'][0]['equipment_pools']=pools
            with self.assertRaises(ValueError):validate_request(r)
        r=request();r['outfits'][0]['equipment_pools']={'shirt':[100,None]}
        with self.assertRaisesRegex(ValueError,'both fixed'):validate_request(r)

if __name__=='__main__':unittest.main()
