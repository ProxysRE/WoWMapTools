"""Интеграционная проверка с настоящим официальным Foundry CLI (не мок)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from class_package_builder import build_package
from foundry_module_builder import create_module, prepare_documents
from compendium_layout import organize, ownership_paths


def without_keys(value):
    if isinstance(value, dict): return {k:without_keys(v) for k,v in value.items() if k!='_key'}
    if isinstance(value, list): return [without_keys(v) for v in value]
    return value


@unittest.skipUnless(os.environ.get('FOUNDRY_CLI_MODULE'), 'Задайте FOUNDRY_CLI_MODULE для настоящей сборки/извлечения LevelDB.')
class LevelDB(unittest.TestCase):
    def test_official_cli_roundtrip(self):
        self._roundtrip('content_package.json')

    def test_standard_options_roundtrip(self):
        self._roundtrip('standard_options.json')

    def _roundtrip(self, filename):
        cli=Path(os.environ['FOUNDRY_CLI_MODULE']).resolve()
        root=Path(__file__).resolve().parents[1]
        package=build_package(json.loads((root/'examples'/filename).read_text(encoding='utf-8')))
        expected=prepare_documents(package,module_id='roundtrip')
        owners=ownership_paths(expected)
        for pack, documents in expected.items():
            documents, folders=organize(documents,pack,ownership=owners,
                                        link_lists=package.get('native_spell_lists',False))
            folder_ids={f['_id'] for f in folders}
            self.assertTrue(all(d.get('folder') in folder_ids for d in documents))
            self.assertTrue(all(f.get('folder') is None or f['folder'] in folder_ids for f in folders))
            expected[pack]=documents+folders
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)
            module=create_module(package,out,cli_module=cli,module_id='roundtrip')
            js='const {extractPack}=await import(process.argv[1]);await extractPack(process.argv[2],process.argv[3]);'
            for pack, documents in expected.items():
                dest=out/'extracted'/pack
                subprocess.run(['node','--input-type=module','--eval',js,cli.as_uri(),str(module/'packs'/pack),str(dest)],check=True,capture_output=True,text=True)
                actual=[json.loads(f.read_text(encoding='utf-8')) for f in dest.glob('*.json')]
                self.assertEqual({d['_id']:without_keys(d) for d in actual},{d['_id']:without_keys(d) for d in documents})

if __name__=='__main__': unittest.main()
