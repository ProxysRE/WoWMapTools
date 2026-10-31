import copy,json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from wowmap.character_variants import candidate_character,plan_variants,build_variants,validate_request
from wowmap.characters import CharacterDB
from wowmap.models import RawAssets
from test_characters import character_fixture


def request():
    return dict(format='wowmap.character-variants.request/1',seed=7,count=4,
                bodies=[dict(id='man',character=dict(race='human',gender='male')),dict(id='woman',character=dict(race='human',gender='female'))],
                outfits=[dict(id='shirt',equipment=dict(shirt=100),pose='bind'),dict(id='robe',equipment=dict(chest=101),pose='bind')])


class CharacterVariantTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.dbc,self.models=character_fixture(self.root);self.db=CharacterDB(self.dbc)

    def test_real_assembly_is_deterministic_unique_and_uses_canonical_token_facing(self):
        with RawAssets(self.models) as raw:
            first=plan_variants(self.db,raw,request());second=plan_variants(self.db,raw,request())
        self.assertEqual(first,second);rows=first['variants']
        self.assertEqual(len({json.dumps(r['appearance'],sort_keys=True) for r in rows}),4)
        self.assertEqual({r['body'] for r in rows},{'man','woman'})
        self.assertEqual({r['outfit'] for r in rows},{'shirt','robe'})
        self.assertTrue(all(r['appearance']['yaw']==-90 and r['appearance']['portrait_yaw']==30 for r in rows))
        result=build_variants(request(),self.dbc,self.models,self.root/'complete')
        for row in result['variants']:
            for file in row['images'].values():self.assertTrue((self.root/'complete'/file).is_file())
        self.assertTrue((self.root/'complete/variants-review.jpg').is_file())

    def test_dbc_relationships_and_fixed_selection_are_respected(self):
        import random
        # Minimal declared catalogue with disjoint face and hair color sets.
        class Catalog:
            sections={(1,0,0,0,2):0,(1,0,0,0,5):0,(1,0,1,7,2):0,(1,0,1,9,5):0,
                      (1,0,3,1,3):0,(1,0,3,4,6):0}
            hair={(1,0,1):0,(1,0,4):0};facial={(1,0,0):0}
            class Table:
                def cell(self,row,column):return 1
            tables={'charsections':Table()}
        for seed in range(20):
            c=candidate_character(Catalog(),dict(character=dict(skin=5,hair_style=4)),random.Random(seed))
            self.assertEqual((c['skin'],c['face'],c['hair_style'],c['hair_color']),(5,9,4,6))
        with self.assertRaisesRegex(ValueError,'No declared option'):
            candidate_character(Catalog(),dict(character=dict(skin=999)),random.Random(1))

    def test_no_duplicates_or_partial_output_if_not_enough_valid_models(self):
        r=request();r['count']=5
        with self.assertRaisesRegex(ValueError,'distinct valid variants'):
            build_variants(r,self.dbc,self.models,self.root/'invalid')
        self.assertFalse((self.root/'invalid').exists())
        r=request();r['outfits'][0]['equipment']={'shirt':999}
        with self.assertRaisesRegex(ValueError,'Rejections'):
            build_variants(r,self.dbc,self.models,self.root/'missing')
        self.assertFalse((self.root/'missing').exists())

    def test_idle_is_default_including_explicit_null(self):
        r=request();r['count']=1
        for outfit in r['outfits']:outfit.pop('pose')
        result=build_variants(r,self.dbc,self.models,self.root/'standing')
        self.assertEqual(result['variants'][0]['appearance']['pose'],'idle')
        for outfit in r['outfits']:outfit['pose']=None
        with RawAssets(self.models) as raw:result=plan_variants(self.db,raw,r)
        self.assertEqual(result['variants'][0]['appearance']['pose'],'idle')

    def test_invalid_requests_are_rejected(self):
        for field,value in [('count',True),('count',25),('seed',False),('portrait_yaw',float('nan')),('portrait_yaw',float('inf'))]:
            r=request();r[field]=value
            with self.assertRaises(ValueError):validate_request(r)
        r=request();r['outfits'][0]['equipment']={'invented_slot':100}
        with self.assertRaises(ValueError):validate_request(r)
        r=request();r['bodies']*=2
        with self.assertRaises(ValueError):validate_request(r)

    def test_secondary_overlay_warnings_do_not_hide_required_missing_layers(self):
        original=self.db.prepare;r=request();r['count']=1
        def wrapped(kind):
            def prepare(*args,**kwargs):
                result=original(*args,**kwargs)
                result['metadata']['omitted_optional_overlays']=[{'kind':kind,'path':'declared-secondary.blp'}]
                return result
            return prepare
        with RawAssets(self.models) as raw:
            for kind in ['scalp_overlay','facial_overlay']:
                with patch.object(self.db,'prepare',side_effect=wrapped(kind)):
                    result=plan_variants(self.db,raw,r)
                    self.assertEqual(result['variants'][0]['warnings'][0]['kind'],kind)
            with patch.object(self.db,'prepare',side_effect=wrapped('overlay')):
                with self.assertRaisesRegex(ValueError,'omitted overlays'):plan_variants(self.db,raw,r)

    def test_one_invalid_body_outfit_has_a_local_retry_limit(self):
        r=request();r['count']=24;counter=iter(range(1000))
        def distinct(*args):return dict(race='human',gender='male',skin=next(counter))
        with patch('wowmap.character_variants.candidate_character',side_effect=distinct),patch.object(self.db,'prepare',side_effect=ValueError('bad combination')) as prepare:
            with self.assertRaisesRegex(ValueError,'distinct valid variants'):plan_variants(self.db,None,r)
            self.assertEqual(prepare.call_count,80)

if __name__=='__main__':unittest.main()
