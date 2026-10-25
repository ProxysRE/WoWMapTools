"""A generic scene launcher; examples are documents, not built-in generation modes."""
import argparse
import json
import os
from pathlib import Path
from .render import render


def main():
    parser=argparse.ArgumentParser(description='Render any WoWMapTools scene JSON')
    parser.add_argument('plan',nargs='?')
    parser.add_argument('--packages',default=os.environ.get('WOWMAP_PACKAGES'))
    parser.add_argument('--out')
    args=parser.parse_args()
    try:
        plan=args.plan;folder=args.packages
        if not plan or not folder:
            import tkinter as tk
            from tkinter import filedialog
            root=tk.Tk();root.withdraw()
            if not plan:
                plan=filedialog.askopenfilename(title='Select scene plan JSON',initialdir=str(Path(__file__).resolve().parents[1]/'examples'),filetypes=[('Scene JSON','*.json')])
            if plan and not folder:folder=filedialog.askdirectory(title='Select WoW resource ZIP folder')
            root.destroy()
        if not plan or not folder:print('Cancelled.');return 1
        out=Path(args.out) if args.out else Path('output')/Path(plan).stem
        metadata=render(json.loads(Path(plan).read_text(encoding='utf-8-sig')),'assets',out,packages=folder)
        print(f"Done: {metadata['width']} x {metadata['height']}; no baked grid")
        if os.name=='nt':os.startfile(str((out/'preview.jpg').resolve()))
        return 0
    except (OSError,ValueError,KeyError) as error:print(f'ERROR: {error}');return 1


if __name__=='__main__':raise SystemExit(main())
