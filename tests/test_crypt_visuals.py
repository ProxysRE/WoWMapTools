import copy, importlib.util, json, subprocess, tempfile, unittest
from pathlib import Path
from test_icons import icon_export
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('visual_policy_batch',ROOT/'tools/build_foundry_batch.py')
batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)

class CryptVisualTests(unittest.TestCase):
    def test_release_has_complete_named_icon_bindings_and_selected_angles(self):
        request=json.loads((ROOT/'requests/builder/void-crypt.json').read_text())
        self.assertTrue(request['require_item_icons']);self.assertTrue(request['require_explicit_angles'])
        count=0
        for entry in request['documents']:
            source=json.loads((ROOT/entry['source']).read_text())
            self.assertEqual(set(entry['item_icons']),{i['system']['identifier'] for i in source['items']})
            count+=len(entry['item_icons'])
            if 'appearance' in entry:
                self.assertNotEqual(entry['appearance']['portrait_yaw'],0)
        self.assertEqual(count,66)

    def test_strict_batch_rejects_missing_ability_icons_before_publishing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);assets=root/'assets';assets.mkdir();icon_export(assets)
            entry=dict(id='brum',mode='npc',source='requests/builder/sources/brum-scavenger.json',item_icons={'brum-stone':'inv_misc_key_01'})
            request=dict(format='foundry-builder.batch/1',require_item_icons=True,documents=[entry])
            original=batch.read_json
            batch.read_json=lambda path:copy.deepcopy(request) if path.name=='visual-test.json' else original(path)
            try:
                out=root/'built'
                with self.assertRaisesRegex(ValueError,'Missing verified WoW item icon'):
                    batch.build_batch('requests/builder/visual-test.json',out,assets)
                self.assertFalse(out.exists())
                del request['require_item_icons']
                with self.assertRaisesRegex(ValueError,'Missing verified WoW item icon'):
                    batch.build_batch('requests/builder/visual-test.json',out,assets)
                self.assertFalse(out.exists())
                entry['item_icons']={k:'inv_misc_key_01' for k in ['brum-bite','brum-stone','brum-hearing']}
                batch.build_batch('requests/builder/visual-test.json',out,assets)
                actor=json.loads((out/'brum.json').read_text())
                for item in actor['items']:
                    self.assertTrue(item['img'].startswith('wowmap/content/icons/'))
                    for activity in item['system'].get('activities',{}).values():self.assertEqual(activity['img'],item['img'])
            finally:batch.read_json=original

    def test_existing_import_visual_update_preserves_combat_state(self):
        subprocess.run(['node',str(ROOT/'tests/test_crypt_visual_update.cjs')],check=True,cwd=ROOT)

    def test_explicit_angles_required_in_release_policy(self):
        with self.assertRaisesRegex(ValueError,'explicit token and portrait angles'):
            batch.validate_visual_policy({},dict(id='wolf',appearance=dict(yaw=-50)),dict(require_explicit_angles=True),None)

if __name__=='__main__':unittest.main()
