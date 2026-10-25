import argparse
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw
from .assets import import_zip, Assets
from .render import render, validate


def main():
    parser = argparse.ArgumentParser(description='WoWMapTools DEV0.1 — explicit scene renderer')
    sub = parser.add_subparsers(dest='command', required=True)
    imp = sub.add_parser('import-png', help='Import wow.export PNG ZIP')
    imp.add_argument('zip'); imp.add_argument('--assets', default='assets')
    cat = sub.add_parser('catalog', help='Search local asset metadata')
    cat.add_argument('--assets', default='assets'); cat.add_argument('--filter', default='')
    gallery = sub.add_parser('gallery', help='Contact sheet of base terrain textures')
    gallery.add_argument('--assets', default='assets'); gallery.add_argument('--out', default='output/catalog.jpg')
    ren = sub.add_parser('render', help='Render a JSON scene plan')
    ren.add_argument('--packages', help='Folder with raw resource ZIPs (required for model objects)')
    ren.add_argument('plan'); ren.add_argument('--assets', default='assets'); ren.add_argument('--out', default='output/scene')
    val = sub.add_parser('validate', help='Validate scene and resolve assets')
    val.add_argument('--packages', help='Folder with raw resource ZIPs')
    val.add_argument('plan'); val.add_argument('--assets', default='assets')
    args = parser.parse_args()
    try:
        if args.command == 'import-png':
            result = import_zip(args.zip, args.assets)
            print(f"Catalog: {len(result['records'])} records")
        elif args.command == 'catalog':
            records = Assets(args.assets).records
            for r in records:
                if args.filter.lower() in r['source'].lower():
                    print(json.dumps(r, ensure_ascii=False))
        elif args.command == 'gallery':
            assets = Assets(args.assets)
            records = [r for r in assets.records if r['category'] == 'terrain' and not r['auxiliary']]
            if not records:
                raise ValueError('No base terrain textures')
            sheet = Image.new('RGB', (880, ((len(records)+3)//4)*190), '#252525')
            draw = ImageDraw.Draw(sheet)
            for i, r in enumerate(records):
                x = (i % 4)*220; y = (i // 4)*190
                with Image.open(assets.resolve(r['id'])) as image:
                    image.thumbnail((155,155)); sheet.paste(image.convert('RGB'), (x,y))
                draw.text((x,y+158),r['name'][:32], fill='white')
            out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True); sheet.save(out)
            print(out)
        else:
            plan = json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
            if args.command == 'validate':
                validate(plan)
                if args.packages:
                    from .models import RawAssets, inspect_model
                    with RawAssets(args.packages) as raw:
                        for layer in [plan['base']] + plan.get('layers', []):
                            if not raw.has(layer['asset']):
                                Assets(args.assets).resolve(layer['asset'])
                        for obj in plan.get('objects', []):
                            info = inspect_model(raw,obj['model'])
                            if info['missing']: raise ValueError('Missing model dependencies: '+', '.join(info['missing']))
                else:
                    if plan.get('objects'): raise ValueError('A scene with model objects requires --packages')
                    assets = Assets(args.assets)
                    for layer in [plan['base']] + plan.get('layers', []): assets.resolve(layer['asset'])
                print('Scene and assets valid')
            else:
                print(json.dumps(render(plan,args.assets,args.out,packages=args.packages),ensure_ascii=False,indent=2))
    except (ValueError, KeyError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
