"""An interrupted ZIP write must not destroy an existing installation archive."""
import sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from foundry_module_builder import write_install_zip

class InstallArchiveTests(unittest.TestCase):
    def test_complete_readable_archive(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);module=root/'wow-dnd5e';(module/'packs').mkdir(parents=True)
            (module/'module.json').write_text('{"version":"test"}')
            payload=bytes(range(256))*1024;(module/'packs/data.ldb').write_bytes(payload)
            target=root/'install.zip';write_install_zip(module,target)
            with zipfile.ZipFile(target) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()),{'wow-dnd5e/module.json','wow-dnd5e/packs/data.ldb'})
                self.assertEqual(archive.read('wow-dnd5e/packs/data.ldb'),payload)
            self.assertEqual(list(root.glob('*.partial')),[])
    def test_failed_write_retains_previous_archive(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);module=root/'wow-dnd5e';module.mkdir();(module/'module.json').write_text('{}')
            target=root/'install.zip';target.write_bytes(b'previous good delivery')
            with patch.object(zipfile.ZipFile,'write',side_effect=OSError('simulated interrupted write')):
                with self.assertRaises(OSError):write_install_zip(module,target)
            self.assertEqual(target.read_bytes(),b'previous good delivery')
            self.assertEqual(list(root.glob('*.partial')),[])
