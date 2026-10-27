"""Smoke tests for the standalone Void Crypt renderer and ZIP packager."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


class VoidCryptBuilderTests(unittest.TestCase):
    def test_cli_help(self):
        result=subprocess.run([sys.executable,str(ROOT/"tools/build_void_crypt.py"),"--help"],
                              cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("--preflight-only",result.stdout)
        self.assertIn("--packages",result.stdout)

    def test_archive_only_contains_foundry_products(self):
        from tools.build_void_crypt import archive_export
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            bundle=root/"foundry-void-crypt"
            (bundle/"wowmap"/"void-crypt").mkdir(parents=True)
            (bundle/"wowmap"/"void-crypt"/"bundle.json").write_text('{"scenes":[]}')
            (bundle/"import-foundry.js").write_text("// macro")
            (root/"private-WoW-pack.zip").write_bytes(b"NEVER SHIP THIS")
            output=root/"foundry-void-crypt.zip"
            archive_export(bundle,output)
            with ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()),{
                    "foundry-void-crypt/import-foundry.js",
                    "foundry-void-crypt/wowmap/void-crypt/bundle.json"})
                self.assertNotIn("private-WoW-pack.zip","".join(archive.namelist()))

if __name__=="__main__":
    unittest.main()
