import importlib.util,json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('crypt_author',ROOT/'tools/prepare_crypt_population.py')
author=importlib.util.module_from_spec(spec);spec.loader.exec_module(author)

class CryptPopulationTests(unittest.TestCase):
    def test_all_placements_fit_walls_and_avoid_transition_regions(self):
        author.author();placements=author.placements()
        self.assertEqual(len(placements),24)
        self.assertTrue(all(not p['actor_link'] for p in placements))
        self.assertEqual(next(p for p in placements if p['actor']=='vaelis')['position'],[21,18])
        request=json.loads((ROOT/'requests/builder/void-crypt.json').read_text())
        self.assertEqual(placements,request['placements'])
        self.assertEqual(len(request['documents']),12)

    def test_boss_resources_and_separate_phase_damage_buttons(self):
        source=author.author()['vaelis']
        self.assertEqual(source['system']['attributes']['hp']['max'],300)
        self.assertEqual(source['system']['resources']['legact']['max'],2)
        self.assertEqual(source['system']['resources']['legres']['max'],2)
        items={i['system']['identifier']:i for i in source['items']}
        self.assertEqual(items['vaelis-ray']['mechanics']['damage'][0]['type'],'force')
        self.assertEqual(items['vaelis-ray-void']['mechanics']['damage'][0]['type'],'psychic')
        self.assertEqual(items['vaelis-wave']['mechanics']['uses']['max'],'2')

    def test_gm_helper_workflow(self):
        subprocess.run(['node',str(ROOT/'tests/test_crypt_encounter.cjs')],check=True,cwd=ROOT)

if __name__=='__main__':unittest.main()
