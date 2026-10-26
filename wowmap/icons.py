"""Resolve explicitly selected WoW icons from a private graphics export.

No network access and no automatic guesses: search names, choose an exact icon,
verify its original bytes, and package a lossless WebP under a content hash.
"""
import argparse
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile
from PIL import Image

PREFIX = 'wowmap/content/icons/'
MAX_ICON_BYTES = 4 * 1024 * 1024


def relative_file(root, name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Expected a relative resource path')
    parts = PurePosixPath(name)
    if parts.is_absolute() or '..' in parts.parts or ':' in name:
        raise ValueError('Unsafe resource path')
    target = (Path(root) / name).resolve()
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError('Resource lies outside its asset folder')
    return target


class IconAssets:
    def __init__(self, root):
        self.root = Path(root).resolve()
        catalog = self.root / 'catalog.jsonl.gz'
        self.records = {}
        self.names = {}
        self.images = {}
        self.media = {}
        self.selected = {}
        with gzip.open(catalog, 'rb') as stream:
            content = stream.read(64 * 1024 * 1024 + 1)
        if len(content) > 64 * 1024 * 1024:
            raise ValueError('Icon catalog exceeds 64 MiB uncompressed')
        for line in content.decode('utf-8-sig').splitlines():
            record = json.loads(line)
            path = record['path']
            if not path.startswith('interface/icons/'):
                continue
            relative_file(self.root, path)
            if PurePosixPath(path).suffix.lower() not in ('.blp', '.png', '.dds', '.tga'):
                continue
            key = path.lower()
            if key in self.records:
                raise ValueError('Duplicate icon path in catalog')
            self.records[key] = record
            self.names.setdefault(PurePosixPath(key).stem, []).append(key)
        if not self.records:
            raise ValueError('No Interface/Icons images in asset catalog')

    def search(self, query, limit=30):
        if not isinstance(query, str) or not query.strip() or not 1 <= limit <= 100:
            raise ValueError('Search needs text and a limit from 1 to 100')
        words = query.lower().split()
        matches = [p for p in sorted(self.records) if all(word in p for word in words)]
        return dict(matches=len(matches), paths=matches[:limit])

    def resolve(self, name):
        if not isinstance(name, str) or not name:
            raise ValueError('Icon name is required')
        name = name.replace('\\', '/').lower()
        if name.startswith('interface/icons/'):
            matches = [name] if name in self.records else []
        elif '/' not in name:
            if PurePosixPath(name).suffix:
                full = 'interface/icons/' + name
                matches = [full] if full in self.records else []
            else:
                matches = self.names.get(name, [])
        else:
            matches = []
        if len(matches) != 1:
            raise ValueError(f'Icon must resolve exactly once: {name} ({len(matches)} matches)')
        return matches[0]

    def select(self, name):
        key = self.resolve(name)
        if key in self.selected:
            return self.selected[key]
        if len(self.selected) >= 2000:
            raise ValueError('At most 2000 selected icons per build')
        record = self.records[key]
        package = relative_file(self.root, record['package'])
        # Drive uploads sometimes flatten the packages/ directory. Both layouts work.
        if not package.is_file() and PurePosixPath(record['package']).parts[:1] == ('packages',):
            package = relative_file(self.root, PurePosixPath(record['package']).name)
        with ZipFile(package) as archive:
            info = archive.getinfo(record['member'])
            if info.file_size > MAX_ICON_BYTES:
                raise ValueError('Icon exceeds 4 MiB')
            raw = archive.read(info)
        if len(raw) != record['size'] or 'raw:' + hashlib.sha256(raw).hexdigest() != record['id']:
            raise ValueError(f'Icon checksum mismatch: {key}')
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > 1024 * 1024:
                raise ValueError('Icon exceeds one megapixel')
            source.load()
            buffer = io.BytesIO()
            source.convert('RGBA').save(buffer, format='WEBP', lossless=True, exact=True)
        data = buffer.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        path = PREFIX + digest + '.webp'
        self.images[path] = data
        row = self.media.setdefault(path, dict(file=path, sha256=digest, bytes=len(data), sources=[]))
        row['sources'].append(dict(path=record['path'], id=record['id']))
        self.selected[key] = path
        return path

    def bind(self, document, bindings):
        """Apply JSON pointers to image fields only, including nested NPC items."""
        if not isinstance(bindings, dict) or len(bindings) > 2000:
            raise ValueError('icons must map JSON pointers to exact icon names')
        result = copy.deepcopy(document)
        for pointer, icon in bindings.items():
            if not isinstance(pointer, str) or not pointer.startswith('/') or re.search(r'~(?![01])', pointer):
                raise ValueError('Icon target must be a JSON pointer')
            tokens = [s.replace('~1', '/').replace('~0', '~') for s in pointer[1:].split('/')]
            if tokens[-1] != 'img' and tokens[-2:] != ['texture', 'src']:
                raise ValueError('Icons can target only img or texture/src fields')
            parent = result
            for token in tokens[:-1]:
                if isinstance(parent, list):
                    if not re.fullmatch(r'0|[1-9][0-9]*', token) or int(token) >= len(parent):
                        raise ValueError('Icon target array index does not exist')
                    parent = parent[int(token)]
                elif isinstance(parent, dict) and token in parent:
                    parent = parent[token]
                else:
                    raise ValueError('Icon target does not exist')
            if not isinstance(parent, dict):
                raise ValueError('Icon target must be an image property')
            parent[tokens[-1]] = self.select(icon)
        return result

    def write(self, root):
        for path, data in self.images.items():
            target = relative_file(root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description='Search exported WoW icon filenames')
    parser.add_argument('--assets', required=True, help='Folder containing catalog.jsonl.gz and ZIP packages')
    parser.add_argument('--query', required=True, help='English filename words, e.g. fire or inv_misc_key')
    parser.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()
    try:
        print(json.dumps(IconAssets(args.assets).search(args.query, args.limit), indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'ERROR: {error}\n')


if __name__ == '__main__':
    main()
