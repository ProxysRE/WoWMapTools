import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from wowmap.foundry import uid
from wowmap.population import populate,validate_population,write_population

ROOT=Path(__file__).resolve().parents[1]


def bundle():
    return dict(format='wowmap.foundry/1',mediaRoot='wowmap/inn',scenes=[dict(_id='scene',width=1000,height=800,grid=dict(size=100),flags={'wowmap':dict(key='ground',package='inn')})])


def population():
    return dict(format='wowmap.population/1',actors=[dict(key='innkeeper',document=dict(name='Innkeeper',type='npc',_stats=dict(systemId='dnd5e'),prototypeToken=dict(width=1,height=1),items=[]))],placements=[dict(id='reception',actor='innkeeper',scene='ground',position=[4,3],actor_link=True)])


class PopulationTests(unittest.TestCase):
    def test_actor_links_and_centred_token_coordinates_are_stable(self):
        original=bundle();pop=population();out=populate(original,pop)
        self.assertEqual(out,populate(original,pop));self.assertNotIn('actors',original)
        actor=out['actors'][0];token=out['scenes'][0]['tokens'][0]
        self.assertEqual(actor['_id'],uid('inn','actor','innkeeper'))
        self.assertEqual(token['actorId'],actor['_id']);self.assertTrue(token['actorLink'])
        self.assertEqual((token['x'],token['y']),(350,250));self.assertEqual(token['disposition'],0)

    def test_multiple_unlinked_tokens_share_base_actor_but_have_unique_ids(self):
        p=population();second=copy.deepcopy(p['placements'][0]);second.update(id='guest',actor_link=False,position=[6,3]);p['placements'].append(second)
        result=populate(bundle(),p);a,b=result['scenes'][0]['tokens']
        self.assertEqual(a['actorId'],b['actorId']);self.assertNotEqual(a['_id'],b['_id']);self.assertFalse(b['actorLink'])

    def test_invalid_references_bounds_duplicate_and_raw_sources_are_rejected(self):
        cases=[]
        p=population();p['placements'][0]['actor']='unknown';cases.append(p)
        p=population();p['placements'][0]['scene']='unknown';cases.append(p)
        p=population();p['placements'][0]['position']=[0,0];cases.append(p)
        p=population();p['actors']*=2;cases.append(p)
        p=population();p['actors'][0]['document']['mechanics']={};cases.append(p)
        for p in cases:
            with self.assertRaises(ValueError):populate(bundle(),p)
        with self.assertRaisesRegex(ValueError,'already'):populate(populate(bundle(),population()),population())

    def test_real_builder_batch_builds_and_failure_leaves_no_partial_output(self):
        spec=importlib.util.spec_from_file_location('batch_adapter',ROOT/'tools/build_foundry_batch.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'valid';result=adapter.build_batch('requests/builder/active.json',out)
            self.assertEqual(len(result['documents']),4)
            pop=json.loads((out/'population.json').read_text(encoding='utf-8'));validate_population(pop)
            self.assertEqual(len(pop['actors']),2)
            for row in result['documents']:
                report=json.loads((out/row['report']).read_text(encoding='utf-8'))
                self.assertEqual(report['source_contract']['errors'],[])
                self.assertEqual(report['midi_compatibility']['errors'],[])
            with self.assertRaisesRegex(ValueError,'empty'):adapter.build_batch('requests/builder/active.json',out)
            with self.assertRaises(ValueError):adapter.build_batch('../../outside.json',Path(temp)/'invalid')
            self.assertFalse((Path(temp)/'invalid').exists())
