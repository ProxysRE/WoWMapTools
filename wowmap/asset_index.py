"""Optional local ZIP directory index: lazy handles, no decompressed asset copies.

Rebuild explicitly after changing the package set. A stale/corrupt index is
ignored by RawAssets, which falls back to the original central-directory scan.
"""
import argparse,json,os,sqlite3,tempfile
from collections.abc import Mapping
from pathlib import Path
from zipfile import ZipFile
from .pack import normalize

FORMAT='wowmap.asset-index/1'
FILENAME='asset-index.sqlite'


def package_paths(folder):
    folder=Path(folder)
    return sorted([*folder.glob('*.zip'),*(folder/'packages').glob('*.zip')])


def manifest(folder):
    folder=Path(folder)
    return {str(p.relative_to(folder)).replace('\\','/'):(p,p.stat().st_size,p.stat().st_mtime_ns) for p in package_paths(folder)}


def build_index(folder):
    folder=Path(folder).resolve();files=manifest(folder)
    if not files:raise ValueError('No resource ZIP packages found')
    fd,name=tempfile.mkstemp(prefix='asset-index-',suffix='.tmp',dir=folder);os.close(fd);tmp=Path(name)
    connection=None
    try:
        connection=sqlite3.connect(tmp)
        connection.executescript('''
          CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE archives(path TEXT PRIMARY KEY,bytes INTEGER,mtime_ns INTEGER);
          CREATE TABLE resources(path TEXT PRIMARY KEY,archive TEXT,member TEXT,bytes INTEGER) WITHOUT ROWID;
        ''')
        count=0
        for rel,(path,size,mtime) in files.items():
            connection.execute('INSERT INTO archives VALUES(?,?,?)',(rel,size,mtime))
            rows=[]
            with ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir():continue
                    if info.file_size>256*1024*1024:raise ValueError('Resource exceeds 256 MiB: '+info.filename)
                    rows.append((normalize(info.filename),rel,info.filename,info.file_size))
            try:connection.executemany('INSERT INTO resources VALUES(?,?,?,?)',rows)
            except sqlite3.IntegrityError as error:raise ValueError('Duplicate virtual resource in ZIP set') from error
            count+=len(rows)
        if {k:(v[1],v[2]) for k,v in files.items()}!={k:(v[1],v[2]) for k,v in manifest(folder).items()}:
            raise ValueError('ZIP packages changed while indexing')
        connection.executemany('INSERT INTO metadata VALUES(?,?)',[('format',FORMAT),('resources',str(count))]);connection.commit();connection.close();connection=None
        target=folder/FILENAME;tmp.replace(target)
        return dict(path=str(target),archives=len(files),resources=count,bytes=target.stat().st_size)
    finally:
        if connection is not None:connection.close()
        tmp.unlink(missing_ok=True)


class IndexedFiles(Mapping):
    """Compatibility mapping; opening a resource's archive is lazy and bounded
    by the number of distinct archives actually used in the operation."""
    def __init__(self,connection,files,owner,count):
        self.connection=connection;self.paths=files;self.owner=owner;self.count=count;self.opened={}

    def __len__(self):return self.count
    def __iter__(self):
        for row in self.connection.execute('SELECT path FROM resources ORDER BY path'):yield row[0]
    def __contains__(self,key):
        return self.connection.execute('SELECT 1 FROM resources WHERE path=?',(key,)).fetchone() is not None
    def __getitem__(self,key):
        row=self.connection.execute('SELECT archive,member,bytes FROM resources WHERE path=?',(key,)).fetchone()
        if row is None:raise KeyError(key)
        rel,member,size=row
        if rel not in self.paths:raise ValueError('Asset index references an unknown ZIP')
        if rel not in self.opened:
            archive=ZipFile(self.paths[rel][0]);self.opened[rel]=archive;self.owner.archives.append(archive)
        archive=self.opened[rel];info=archive.getinfo(member)
        if normalize(info.filename)!=key or info.file_size!=size:raise ValueError('Asset index resource differs from archive')
        if info.file_size>256*1024*1024:raise ValueError('Resource exceeds 256 MiB: '+key)
        return archive,info


def open_index(folder,owner):
    folder=Path(folder);path=folder/FILENAME
    if not path.is_file():return None,None
    connection=None
    try:
        # URI encoding avoids interpreting literal ?/# characters in a path.
        connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        meta=dict(connection.execute('SELECT key,value FROM metadata'))
        if meta.get('format')!=FORMAT:raise ValueError('Unknown index format')
        files=manifest(folder)
        current={k:(v[1],v[2]) for k,v in files.items()}
        recorded={r[0]:(r[1],r[2]) for r in connection.execute('SELECT path,bytes,mtime_ns FROM archives')}
        if current!=recorded:raise ValueError('Stale ZIP index')
        count=int(meta['resources'])
        if count<=0 or count!=connection.execute('SELECT count(*) FROM resources').fetchone()[0]:raise ValueError('Invalid resource index size')
        return connection,IndexedFiles(connection,files,owner,count)
    except (OSError,sqlite3.Error,ValueError,KeyError):
        if connection is not None:connection.close()
        return None,None


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--packages',required=True);args=parser.parse_args()
    try:print(json.dumps(build_index(args.packages)))
    except (OSError,ValueError,sqlite3.Error) as error:parser.exit(1,f'ERROR: {error}\n')


if __name__=='__main__':main()
