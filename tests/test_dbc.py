import struct
import unittest
from wowmap.dbc import DBC, appearance_coverage


class DBCTests(unittest.TestCase):
    def test_header_rows_float_signed_and_localized_strings(self):
        strings=b'\0'+ 'Волк'.encode('utf-8')+b'\0'
        data=struct.pack('<4s4I',b'WDBC',1,4,16,len(strings))+struct.pack('<IifI',27,-9,1.5,1)+strings
        table=DBC(data)
        self.assertEqual(table.metadata()['records'],1)
        self.assertEqual(table.cell(0,0),27)
        self.assertEqual(table.cell(0,1,'int32'),-9)
        self.assertEqual(table.cell(0,2,'float32'),1.5)
        self.assertEqual(table.cell(0,3,'string'),'Волк')
        for row,col in [(-1,0),(1,0),(0,4)]:
            with self.assertRaises(ValueError):table.cell(row,col)
        with self.assertRaises(ValueError):table.cell(0,3,'uint64')
        with self.assertRaisesRegex(ValueError,'offset'):table.cell(0,0,'string')

    def test_malformed_and_packed_tables_are_not_misinterpreted(self):
        valid=struct.pack('<4s4I',b'WDBC',1,1,4,1)+struct.pack('<I',7)+b'\0'
        for bad in [b'bad',b'WDB2'+valid[4:],valid[:-1],valid+b'junk',valid[:-1]+b'x']:
            with self.assertRaises(ValueError):DBC(bad)
        packed=DBC(struct.pack('<4s4I',b'WDBC',1,2,5,1)+b'12345\0')
        self.assertEqual(packed.metadata()['record_bytes'],5)
        with self.assertRaisesRegex(ValueError,'schema'):packed.cell(0,0)
        invalid=DBC(struct.pack('<4s4I',b'WDBC',1,1,4,3)+struct.pack('<I',1)+b'\0\xff\0')
        with self.assertRaisesRegex(ValueError,'UTF-8'):invalid.cell(0,0,'string')

    def test_coverage_reports_missing_tables_without_inventing_client_build(self):
        coverage=appearance_coverage(['dbfilesclient/CreatureDisplayInfo.dbc','dbfilesclient/CreatureModelData.dbc'])
        self.assertEqual(coverage['creatures']['missing'],[])
        self.assertIn('itemdisplayinfo.dbc',coverage['equipment']['missing'])
