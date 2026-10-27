"""Build independent raw-asset ZIPs and a searchable catalog for Drive.

Does not upload, execute client code, or modify source MPQs.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import ZipFile, ZipInfo, ZIP_STORED
from PIL import Image, ImageDraw
from .mpq import Storm, PATCH_FILE, DELETE_MARKER

ARCHIVES = ('common.mpq', 'common-2.mpq', 'expansion.mpq', 'lichking.mpq',
            'patch.mpq', 'patch-2.mpq', 'patch-3.mpq')
GRAPHICS = {'.blp', '.png', '.dds', '.tga', '.m2', '.mdx', '.skin', '.anim',
            '.wmo', '.adt', '.wdt', '.wdl', '.dbc'}
SCHEMA = 'wowmap.drive-bundle/1'
ICON_EXTENSIONS = {'.blp', '.png', '.dds', '.tga'}


def archive_order(data_root, profile='graphics', locale=None):
    """Return relative paths, keeping localized and root patch generations aligned."""
    if profile not in ('graphics', 'icons', 'dbc'):
        raise ValueError('Unknown export profile')
    available = {p.name.lower(): p.name for p in data_root.iterdir()
                 if p.is_file() and p.suffix.lower() == '.mpq'}
    if not any(name in available for name in ARCHIVES):
        raise ValueError('No standard WotLK MPQ archives found in this directory')
    if profile == 'graphics':
        if locale:
            raise ValueError('--locale is supported only with --profile icons or dbc')
        return [available[n] for n in ARCHIVES if n in available]
    languages = {}
    for folder in sorted(data_root.iterdir()):
        if not folder.is_dir() or not re.fullmatch(r'[a-zA-Z]{4}', folder.name):
            continue
        code = folder.name.lower()
        names = {p.name.lower(): p for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() == '.mpq'}
        chain = [f'locale-{code}.mpq', f'expansion-locale-{code}.mpq',
                 f'lichking-locale-{code}.mpq', f'patch-{code}.mpq',
                 f'patch-{code}-2.mpq', f'patch-{code}-3.mpq']
        selected = [names[n].relative_to(data_root).as_posix() for n in chain if n in names]
        if selected:
            languages[code] = selected
    if locale:
        if locale.lower() not in languages:
            raise ValueError('No standard locale archives for requested language; found: '
                             + ', '.join(languages))
        localized = languages[locale.lower()]
    elif len(languages) > 1:
        raise ValueError('Multiple client languages found: ' + ', '.join(languages)
                         + '. Choose one with --locale (for example --locale ruRU).')
    else:
        localized = next(iter(languages.values()), [])
    result = [available[n] for n in ARCHIVES[:4] if n in available]
    result.extend(n for n in localized if not Path(n).name.lower().startswith('patch-'))
    for root_patch in ARCHIVES[4:]:
        if root_patch in available:
            result.append(available[root_patch])
        suffix = root_patch.removeprefix('patch').removesuffix('.mpq')
        result.extend(n for n in localized
                      if re.fullmatch(r'patch-[a-z]{4}' + re.escape(suffix) + r'\.mpq',
                                      Path(n).name.lower()))
    return result


def json_write(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def normalize(name):
    name = name.replace('\\', '/').lower()
    # Equivalent to PurePosixPath for virtual resources, without constructing
    # thousands of pathlib objects while indexing a client package.
    parts = name.split('/')
    if name.startswith('/') or '..' in parts or ':' in name:
        raise ValueError('Unsafe resource path')
    return '/'.join(part for part in parts if part and part != '.') or '.'


def group_for(path):
    parts = PurePosixPath(path).parts
    if parts[0] == 'tileset' and len(parts) > 2:
        return '/'.join(parts[:2])
    if parts[0] == 'world' and len(parts) > 3:
        return '/'.join(parts[:3])
    if len(parts) > 2:
        return '/'.join(parts[:2])
    return parts[0]


def scan(data_root, storm, listfile=None, progress=print, profile='graphics', locale=None):
    data_root = Path(data_root)
    if not data_root.is_dir():
        raise ValueError('Choose an existing client Data directory')
    available = {p.name.lower(): p for p in data_root.iterdir() if p.is_file() and p.suffix.lower() == '.mpq'}
    ordered = archive_order(data_root, profile, locale)
    effective = {}
    stats = []
    warnings = []
    warnings.extend(f'Standard archive missing: {n}' for n in ARCHIVES if n not in available)
    if profile in ('icons', 'dbc') and not any('/' in n for n in ordered):
        warnings.append('No standard locale archives found; searched root archives only')
    for relative_name in ordered:
        source = data_root / relative_name
        progress(f'Indexing {relative_name} ...', flush=True)
        named = unnamed = selected = 0
        with storm.open(source) as archive:
            for item in archive.entries(listfile):
                original = item['path']
                if re.fullmatch(r'File[0-9a-fA-F]{8}(?:\..*)?', original, re.IGNORECASE):
                    unnamed += 1
                    continue
                try:
                    path = normalize(original)
                except ValueError:
                    unnamed += 1
                    continue
                named += 1
                if PurePosixPath(path).suffix not in GRAPHICS:
                    continue
                if profile == 'icons' and (not path.startswith('interface/icons/')
                                          or PurePosixPath(path).suffix not in ICON_EXTENSIONS):
                    continue
                if profile == 'dbc' and (not path.startswith('dbfilesclient/') or not path.endswith('.dbc')):
                    continue
                # Root archives normally use neutral locale. Prefer that version if both exist.
                existing = effective.get(path)
                if existing and existing['archive'] == relative_name and existing['locale'] == 0 and item['locale'] != 0:
                    continue
                effective[path] = dict(path=path, original=original, archive=relative_name,
                                       size=item['size'], flags=item['flags'], locale=item['locale'])
                selected += 1
        stat = source.stat()
        stats.append(dict(name=relative_name, bytes=stat.st_size, modified_ns=stat.st_mtime_ns,
                          named=named, unnamed=unnamed, graphics_entries=selected))
        if unnamed:
            warnings.append(f'{relative_name}: {unnamed} unnamed entries; an external listfile may improve coverage')
    ignored = [p.name for key,p in available.items() if key not in ARCHIVES]
    if ignored:
        warnings.append('Unrecognized/custom root archives not used: ' + ', '.join(sorted(ignored)))
    # General graphics retains the original root-only export scope.
    deleted = [path for path,item in effective.items() if item['flags'] & DELETE_MARKER]
    for path in deleted:
        del effective[path]
    delta = [path for path,item in effective.items() if item['flags'] & PATCH_FILE]
    if delta:
        raise ValueError(f'{len(delta)} delta-patched graphics resources found. This version refuses to export patch blobs as models/textures.')
    return effective, stats, warnings


def write_parts(group, entries, handles, upload, part_bytes, validate_dbc=False):
    slug = re.sub(r'[^a-z0-9_-]', '-', group)[:72]
    slug += '-' + hashlib.sha256(group.encode()).hexdigest()[:8]
    records, parts, tables = [], [], []
    zip_handle = None
    temporary = None
    size = 0
    part_number = 0
    current_file = None

    def finish():
        nonlocal zip_handle, temporary
        if zip_handle:
            zip_handle.close(); zip_handle = None
            target = upload / current_file
            temporary.replace(target)
            temporary = None
            parts.append(dict(file=current_file, bytes=target.stat().st_size, sha256=digest_file(target)))

    try:
        for entry in entries:
            content = handles[entry['archive']].read(entry['original'], entry['locale'])
            if validate_dbc:
                from .dbc import DBC
                try:
                    tables.append(dict(path=entry['path'],**DBC(content).metadata()))
                except ValueError as error:
                    raise ValueError(f"Invalid DBC {entry['path']}: {error}") from error
            # Conservative room for local header + central directory, including UTF-8 names.
            overhead = 256 + 2 * len(entry['path'].encode('utf-8'))
            if zip_handle and size + len(content) + overhead > part_bytes:
                finish()
            if zip_handle is None:
                part_number += 1
                current_file = f'packages/{slug}-{part_number:03d}.zip'
                temporary = (upload / current_file).with_suffix('.zip.tmp')
                zip_handle = ZipFile(temporary, 'w', compression=ZIP_STORED, allowZip64=True)
                size = 22
            info = ZipInfo(entry['path'], date_time=(1980,1,1,0,0,0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o100644 << 16
            zip_handle.writestr(info, content)
            size += len(content) + overhead
            records.append(dict(path=entry['path'], id='raw:' + hashlib.sha256(content).hexdigest(),
                                size=len(content), archive=entry['archive'], group=group,
                                package=current_file, member=entry['path'], locale=entry['locale']))
        finish()
    finally:
        if zip_handle:
            zip_handle.close()
        if temporary and temporary.exists():
            temporary.unlink()
    result=dict(group=group, records=records, packages=parts)
    if validate_dbc:result['tables']=tables
    return result


def previews(upload, records, max_zones=64, per_zone=8):
    """Small terrain contact sheets, read from finished packages, not source MPQs."""
    groups = defaultdict(list)
    for record in records:
        path = record['path']
        if path.startswith('tileset/') and path.endswith(('.blp','.png')) and not PurePosixPath(path).stem.endswith('_s'):
            groups[record['group']].append(record)
    failures, sheets = [], []
    for group, choices in sorted(groups.items())[:max_zones]:
        chosen = sorted(choices,key=lambda r:r['path'])[:per_zone]
        sheet = Image.new('RGB',(800,((len(chosen)+3)//4)*160),'#252525')
        draw = ImageDraw.Draw(sheet)
        for index, record in enumerate(chosen):
            x,y=(index%4)*200,(index//4)*160
            try:
                with ZipFile(upload / record['package']) as archive:
                    raw = archive.read(record['member'])
                with Image.open(io.BytesIO(raw)) as image:
                    image.load(); image.thumbnail((125,125))
                    sheet.paste(image.convert('RGB'),(x,y))
                draw.text((x,y+130),PurePosixPath(record['path']).name[:30],fill='white')
            except Exception:
                failures.append(record['path'])
                draw.text((x,y+30),'Preview unavailable',fill='orange')
        name='previews/' + group.replace('/','-') + '.jpg'
        sheet.save(upload/name,quality=85)
        sheets.append(dict(group=group,file=name))
    return dict(sheets=sheets, failed=failures, zones_total=len(groups),
                zones_previewed=min(len(groups),max_zones), samples_per_zone=per_zone)


def build(data_root, output, storm=None, part_mib=128, listfile=None, index_only=False,
          progress=print, profile='graphics', locale=None):
    if not 8 <= part_mib <= 1024:
        raise ValueError('part-mib must be between 8 and 1024')
    output = Path(output).resolve()
    data_root = Path(data_root).resolve()
    if output == data_root or output.is_relative_to(data_root):
        raise ValueError('Choose an output folder outside the client Data directory')
    storm = storm or Storm()
    effective, archives, warnings = scan(data_root,storm,listfile,progress,profile,locale)
    if not effective:
        # A separate diagnostic survives even when there is nothing to package.
        output.mkdir(parents=True,exist_ok=True)
        json_write(output/'scan-diagnostic.json',dict(status='no_resources',profile=profile,
                   archive_order=archives,warnings=warnings))
        raise ValueError('No matching named resources found. See scan-diagnostic.json; '
                         'an external --listfile may improve coverage.')
    # No absolute client paths are recorded in uploadable metadata.
    signature = hashlib.sha256(json.dumps(dict(archives=archives,part_mib=part_mib,
                                              listfile_sha256=digest_file(listfile) if listfile else None,
                                              schema=SCHEMA,packer_version='0.2.2',
                                              profile=profile,locale=locale),sort_keys=True).encode()).hexdigest()
    output.mkdir(parents=True,exist_ok=True)
    work=output/'work'; upload=output/'upload'
    work.mkdir(exist_ok=True); upload.mkdir(exist_ok=True)
    (upload/'packages').mkdir(exist_ok=True); (upload/'previews').mkdir(exist_ok=True)
    state_file=work/'source.json'
    if state_file.exists() and json.loads(state_file.read_text(encoding='utf-8'))['signature'] != signature:
        raise ValueError('Source archives or settings changed; choose a new output directory')
    json_write(state_file,dict(signature=signature))
    with gzip.open(upload/'inventory.jsonl.gz','wt',encoding='utf-8') as stream:
        for path in sorted(effective):
            stream.write(json.dumps(effective[path],ensure_ascii=False)+'\n')
    total_bytes=sum(entry['size'] for entry in effective.values())
    report=dict(format=SCHEMA,status='indexed',signature=signature,archive_order=archives,
                resources=len(effective),estimated_raw_bytes=total_bytes,warnings=warnings,
                profile=profile,
                coverage=('named Interface/Icons images in standard root and selected locale archives'
                          if profile == 'icons' else 'named DBFilesClient/*.dbc in standard root and selected locale archives'
                          if profile == 'dbc' else 'named root-archive graphics only; not a complete client backup'),
                locale_archives_included=any('/' in a['name'] for a in archives),
                custom_archives_included=False)
    json_write(upload/'summary.json',report)
    progress(f'Found {len(effective)} resources; raw size approx {total_bytes/1024**3:.2f} GiB',flush=True)
    if index_only:
        return report
    groups=defaultdict(list)
    for path,entry in sorted(effective.items()):
        groups[group_for(path)].append(entry)
    records=[]; packages=[]; tables=[]; completed_groups=0
    report['status']='packing';json_write(upload/'summary.json',report)
    try:
        with ExitStack() as stack:
            handles={a['name']:stack.enter_context(storm.open(data_root/a['name'])) for a in archives}
            for index,(group,entries) in enumerate(sorted(groups.items()),1):
                checkpoint=work/(hashlib.sha256(group.encode()).hexdigest()+'.json')
                result=None
                if checkpoint.exists():
                    candidate=json.loads(checkpoint.read_text(encoding='utf-8'))
                    if all((upload/p['file']).is_file() and digest_file(upload/p['file'])==p['sha256'] for p in candidate['packages']):
                        result=candidate
                if result is None:
                    progress(f'[{index}/{len(groups)}] Packing {group}: {len(entries)} resources',flush=True)
                    result=write_parts(group,entries,handles,upload,part_mib*1024*1024,validate_dbc=profile=='dbc')
                    json_write(checkpoint,result)
                else:
                    progress(f'[{index}/{len(groups)}] Reusing {group}',flush=True)
                records.extend(result['records']);packages.extend(result['packages']);completed_groups += 1
                tables.extend(result.get('tables',[]))
        with gzip.open(upload/'catalog.jsonl.gz','wt',encoding='utf-8') as stream:
            for record in records:
                stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        preview_report=previews(upload,records)
        if profile == 'dbc':
            from .dbc import appearance_coverage
            coverage=appearance_coverage(r['path'] for r in records)
            json_write(upload/'dbc-report.json',dict(format='wowmap.dbc-report/1',tables=tables,
                       appearance_tables=coverage,client_build='not inferred from WDBC header'))
            report['dbc_report']='dbc-report.json'
            report['appearance_tables']=coverage
            missing=[name for group in coverage.values() for name in group['missing']]
            if missing:warnings.append('Appearance support tables missing: '+', '.join(missing))
        report.update(status='complete',packages=packages,preview=preview_report,
                      extensions=dict(Counter(PurePosixPath(r['path']).suffix for r in records)),
                      groups=[dict(group=g,resources=len(v)) for g,v in sorted(groups.items())],
                      actual_package_bytes=sum(p['bytes'] for p in packages),
                      oversized_packages=[p['file'] for p in packages if p['bytes']>part_mib*1024*1024])
        (upload/'READ_ME.txt').write_text(
            f'WoWMapTools raw resource bundle (profile: {profile})\nUpload this folder to your private Drive.\n'
            'summary.json: package hashes and status. catalog.jsonl.gz: resource -> ZIP lookup.\n'
            'Each ZIP is independent; paths are preserved and lowercased. No game executable or audio.\n'
            'This is not a complete client backup. See warnings and coverage in summary.json.\n'
            'Models are raw WoW formats, not top-down sprites.\n',encoding='utf-8')
    except (Exception,KeyboardInterrupt) as error:
        report.update(status='interrupted' if isinstance(error,KeyboardInterrupt) else 'failed',
                      error_type=type(error).__name__,completed_groups=completed_groups)
        json_write(upload/'summary.json',report)
        raise
    json_write(upload/'summary.json',report)
    progress('Done. Upload ONLY the upload folder. Start by sharing summary.json and catalog.jsonl.gz.',flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description='Prepare local WoW resource exports for Google Drive')
    parser.add_argument('--data',help='Client Data folder; opens a folder chooser if omitted')
    parser.add_argument('--out',help='Default: output/drive-export, output/icons-export or output/dbc-export')
    parser.add_argument('--part-mib',type=int,default=128)
    parser.add_argument('--listfile',help='Optional plaintext MPQ listfile')
    parser.add_argument('--index-only',action='store_true')
    parser.add_argument('--profile',choices=('graphics','icons','dbc'),default='graphics')
    parser.add_argument('--locale',help='Client language folder, e.g. ruRU; icons and dbc profiles only')
    args=parser.parse_args()
    if not args.out:
        args.out={'graphics':'output/drive-export','icons':'output/icons-export','dbc':'output/dbc-export'}[args.profile]
    try:
        if not args.data:
            import tkinter as tk
            from tkinter import filedialog
            root=tk.Tk();root.withdraw()
            args.data=filedialog.askdirectory(title='Select WoW 3.3.5a Data folder')
            root.destroy()
            if not args.data:
                print('Cancelled.');return 1
        report=build(args.data,args.out,part_mib=args.part_mib,listfile=args.listfile,
                     index_only=args.index_only,profile=args.profile,locale=args.locale)
        print(json.dumps({k:report[k] for k in ('status','resources','estimated_raw_bytes','warnings')},ensure_ascii=False,indent=2))
        return 0
    except KeyboardInterrupt:
        print('Interrupted. Run again with the same settings to resume.',file=sys.stderr)
        return 130
    except (OSError,ValueError) as error:
        print(f'ERROR: {error}',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
