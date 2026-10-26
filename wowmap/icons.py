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
import textwrap
from zipfile import ZipFile
from PIL import Image, ImageDraw, ImageFont

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
        self.bindings = []
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
            self.bindings.append(dict(pointer=pointer, name=parent.get('name', pointer),
                                      icon=self.resolve(icon), file=parent[tokens[-1]]))
        return result

    def bind_items(self, document, bindings):
        """Bind embedded item icons by their exact system.identifier, never list order."""
        if not isinstance(bindings, dict) or len(bindings) > 2000:
            raise ValueError('item_icons must map item identifiers to exact icon names')
        pointers = {}
        for identifier, icon in bindings.items():
            if not isinstance(identifier, str) or not identifier:
                raise ValueError('Item icon identifier must be nonempty text')
            matches = [i for i, item in enumerate(document.get('items', []))
                       if item.get('system', {}).get('identifier') == identifier]
            if len(matches) != 1:
                raise ValueError(f'Item icon identifier must resolve exactly once: {identifier} ({len(matches)} matches)')
            pointers[f'/items/{matches[0]}/img'] = icon
        return self.bind(document, pointers)

    def review(self, root, rows, stem='icon-review'):
        """Paginated contact sheets of actual selected pixels, for human review only."""
        root = Path(root)
        if not re.fullmatch(r'[a-z0-9-]+', stem):
            raise ValueError('Review filename must be an ASCII slug')
        font = None
        for name in ('DejaVuSans.ttf', 'arial.ttf'):
            try:
                font = ImageFont.truetype(name, 14)
                break
            except OSError:
                pass
        if font is None:
            font = ImageFont.load_default(size=14)
        files = []
        for start in range(0, len(rows), 24):
            page = rows[start:start + 24]
            image = Image.new('RGB', (1000, ((len(page) + 3) // 4) * 190), '#20252d')
            draw = ImageDraw.Draw(image)
            for index, row in enumerate(page):
                x, y = (index % 4) * 250, (index // 4) * 190
                with Image.open(io.BytesIO(self.images[row['file']])) as source:
                    icon = source.convert('RGBA')
                    icon.thumbnail((80, 80), Image.Resampling.NEAREST)
                    image.paste(icon, (x + (250 - icon.width) // 2, y + 8), icon)
                label = row.get('document', '')
                lines = [label[:29]] if label else []
                lines += textwrap.wrap(str(row['name']), 28)[:2]
                lines += textwrap.wrap(PurePosixPath(row['icon']).stem, 28)[:2]
                draw.multiline_text((x + 8, y + 94), '\n'.join(lines), fill='white', font=font, spacing=2)
            path = root / f'{stem}-{start // 24 + 1:03}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path)
            files.append(path.name)
        return files

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
    parser.add_argument('--preview-dir', help='Also render matching icons with filenames for visual selection')
    args = parser.parse_args()
    try:
        icons = IconAssets(args.assets)
        result = icons.search(args.query, args.limit)
        if args.preview_dir:
            rows = [dict(name=PurePosixPath(p).stem, icon=p, file=icons.select(p)) for p in result['paths']]
            result['previews'] = icons.review(args.preview_dir, rows)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'ERROR: {error}\n')


if __name__ == '__main__':
    main()
