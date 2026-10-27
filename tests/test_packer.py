import ctypes as C
import gzip
import io
import json
import os
import struct
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from PIL import Image
from wowmap.mpq import Storm, HANDLE, U32, PATCH_FILE, DELETE_MARKER, FindData, FIND_NAME_BYTES
from wowmap.pack import build, normalize, scan


class FakeArchive:
    def __init__(self, entries): self.items=entries
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def entries(self,listfile=None):
        for path,(data,flags) in self.items.items():
            yield dict(path=path,size=len(data),flags=flags,locale=0)
    def read(self,name,locale=0): return self.items[name][0]


class FakeStorm:
    def __init__(self,archives,root=None): self.archives,self.root=archives,root
    def open(self,path):
        key=Path(path).resolve().relative_to(self.root.resolve()).as_posix() if self.root else Path(path).name
        return FakeArchive(self.archives[key])


def silent(*args,**kwargs): pass


class PackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.data=self.root/'Data';self.data.mkdir()
        raw=io.BytesIO();Image.new('RGB',(16,16),'green').save(raw,format='PNG')
        self.archives={
            'common.MPQ': {'Tileset\\Ashenvale\\grass.png':(raw.getvalue(),0),
                           'World\\Kalimdor\\Ashenvale\\tree.m2':(b'model-original',0),
                           'World\\Kalimdor\\Ashenvale\\old.m2':(b'delete me',0),
                           'Sound\\test.ogg':(b'sound',0), 'Wow.exe':(b'executable',0)},
            'patch.MPQ': {'World\\Kalimdor\\Ashenvale\\tree.m2':(b'model-updated',0),
                          'World\\Kalimdor\\Ashenvale\\old.m2':(b'',DELETE_MARKER)}}
        for name in self.archives: (self.data/name).write_bytes(b'placeholder')
        self.storm=FakeStorm(self.archives)

    def test_virtual_path_normalization_keeps_aliases_and_rejects_unsafe_paths(self):
        cases={'A\\B//./C.blp':'a/b/c.blp','./':'.','':'.','foo/.../bar':'foo/.../bar','ТЕСТ/ФАЙЛ.blp':'тест/файл.blp','a/./b/':'a/b'}
        for source,expected in cases.items():self.assertEqual(normalize(source),expected)
        for source in ['/a','//server/a','C:/a','a:b','a/../b','..','a\\..\\b','\\root','a/./../b']:
            with self.assertRaises(ValueError,msg=source):normalize(source)

    def test_selection_patches_catalog_and_resume(self):
        out=self.root/'bundle'
        report=build(self.data,out,storm=self.storm,progress=silent)
        self.assertEqual(report['status'],'complete')
        self.assertEqual(report['resources'],2)
        with gzip.open(out/'upload/catalog.jsonl.gz','rt',encoding='utf-8') as stream:
            records=[json.loads(line) for line in stream]
        model=next(r for r in records if r['path'].endswith('.m2'))
        with ZipFile(out/'upload'/model['package']) as zip:
            self.assertEqual(zip.read(model['member']),b'model-updated')
        self.assertNotIn(str(self.data),json.dumps(report))
        hashes=[p['sha256'] for p in report['packages']]
        report2=build(self.data,out,storm=self.storm,progress=silent)
        self.assertEqual(hashes,[p['sha256'] for p in report2['packages']])
        package=out/'upload'/report2['packages'][0]['file']
        package.write_bytes(b'corrupted')
        repaired=build(self.data,out,storm=self.storm,progress=silent)
        self.assertEqual(hashes,[p['sha256'] for p in repaired['packages']])

    def test_change_of_source_and_output_inside_client_rejected(self):
        out=self.root/'bundle';build(self.data,out,storm=self.storm,index_only=True,progress=silent)
        (self.data/'common.MPQ').write_bytes(b'different size')
        with self.assertRaisesRegex(ValueError,'Source archives'):
            build(self.data,out,storm=self.storm,progress=silent)
        with self.assertRaisesRegex(ValueError,'outside'):
            build(self.data,self.data/'out',storm=self.storm,progress=silent)

    def test_delta_patch_and_traversal_rejected(self):
        self.archives['patch.MPQ']['World\\Kalimdor\\Ashenvale\\tree.m2']=(b'patch',PATCH_FILE)
        with self.assertRaisesRegex(ValueError,'delta'):
            scan(self.data,self.storm,progress=silent)
        for name in ('../evil.blp','C:/evil.blp','/evil.blp'):
            with self.assertRaises(ValueError): normalize(name)

    def test_interruption_retains_finished_groups(self):
        out=self.root/'bundle';seen=[]
        def stop(message,**kwargs):
            if 'Packing world/' in message: raise KeyboardInterrupt
            seen.append(message)
        with self.assertRaises(KeyboardInterrupt): build(self.data,out,storm=self.storm,progress=stop)
        self.assertEqual(json.loads((out/'upload/summary.json').read_text())['status'],'interrupted')
        report=build(self.data,out,storm=self.storm,progress=silent)
        self.assertEqual(report['status'],'complete')

    def add_localized(self):
        extra={
            'ruRU/locale-ruRU.MPQ': {'Interface\\Icons\\INV_Test.blp':(b'base icon',0),
                                   'Interface\\Icons\\Deleted.blp':(b'old icon',0),
                                   'Interface\\Frame.blp':(b'not an icon',0)},
            'ruRU/patch-ruRU.MPQ': {'Interface\\Icons\\INV_Test.blp':(b'locale patch',0)},
            'patch-2.MPQ': {'Interface\\Icons\\INV_Test.blp':(b'root patch2',0)},
            'ruRU/patch-ruRU-2.MPQ': {'Interface\\Icons\\INV_Test.blp':(b'locale patch2',0),
                                     'Interface\\Icons\\Deleted.blp':(b'',DELETE_MARKER)}}
        self.archives.update(extra)
        for name in extra:
            target=self.data/name;target.parent.mkdir(exist_ok=True);target.write_bytes(b'archive')
        self.storm=FakeStorm(self.archives,self.data)

    def test_icons_locale_patch_order_filter_catalog_and_resume(self):
        self.add_localized()
        out=self.root/'icons'
        report=build(self.data,out,storm=self.storm,profile='icons',progress=silent)
        self.assertEqual(report['resources'],1)
        self.assertTrue(report['locale_archives_included'])
        self.assertEqual(report['profile'],'icons')
        self.assertNotIn(str(self.data),json.dumps(report))
        with gzip.open(out/'upload/catalog.jsonl.gz','rt') as f: records=[json.loads(l) for l in f]
        self.assertEqual(records[0]['archive'],'ruRU/patch-ruRU-2.MPQ')
        with ZipFile(out/'upload'/records[0]['package']) as z:
            self.assertEqual(z.read('interface/icons/inv_test.blp'),b'locale patch2')
        repeated=build(self.data,out,storm=self.storm,profile='icons',progress=silent)
        self.assertEqual(report['packages'],repeated['packages'])
        with self.assertRaisesRegex(ValueError,'Source archives'):
            build(self.data,out,storm=self.storm,progress=silent)
        # The original full graphics profile still excludes language archives.
        effective,_,_=scan(self.data,self.storm,progress=silent)
        self.assertFalse(any('/' in r['archive'] for r in effective.values()))

    def test_icons_multiple_languages_require_explicit_choice(self):
        self.add_localized()
        name='enUS/locale-enUS.MPQ';target=self.data/name
        target.parent.mkdir();target.write_bytes(b'archive')
        self.archives[name]={'Interface\\Icons\\INV_Test.blp':(b'enUS',0)}
        with self.assertRaisesRegex(ValueError,'Multiple client languages'):
            scan(self.data,self.storm,profile='icons',progress=silent)
        effective,_,_=scan(self.data,self.storm,profile='icons',locale='rUrU',progress=silent)
        self.assertEqual(len(effective),1)
        with self.assertRaisesRegex(ValueError,'requested language'):
            scan(self.data,self.storm,profile='icons',locale='zzZZ',progress=silent)

    def test_icons_empty_diagnostic_and_delta_rejection(self):
        out=self.root/'empty'
        with self.assertRaisesRegex(ValueError,'scan-diagnostic'):
            build(self.data,out,storm=self.storm,profile='icons',progress=silent)
        diagnostic=json.loads((out/'scan-diagnostic.json').read_text())
        self.assertEqual(diagnostic['status'],'no_resources')
        self.assertNotIn(str(self.data),json.dumps(diagnostic))
        self.add_localized()
        self.archives['ruRU/patch-ruRU-2.MPQ']['Interface\\Icons\\INV_Test.blp']=(b'delta',PATCH_FILE)
        with self.assertRaisesRegex(ValueError,'delta'):
            scan(self.data,self.storm,profile='icons',progress=silent)

    def test_dbc_profile_validates_localized_patched_tables_and_resume(self):
        from wowmap.dbc import DBC
        self.add_localized()
        def table(value):return struct.pack('<4s4I',b'WDBC',1,1,4,1)+struct.pack('<I',value)+b'\0'
        key='DBFilesClient\\CreatureDisplayInfo.dbc'
        self.archives['common.MPQ'][key]=(table(1),0)
        self.archives['ruRU/locale-ruRU.MPQ'][key]=(table(2),0)
        self.archives['ruRU/patch-ruRU-2.MPQ'][key]=(table(3),0)
        self.archives['ruRU/locale-ruRU.MPQ']['Other\\Skip.dbc']=(table(4),0)
        out=self.root/'dbc'
        report=build(self.data,out,storm=self.storm,profile='dbc',progress=silent)
        self.assertEqual(report['resources'],1)
        self.assertEqual(report['extensions'],{'.dbc':1})
        self.assertTrue(report['locale_archives_included'])
        details=json.loads((out/'upload/dbc-report.json').read_text())
        self.assertEqual(details['tables'][0]['records'],1)
        self.assertEqual(details['appearance_tables']['creatures']['missing'],['creaturemodeldata.dbc'])
        self.assertNotIn(str(self.data),json.dumps(report))
        with ZipFile(out/'upload'/report['packages'][0]['file']) as z:
            self.assertEqual(DBC(z.read('dbfilesclient/creaturedisplayinfo.dbc')).cell(0,0),3)
        again=build(self.data,out,storm=self.storm,profile='dbc',progress=silent)
        self.assertEqual(again['packages'],report['packages'])
        self.assertEqual(json.loads((out/'upload/dbc-report.json').read_text()),details)

    def test_invalid_dbc_stops_export_instead_of_reporting_complete(self):
        self.add_localized()
        self.archives['ruRU/locale-ruRU.MPQ']['DBFilesClient\\Broken.dbc']=(b'not a table',0)
        out=self.root/'bad-dbc'
        with self.assertRaisesRegex(ValueError,'Invalid DBC'):
            build(self.data,out,storm=self.storm,profile='dbc',progress=silent)
        self.assertEqual(json.loads((out/'upload/summary.json').read_text())['status'],'failed')


