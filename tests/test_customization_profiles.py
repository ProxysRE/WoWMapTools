import random,struct,tempfile,unittest
from pathlib import Path
from test_characters import character_fixture
from wowmap.characters import CharacterDB,character_options,section_allowed
from wowmap.character_variants import candidate_character
from wowmap.models import RawAssets

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.dbc,self.models=character_fixture(Path(self.temp.name));self.db=CharacterDB(self.dbc)

    def mark(self,key,flags):
        t=self.db.tables['charsections'];data=bytearray(t.data)
        struct.pack_into('<I',data,20+self.db.sections[key]*t.record_size+7*4,flags);t.data=bytes(data)

    def test_default_normal_rejects_dk_even_when_indices_are_explicit(self):
        self.mark((1,0,0,0,0),5)
        with RawAssets(self.models) as raw:
            with self.assertRaisesRegex(ValueError,'profile normal excludes'):
                self.db.assemble(raw,dict(race='human'),{})
            _,_,_,_,metadata=self.db.assemble(raw,dict(race='human',profile='death_knight'),{})
            self.assertEqual(metadata['customization_profile'],'death_knight')
            self.assertTrue(any(r['flags']&4 for r in metadata['section_flags']))

    def test_optional_face_features_cannot_bypass_profile(self):
        self.mark((1,0,3,1,0),5)
        with RawAssets(self.models) as raw:
            with self.assertRaisesRegex(ValueError,'profile normal excludes'):
                self.db.assemble(raw,{}, {})
            self.db.assemble(raw,dict(profile='death_knight'),{})

    def test_npc_skins_need_explicit_profile_on_playable_bodies(self):
        self.assertFalse(section_allowed(8,'normal',1));self.assertTrue(section_allowed(8,'npc',1))
        self.assertTrue(section_allowed(8,'normal',17))
        for profile in ('normal','npc'):self.assertFalse(section_allowed(5,profile,1))
        self.assertTrue(section_allowed(17,'normal',1));self.assertTrue(section_allowed(5,'death_knight',1))
        with self.assertRaises(ValueError):character_options(dict(profile='anything'),{})
        self.assertEqual(character_options({}, {})[0]['profile'],'normal')

    def test_sampler_does_not_offer_dk_colors(self):
        self.mark((1,0,3,1,0),5)
        with self.assertRaisesRegex(ValueError,'No declared options'):
            candidate_character(self.db,dict(character=dict(race='human',gender='male')),random.Random(1))
        c=candidate_character(self.db,dict(character=dict(race='human',gender='male',profile='death_knight')),random.Random(1))
        self.assertEqual(c['profile'],'death_knight')

if __name__=='__main__':unittest.main()
