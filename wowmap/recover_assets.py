"""Recover explicitly named missing resources without relying on an MPQ listfile.

Read-only client access. Archive precedence and delta/deletion flags are retained;
no invalid patch blob or guessed replacement is exported as a game texture.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile,ZIP_DEFLATED
from .mpq import Storm,PATCH_FILE,DELETE_MARKER
from .pack import archive_order,normalize

DEFAULT_PATHS=['interface/glues/models/ui_scourge/cemetery01.blp']


def recover(data_root,output,paths=None,storm=None,locale=None):
    data_root=Path(data_root);output=Path(output)
    paths=sorted({normalize(p) for p in (paths or DEFAULT_PATHS)})
    if not paths or len(paths)>100 or any(not p.endswith(('.blp','.m2','.skin','.anim')) for p in paths):raise ValueError('Recover 1..100 explicitly named model/texture resources')
    # Localized archives are also searched: they can hold glue-screen resources.
    ordered=archive_order(data_root,profile='dbc',locale=locale)
    storm=storm or Storm();selected={};attempts=[]
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        listfile=Path(temporary)/'requested-listfile.txt'
        listfile.write_text('\n'.join(p.replace('/','\\') for p in paths)+'\n',encoding='utf-8')
        with ExitStack() as stack:
            handles={name:stack.enter_context(storm.open(data_root/name)) for name in ordered}
            for archive_name,archive in handles.items():
                for path in paths:
                    matches=[r for r in archive.entries(listfile,pattern=path.replace('/','\\')) if normalize(r['path'])==path]
                    for row in matches:
                        selected[path]=dict(archive=archive_name,original=row['path'],flags=row['flags'],locale=row['locale'])
                    attempts.append(dict(archive=archive_name,path=path,matches=len(matches)))
            recovered=[];missing=[];blocked=[];contents={}
            for path in paths:
                row=selected.get(path)
                if row is None or row['flags']&DELETE_MARKER:missing.append(path);continue
                if row['flags']&PATCH_FILE:blocked.append(dict(path=path,reason='delta patch requires a patched archive reader'));continue
                blob=handles[row['archive']].read(row['original'],row['locale'])
                if path.endswith('.blp'):
                    from .images import decode_image
                    with decode_image(blob) as image:image.load()
                contents[path]=blob;recovered.append(dict(path=path,archive=row['archive'],bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest()))
    package=output/'recovered-crypt-assets.zip'
    if contents:
        with ZipFile(package.with_suffix('.zip.tmp'),'w',ZIP_DEFLATED) as z:
            for path,blob in contents.items():z.writestr(path,blob)
        package.with_suffix('.zip.tmp').replace(package)
    else:package.unlink(missing_ok=True)
    report=dict(format='wowmap.recovered-assets/1',requested=paths,recovered=recovered,missing=missing,blocked=blocked,
                archives=ordered,attempts=attempts,complete=not missing and not blocked,package=package.name if contents else None)
    (output/'recovery-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data');p.add_argument('--out',default='output/missing-crypt-assets')
    p.add_argument('--path',action='append');p.add_argument('--locale');a=p.parse_args()
    try:
        if not a.data:
            import tkinter as tk
            from tkinter import filedialog
            root=tk.Tk();root.withdraw();a.data=filedialog.askdirectory(title='Select WoW 3.3.5a Data folder');root.destroy()
            if not a.data:raise ValueError('No Data folder selected')
        report=recover(a.data,a.out,a.path,locale=a.locale)
        print(json.dumps(dict(complete=report['complete'],recovered=len(report['recovered']),missing=report['missing'],report=str(Path(a.out)/'recovery-report.json')),ensure_ascii=False))
        return 0 if report['complete'] else 2
    except (OSError,ValueError) as e:p.exit(1,f'ERROR: {e}\n')


if __name__=='__main__':raise SystemExit(main())