@unittest.skipUnless(os.environ.get('WOWMAP_STORMLIB'),'Native StormLib not configured')
class NativeMPQTests(unittest.TestCase):
    def test_find_data_abi_does_not_overwrite_guard_bytes(self):
        storm=Storm()
        native_path=C.c_wchar_p if os.name=='nt' else C.c_char_p
        storm.bind('SFileCreateArchive',[native_path,U32,U32,C.POINTER(HANDLE)],C.c_bool)
        storm.bind('SFileAddFileEx',[HANDLE,native_path,C.c_char_p,U32,U32,U32],C.c_bool)
        class GuardedFindData(C.Structure):
            _fields_=[('record',FindData),('guard',C.c_ubyte*2048)]
        with tempfile.TemporaryDirectory(prefix='wowmap-abi-') as temp:
            root=Path(temp);path=root/'check.MPQ';h=HANDLE()
            self.assertTrue(storm.lib.SFileCreateArchive(storm.path_arg(path),0x100000,32,C.byref(h)))
            source=root/'source.bin';source.write_bytes(b'ABI check')
            self.assertTrue(storm.lib.SFileAddFileEx(h,storm.path_arg(source),b'Interface\\Icons\\test.blp',0x200,2,2))
            self.assertTrue(storm.lib.SFileCloseArchive(h))
            guarded=GuardedFindData();guarded.guard[:]=[0xA5]*2048
            with storm.open(path) as archive:
                search=storm.lib.SFileFindFirstFile(archive.handle,b'*',C.byref(guarded.record),None)
                self.assertTrue(search)
                try:
                    while storm.lib.SFileFindNextFile(search,C.byref(guarded.record)):pass
                    self.assertEqual(bytes(guarded.guard),bytes([0xA5])*2048)
                finally:storm.lib.SFileFindClose(search)
            self.assertEqual(FIND_NAME_BYTES,260 if os.name=='nt' else 1024)

    def test_native_localized_dbc_export(self):
        from wowmap.dbc import DBC
        storm=Storm()
        native_path=C.c_wchar_p if os.name=='nt' else C.c_char_p
        storm.bind('SFileCreateArchive',[native_path,U32,U32,C.POINTER(HANDLE)],C.c_bool)
        storm.bind('SFileAddFileEx',[HANDLE,native_path,C.c_char_p,U32,U32,U32],C.c_bool)
        with tempfile.TemporaryDirectory(prefix='wowmap-dbc-') as temp:
            root=Path(temp);data=root/'Data';(data/'ruRU').mkdir(parents=True)
            for name,value in [('common.MPQ',1),('ruRU/locale-ruRU.MPQ',2),('ruRU/patch-ruRU-3.MPQ',3)]:
                h=HANDLE()
                self.assertTrue(storm.lib.SFileCreateArchive(storm.path_arg(data/name),0x100000,32,C.byref(h)))
                source=root/'table.bin'
                source.write_bytes(struct.pack('<4s4I',b'WDBC',1,1,4,1)+struct.pack('<I',value)+b'\0')
                self.assertTrue(storm.lib.SFileAddFileEx(h,storm.path_arg(source),b'DBFilesClient\\CreatureDisplayInfo.dbc',0x200,2,2))
                self.assertTrue(storm.lib.SFileCloseArchive(h))
            report=build(data,root/'export',storm=storm,profile='dbc',progress=silent)
            self.assertEqual(report['resources'],1)
            with ZipFile(root/'export/upload'/report['packages'][0]['file']) as z:
                self.assertEqual(DBC(z.read('dbfilesclient/creaturedisplayinfo.dbc')).cell(0,0),3)

    def test_native_localized_icon_export(self):
        storm=Storm()
        native_path=C.c_wchar_p if os.name=='nt' else C.c_char_p
        storm.bind('SFileCreateArchive',[native_path,U32,U32,C.POINTER(HANDLE)],C.c_bool)
        storm.bind('SFileAddFileEx',[HANDLE,native_path,C.c_char_p,U32,U32,U32],C.c_bool)
        with tempfile.TemporaryDirectory(prefix='wowmap-icons-') as temp:
            root=Path(temp);data=root/'Data';(data/'ruRU').mkdir(parents=True)
            for name,content in [('common.MPQ',b'base'),('ruRU/locale-ruRU.MPQ',b'localized'),
                                 ('ruRU/patch-ruRU-3.MPQ',b'latest')]:
                h=HANDLE()
                self.assertTrue(storm.lib.SFileCreateArchive(storm.path_arg(data/name),0x100000,32,C.byref(h)))
                source=root/'icon.bin';source.write_bytes(content)
                self.assertTrue(storm.lib.SFileAddFileEx(h,storm.path_arg(source),b'Interface\\Icons\\INV_Test.blp',0x200,2,2))
                self.assertTrue(storm.lib.SFileCloseArchive(h))
            report=build(data,root/'icons',storm=storm,profile='icons',progress=silent)
            self.assertEqual(report['resources'],1)
            with ZipFile(root/'icons/upload'/report['packages'][0]['file']) as z:
                self.assertEqual(z.read('interface/icons/inv_test.blp'),b'latest')

    def test_real_compressed_mpq_roundtrip_and_pack(self):
        storm=Storm()
        native_path=C.c_wchar_p if os.name=='nt' else C.c_char_p
        storm.bind('SFileCreateArchive',[native_path,U32,U32,C.POINTER(HANDLE)],C.c_bool)
        storm.bind('SFileAddFileEx',[HANDLE,native_path,C.c_char_p,U32,U32,U32],C.c_bool)
        with tempfile.TemporaryDirectory(prefix='wowmap-') as temp:
            root=Path(temp);data=root/'Data';data.mkdir()
            original=b'MD20'+b'0123456789'*4096
            for archive_name,content in [('common.MPQ',original),('patch.MPQ',b'MD20updated')]:
                h=HANDLE()
                self.assertTrue(storm.lib.SFileCreateArchive(storm.path_arg(data/archive_name),0x100000,32,C.byref(h)))
                source=root/'source.bin';source.write_bytes(content)
                self.assertTrue(storm.lib.SFileAddFileEx(h,storm.path_arg(source),b'World\\Kalimdor\\Ashenvale\\Tree.m2',0x200,2,2))
                self.assertTrue(storm.lib.SFileCloseArchive(h))
            with storm.open(data/'common.MPQ') as archive:
                found=list(archive.entries())
                self.assertTrue(any(e['path'].lower().endswith('tree.m2') for e in found))
                self.assertEqual(archive.read('World\\Kalimdor\\Ashenvale\\Tree.m2'),original)
            report=build(data,root/'bundle',storm=storm,progress=silent)
            self.assertEqual(report['resources'],1)
            with ZipFile(root/'bundle/upload'/report['packages'][0]['file']) as archive:
                self.assertEqual(archive.read('world/kalimdor/ashenvale/tree.m2'),b'MD20updated')


if __name__=='__main__': unittest.main()
