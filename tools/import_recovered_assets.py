"""Validate a private recovery ZIP and add its new resources to RawAssets packages."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED


def import_recovery(source, manifest_path, packages, catalog=None):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    source = Path(source)
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['source_zip_sha256']:
        raise ValueError('Recovery ZIP SHA-256 does not match the manifest')
    content = {}
    with ZipFile(source) as archive:
        if archive.testzip():
            raise ValueError('Corrupt recovery ZIP')
        for row in manifest['files']:
            path = row['path']
            if path.startswith('/') or any(p in ('', '.', '..') or ':' in p for p in path.split('/')):
                raise ValueError('Unsafe virtual path')
            data = archive.read(row['member'])
            if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Resource hash mismatch: ' + path)
            if row['action'] == 'add':
                content[path] = data
    packages = Path(packages)
    packages.mkdir(parents=True, exist_ok=True)
    target = packages / manifest['package']
    # Never put a second copy under a path already owned by another package.
    for other in packages.glob('*.zip'):
        if other == target:
            continue
        with ZipFile(other) as archive:
            overlap = set(content) & {i.filename.replace('\\', '/').lower() for i in archive.infolist()}
            if overlap:
                raise ValueError('Already packaged elsewhere: ' + ', '.join(sorted(overlap)))
    records = None
    if catalog:
        with gzip.open(catalog, 'rt', encoding='utf-8') as stream:
            records = {r['path']: r for r in map(json.loads, stream)}
        for row in manifest['files']:
            if row['action'] != 'add':
                continue
            path = row['path']
            if path in records and records[path]['id'] != 'raw:' + row['sha256']:
                raise ValueError('Catalog hash conflict: ' + path)
            records[path] = dict(path=path, id='raw:' + row['sha256'], size=row['size'],
                                 archive=row['source_mpq'], group='interface/glues/models',
                                 package='packages/' + target.name, member=path, locale=1049)
    # All input validation is complete before writing the independent package.
    with tempfile.TemporaryDirectory(dir=packages) as temporary:
        staged = Path(temporary) / target.name
        with ZipFile(staged, 'w', ZIP_DEFLATED) as archive:
            for path, data in sorted(content.items()):
                archive.writestr(path, data)
        staged.replace(target)
        if records is not None:
            staged_catalog = Path(temporary) / 'catalog.jsonl.gz'
            with gzip.open(staged_catalog, 'wt', encoding='utf-8') as stream:
                for row in sorted(records.values(), key=lambda r: r['path']):
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            staged_catalog.replace(catalog)
    return {'package': str(target), 'added': sorted(content), 'verified_files': len(manifest['files'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--packages', required=True)
    parser.add_argument('--catalog')
    args = parser.parse_args()
    print(json.dumps(import_recovery(args.source, args.manifest, args.packages, args.catalog), indent=2))
