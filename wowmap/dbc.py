"""Bounded reader for original WDBC files; field meanings require a build schema.

Header reference: TrinityCore common/DataStores/DBCFileLoader.cpp (3.3.5).
This reader deliberately does not guess a table's build or column meanings.
"""
import argparse
import json
from pathlib import Path
import struct


APPEARANCE_TABLES = {
    'creatures': ('creaturedisplayinfo', 'creaturemodeldata'),
    'humanoids': ('creaturedisplayinfoextra', 'chrraces', 'charsections',
                  'charhairgeosets', 'characterfacialhairstyles'),
    'equipment': ('item', 'itemdisplayinfo', 'helmetgeosetvisdata',
                  'itemvisuals', 'itemvisualeffects'),
    'animations': ('animationdata',),
    'icons': ('spellicon',),
}


class DBC:
    def __init__(self, data):
        if len(data) < 20 or data[:4] != b'WDBC':
            raise ValueError('Expected original WDBC table, not DB2/CSV or a patch blob')
        self.data = data
        self.records, self.fields, self.record_size, self.string_bytes = struct.unpack_from('<4I', data, 4)
        if not 1 <= self.fields <= 4096 or not 1 <= self.record_size <= 65536:
            raise ValueError('Invalid DBC field count or record size')
        self.string_start = 20 + self.records * self.record_size
        if self.string_start + self.string_bytes != len(data):
            raise ValueError('DBC size does not match records and string block')
        if self.string_bytes and data[-1] != 0:
            raise ValueError('DBC string block is not NUL terminated')

    def metadata(self):
        return dict(format='WDBC', records=self.records, fields=self.fields,
                    record_bytes=self.record_size, string_bytes=self.string_bytes,
                    bytes=len(self.data))

    def cell(self, row, column, kind='uint32'):
        if self.record_size != self.fields * 4:
            raise ValueError('Column access requires an explicit schema for packed DBC records')
        if not 0 <= row < self.records or not 0 <= column < self.fields:
            raise ValueError('DBC row or column outside table')
        formats={'uint32':'I', 'int32':'i', 'float32':'f', 'string':'I'}
        if kind not in formats:
            raise ValueError('Unsupported DBC cell type')
        value=struct.unpack_from('<'+formats[kind],self.data,20+row*self.record_size+column*4)[0]
        if kind != 'string':
            return value
        if value >= self.string_bytes:
            raise ValueError('DBC string offset outside string block')
        start=self.string_start+value
        end=self.data.find(b'\0',start)
        if end < 0:
            raise ValueError('Unterminated DBC string')
        try:
            return self.data[start:end].decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('DBC string is not valid UTF-8') from error


def appearance_coverage(paths):
    names={Path(p).stem.lower() for p in paths}
    return {group:dict(present=[name+'.dbc' for name in tables if name in names],
                       missing=[name+'.dbc' for name in tables if name not in names])
            for group,tables in APPEARANCE_TABLES.items()}


def main():
    parser=argparse.ArgumentParser(description='Inspect an original WDBC table without guessing its schema')
    parser.add_argument('file')
    args=parser.parse_args()
    try:
        path=Path(args.file)
        if path.stat().st_size > 256*1024*1024:
            raise ValueError('DBC exceeds 256 MiB')
        print(json.dumps(DBC(path.read_bytes()).metadata(),indent=2))
    except (ValueError,OSError) as error:
        parser.exit(1,f'ERROR: {error}\n')


if __name__ == '__main__':
    main()
