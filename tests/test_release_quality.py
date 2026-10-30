"""Regression checks for image sessions and the NPC publication boundary."""
import importlib.util,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from test_icons import icon_export
from wowmap.icons import IconAssets
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_batch',ROOT/'tools/build_foundry_batch.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class ReleaseQualityTests(unittest.TestCase):
 def test_icon_session_reuses_zip_without_changing_bytes_and_closes_on_error(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);icon_export(root);plain=IconAssets(root)
   expected=[plain.select(x) for x in ['inv_misc_key_01','spell_fire_fireball']]
   icons=IconAssets(root)
   with patch('wowmap.icons.ZipFile',wraps=ZipFile) as opened:
    with self.assertRaisesRegex(RuntimeError,'abort'),icons.session():
     with icons.session():actual=[icons.select(x) for x in ['inv_misc_key_01','spell_fire_fireball']]
     handles=list(icons._archives.values());self.assertEqual(opened.call_count,1)
     self.assertTrue(handles[0].fp);raise RuntimeError('abort')
    self.assertTrue(all(h.fp is None for h in handles));self.assertIsNone(icons._archives)
   self.assertEqual(actual,expected);self.assertEqual(icons.images,plain.images)
   self.assertEqual(icons.media,plain.media)
   (root/'icons.zip').unlink()

 def test_release_token_orientation_is_independent_from_portrait(self):
  entry={'id':'wolf','appearance':{'yaw':-90,'portrait_yaw':35}}
  for yaw in [-90,270]:
   entry['appearance']['yaw']=yaw;mod.validate_visual_policy({},entry,{'require_item_icons':False},None)
  del entry['appearance']['yaw'];mod.validate_visual_policy({},entry,{'require_item_icons':False},None)
  for yaw in [-65,0,True,float('nan'),float('inf')]:
   entry['appearance']['yaw']=yaw
   with self.assertRaisesRegex(ValueError,'face forward'):mod.validate_visual_policy({},entry,{'require_item_icons':False},None)

 def test_effect_icons_are_verified_and_default_images_inherit_item_icon(self):
  class Icons:images={'wowmap/content/icons/approved.webp':b'bytes'}
  item={'name':'Claw','img':'wowmap/content/icons/approved.webp','system':{'activities':{'attack':{'img':'icons/sword.svg'}}},'effects':[{'img':'icons/blank.svg'}]}
  doc={'items':[item]};mod.validate_visual_policy(doc,{'id':'wolf'},{},Icons())
  self.assertEqual(item['effects'][0]['img'],item['img']);self.assertEqual(item['system']['activities']['attack']['img'],item['img'])
  item['effects'][0]['img']='unknown.webp'
  with self.assertRaisesRegex(ValueError,'effect icon'):mod.validate_visual_policy(doc,{'id':'wolf'},{},Icons())
