"""Import the PNG export without executing or trusting archive paths."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
from PIL import Image
import io

MAX_BYTES = 512 * 1024 * 1024


def import_zip(source, destination):
    destination = Path(destination)
    records = []
    # Validate everything before creating any imported files.
    pending = []
    total = 0
    with ZipFile(source) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = member.filename.replace('\\', '/')
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or any(':' in p for p in path.parts):
                raise ValueError(f'Unsafe ZIP path: {name}')
            if path.suffix.lower() != '.png':
                continue
            total += member.file_size
            if total > MAX_BYTES:
                raise ValueError('PNG archive exceeds 512 MiB uncompressed')
            data = archive.read(member)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.format != 'PNG':
                    raise ValueError(f'Not a PNG: {name}')
                size = list(image.size)
            digest = hashlib.sha256(data).hexdigest()
            # Content addresses prevent path collisions and make IDs persistent.
            target = f'files/{digest}.png'
            lower = name.lower()
            category = ('terrain' if '/tileset/' in lower else
                        'worldmap' if '/worldmap/' in lower else 'model_texture')
            record = dict(id='png:' + digest, source=name, file=target,
                          name=path.stem, category=category, size=size,
                          auxiliary=path.stem.lower().endswith('_s'))
            pending.append((target, data))
            records.append(record)
    if not records:
        raise ValueError('No PNG files found')
    destination.mkdir(parents=True, exist_ok=True)
    for target, data in pending:
        out = destination / target
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    catalog = dict(version=1, records=records)
    # Merge imports so later asset packs do not erase earlier entries.
    old = destination / 'catalog.json'
    if old.exists():
        previous = json.loads(old.read_text(encoding='utf-8'))['records']
        combined = {(r['source'], r['id']): r for r in previous + records}
        catalog['records'] = sorted(combined.values(), key=lambda r: (r['source'], r['id']))
    old.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
    return catalog


class Assets:
    def __init__(self, root):
        self.root = Path(root)
        self.records = json.loads((self.root / 'catalog.json').read_text(encoding='utf-8'))['records']

    def resolve(self, selector):
        matches = [r for r in self.records if r['id'] == selector or r['source'] == selector]
        if not matches:
            raise ValueError(f'Asset not found: {selector}')
        if len({r['id'] for r in matches}) != 1:
            raise ValueError(f'Ambiguous asset selector: {selector}')
        path = (self.root / matches[0]['file']).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError('Asset path escapes catalog directory')
        return path
