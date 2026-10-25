"""Convenience Windows entry point; the renderer itself has no GUI requirement."""
import argparse
import json
import os
from pathlib import Path
from .render import render


def main():
    parser=argparse.ArgumentParser(description='Render the Ashenvale camp example from local resource packages')
    parser.add_argument('--packages')
    parser.add_argument('--out',default='output/camp')
    args=parser.parse_args()
    try:
        folder=args.packages
        if not folder:
            candidate=Path('output/drive-export/upload/packages')
            if candidate.is_dir(): folder=str(candidate)
        if not folder:
            import tkinter as tk
            from tkinter import filedialog
            root=tk.Tk();root.withdraw()
            folder=filedialog.askdirectory(title='Select folder containing WoW resource ZIP packages')
            root.destroy()
        if not folder:
            print('Cancelled.');return 1
        plan=Path(__file__).resolve().parents[1]/'examples'/'ashenvale-camp-objects.json'
        result=render(json.loads(plan.read_text(encoding='utf-8')),'assets',args.out,packages=folder)
        print(f"Done: {result['object_count']} objects; {result['width']} x {result['height']} pixels")
        if os.name=='nt': os.startfile(str((Path(args.out)/'preview.jpg').resolve()))
        return 0
    except (OSError,ValueError,KeyError) as error:
        print(f'ERROR: {error}');return 1


if __name__=='__main__':raise SystemExit(main())
