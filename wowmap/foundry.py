"""Foundry VTT 13 scene bundles. Coordinates in plans are cells; radii are cells.

No game-system rules, arbitrary scripts or third-party module flags are generated.
Runtime validation in import-foundry.js uses the user's actual Foundry schema.
"""
import argparse
import copy
import hashlib
import json
import datetime
import re
from pathlib import Path
from PIL import Image
from .geometry import validate_shape
from .objects import finite, pair
from .structures import wall_parts

SENSE = {'none': 0, 'limited': 10, 'normal': 20, 'proximity': 30, 'distance': 40}
STATE = {'closed': 0, 'open': 1, 'locked': 2}
BEHAVIORS = {'teleportToken', 'pauseGame', 'suppressWeather', 'modifyMovementCost', 'adjustDarknessLevel'}


def uid(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:16]


def number(value, name, low=None, high=None):
    v = finite(value, name)
    if (low is not None and v < low) or (high is not None and v > high):
        raise ValueError(f'{name} outside allowed range')
    return v


def boolean(value, name):
    if not isinstance(value, bool): raise ValueError(f'{name} must be boolean')
    return value


def local_path(value):
    # Foundry Data-relative paths only. External files remain explicit dependencies.
    if not isinstance(value, str) or not value or any(x in value for x in ('\\', ':', '?', '#')):
        raise ValueError('Media path must be relative to Foundry Data')
    if value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('Invalid media path')
    return value


def shape_data(shape, ppc, hole=False):
    validate_shape(shape)
    if shape.get('feather', 0) or shape.get('roughness', 0):
        raise ValueError('Foundry regions require exact shapes without feather/roughness')
    kind = shape['type']
    if kind == 'path': raise ValueError('Region paths must be outlined as polygons')
    common = dict(type=kind, hole=hole)
    if kind == 'polygon':
        common['points'] = [v * ppc for point in shape['points'] for v in point]
    else:
        a, b, c, d = [v * ppc for v in shape['bounds']]
        if kind == 'rectangle': common.update(x=a, y=b, width=c-a, height=d-b, rotation=0)
        else: common.update(x=(a+c)/2, y=(b+d)/2, radiusX=(c-a)/2, radiusY=(d-b)/2, rotation=0)
    result = [common]
    for cutout in shape.get('cutouts', []):
        if cutout.get('cutouts'): raise ValueError('Nested region cutouts are not supported')
        result.extend(shape_data(cutout, ppc, True))
    return result


def wall_options(options, window=False):
    result = dict(move=20, sight=0 if window else 20, light=0 if window else 20, sound=20, dir=0)
    for key in ('sight', 'light', 'sound'):
        value = options.get(key)
        if value is not None:
            if value not in SENSE: raise ValueError(f'Invalid wall {key}')
            result[key] = SENSE[value]
    if 'move' in options:
        if options['move'] not in ('normal', 'none'): raise ValueError('Invalid wall move')
        result['move'] = 20 if options['move'] == 'normal' else 0
    if options.get('direction', 'both') not in ('both', 'left', 'right'): raise ValueError('Invalid wall direction')
    result['dir'] = {'both': 0, 'left': 1, 'right': 2}[options.get('direction', 'both')]
    thresholds = options.get('threshold', {})
    if set(thresholds) - {'light', 'sight', 'sound', 'attenuation'}: raise ValueError('Unknown wall threshold')
    result['threshold'] = {key: number(value, 'threshold', 0) if key != 'attenuation' else boolean(value, key)
                           for key, value in thresholds.items()}
    for key in ('sight', 'light', 'sound'):
        if result[key] in (30, 40) and key not in thresholds:
            raise ValueError(f'{key} proximity/distance needs threshold in scene distance units')
    return result


def compile_scene(plan, package_id, scene_key, keys, media_root, has_overhead=False):
    ppc = number(plan['pixels_per_cell'], 'pixels_per_cell', 50)
    distance = number(plan.get('distance_per_cell', 5), 'distance_per_cell', .001)
    config = plan.get('foundry', {})
    sid = uid(package_id, scene_key)
    def identifier(kind, key): return uid(package_id, scene_key, kind, key)
    def flags(key): return {'wowmap': {'sourceId': key}}
    walls = []
    def add_wall(a, b, key, options, door=0, state=0, window=False):
        coords = [number(v * ppc, 'wall coordinate') for p in (a, b) for v in p]
        if coords[:2] == coords[2:]: raise ValueError('Zero length Foundry wall')
        walls.append(dict(_id=identifier('wall', key), c=coords, door=door, ds=state,
                          flags=flags(key), **wall_options(options, window)))
    for wall in plan.get('walls', []):
        pieces, openings = wall_parts(wall)
        for i, (a, b) in enumerate(pieces): add_wall(a, b, f"{wall['id']}:{i}", wall.get('foundry', {}))
        for a, b, op in openings:
            if op['type'] == 'passage': continue
            opts = {**wall.get('foundry', {}), **op.get('foundry', {})}
            door = (2 if boolean(opts.get('secret', False), 'secret') else 1) if op['type'] == 'door' else 0
            add_wall(a, b, op['id'], opts, door, STATE[op.get('state', 'closed')], op['type'] == 'window')
    barrier_ids = set()
    for row in plan.get('burials',[]):
        if not row.get('blocks_movement',True):continue
        a,b,c,d=row['bounds'];pts=[[a,b],[c,b],[c,d],[a,d]]
        for i,(p,q) in enumerate(zip(pts,pts[1:]+pts[:1])):
            add_wall(p,q,'burial:'+row['id']+':'+str(i),dict(sight='none',light='none',sound='none'))
    for barrier in config.get('barriers', []):
        if barrier['id'] in barrier_ids: raise ValueError('Duplicate barrier id')
        barrier_ids.add(barrier['id'])
        pts = [pair(p, 'barrier point') for p in barrier['points']]
        if len(pts) < 2: raise ValueError('Barrier needs at least two points')
        if barrier.get('closed'): pts.append(pts[0])
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            add_wall(a, b, 'barrier:'+barrier['id']+':'+str(i), barrier)
    lights = []
    for light in config.get('lights', []):
        x, y = pair(light['position'], 'light position')
        bright = number(light.get('bright', 0), 'bright', 0) * distance
        dim = number(light.get('dim', 0), 'dim', 0) * distance
        if dim < bright: raise ValueError('dim radius must cover bright radius')
        color = light.get('color', '#ffffff')
        if not re.fullmatch(r'#[a-fA-F0-9]{6}', color): raise ValueError('Light color must be #RRGGBB')
        cfg = dict(bright=bright, dim=dim, color=color, alpha=number(light.get('alpha', .5), 'alpha', 0, 1),
                   angle=number(light.get('angle', 360), 'angle', 0, 360))
        if 'animation' in light:
            ani = light['animation']
            cfg['animation'] = dict(type=ani['type'], speed=number(ani.get('speed', 5), 'speed', 0, 10),
                                    intensity=number(ani.get('intensity', 5), 'intensity', 0, 10))
        lights.append(dict(_id=identifier('light', light['id']), x=x*ppc, y=y*ppc, config=cfg,
                           walls=boolean(light.get('walls', True), 'light walls'),
                           hidden=boolean(light.get('hidden', False), 'light hidden'),
                           rotation=number(light.get('rotation', 0), 'rotation', 0, 360), flags=flags(light['id'])))
    regions = []
    for region in config.get('regions', []):
        rid = region['id']; behaviors = []
        for i, behavior in enumerate(region.get('behaviors', [])):
            kind = behavior['type']
            if kind not in BEHAVIORS: raise ValueError(f'Unsupported region behavior: {kind}')
            system = copy.deepcopy(behavior.get('system', {}))
            if kind == 'teleportToken':
                dest = behavior['destination']; dest_key = dest.get('scene', scene_key)
                if dest_key not in keys or dest['region'] not in keys[dest_key]:
                    raise ValueError(f'Unknown teleport destination: {dest}')
                system = dict(destination=f"Scene.{uid(package_id, dest_key)}.Region.{uid(package_id, dest_key, 'region', dest['region'])}",
                              choice=boolean(behavior.get('choice', True), 'teleport choice'))
            elif kind == 'pauseGame': system = dict(once=boolean(behavior.get('once', True), 'pause once'))
            elif kind == 'suppressWeather': system = {}
            # The two configurable behaviors use explicit native v13 system data;
            # no guessed game-system movement modes or darkness enum values.
            elif not system: raise ValueError(f'{kind} requires explicit native system data')
            behaviors.append(dict(_id=identifier('behavior', f'{rid}:{i}'), name=behavior.get('name', kind),
                                  type=kind, system=system, disabled=False))
        shapes = []
        for shape in region['shapes']: shapes.extend(shape_data(shape, ppc))
        if not shapes: raise ValueError('Region needs shapes')
        elevation = region.get('elevation', {})
        bottom = None if elevation.get('bottom') is None else number(elevation['bottom'], 'region bottom')
        top = None if elevation.get('top') is None else number(elevation['top'], 'region top')
        if bottom is not None and top is not None and bottom > top: raise ValueError('Invalid region elevation range')
        regions.append(dict(_id=identifier('region', rid), name=region.get('name', rid), shapes=shapes,
                            elevation=dict(bottom=bottom, top=top), behaviors=behaviors,
                            visibility=0, color=region.get('color', '#8888ff'), flags=flags(rid)))
    sounds = []
    for sound in config.get('sounds', []):
        x, y = pair(sound['position'], 'sound position')
        sounds.append(dict(_id=identifier('sound', sound['id']), x=x*ppc, y=y*ppc, path=local_path(sound['path']),
                           radius=number(sound['radius'], 'sound radius', .001)*distance,
                           volume=number(sound.get('volume', .5), 'volume', 0, 1),
                           repeat=True, easing=True, walls=True, hidden=False))
    w, h = [round(v * ppc) for v in plan['size_cells']]
    tiles = []
    if has_overhead:
        tiles.append(dict(_id=identifier('tile', 'canopy'), x=0, y=0, width=w, height=h,
                          texture=dict(src=media_root+'/overhead.webp'), elevation=number(config.get('overhead_elevation', 20), 'overhead_elevation'),
                          occlusion=dict(mode=1, alpha=.15), restrictions=dict(light=False, weather=True), locked=True))
    for tile in config.get('tiles', []):
        x, y = pair(tile['position'], 'tile position');tw, th = pair(tile['size_cells'], 'tile size')
        if min(tw, th) <= 0: raise ValueError('Tile size must be positive')
        tiles.append(dict(_id=identifier('tile', tile['id']), x=x*ppc, y=y*ppc, width=tw*ppc, height=th*ppc,
                          texture=dict(src=local_path(tile['path'])), elevation=number(tile.get('elevation', 0), 'tile elevation'),
                          occlusion=dict(mode=1 if tile.get('overhead', False) else 0, alpha=.15),
                          restrictions=dict(light=bool(tile.get('blocks_light', False)), weather=bool(tile.get('overhead', False))), locked=True))
        if 'opacity' in tile:tiles[-1]['alpha']=number(tile['opacity'],'tile opacity',0,1)
        if 'video' in tile:
            video=tile['video']
            if not isinstance(video,dict) or set(video)-{'autoplay','loop','volume'}:raise ValueError('Unsupported tile video fields')
            if any(type(video[k]) is not bool for k in ('autoplay','loop') if k in video):raise ValueError('Tile video autoplay/loop must be boolean')
            tiles[-1]['video']=dict(autoplay=video.get('autoplay',True),loop=video.get('loop',True),volume=number(video.get('volume',0),'tile video volume',0,1))
    for label, docs in [('wall', walls), ('light', lights), ('region', regions), ('sound', sounds), ('tile', tiles)]:
        if len({doc['_id'] for doc in docs}) != len(docs): raise ValueError(f'Duplicate {label} id')
    return dict(_id=sid, name=plan.get('name', scene_key), active=False, navigation=True, width=w, height=h, padding=0,
                background=dict(src=media_root+'/background.webp'),
                grid=dict(type=1, size=ppc, distance=distance, units=plan.get('units', 'ft'), alpha=number(config.get('grid_alpha', .2), 'grid_alpha', 0, 1)),
                tokenVision=True, fog=dict(exploration=True),
                environment=dict(darknessLevel=number(config.get('darkness', .5), 'darkness', 0, 1),
                                 globalLight=dict(enabled=boolean(config.get('global_light', False), 'global_light'))),
                weather=config.get('weather', ''), walls=walls, lights=lights, regions=regions, sounds=sounds, tiles=tiles,
                flags={'wowmap': dict(format='wowmap.foundry/1', package=package_id, key=scene_key, target='13.351')})


def export_bundle(scene_dirs, output, package_id):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', package_id): raise ValueError('Package id must contain lowercase ASCII letters, digits, hyphens')
    output = Path(output)
    if output.exists() and any(output.iterdir()): raise ValueError('Export directory must be empty; use a new directory')
    records = []; keys = {}
    for folder in map(Path, scene_dirs):
        source = json.loads((folder/'scene-plan.json').read_text(encoding='utf-8-sig'))
        meta = json.loads((folder/'render.json').read_text(encoding='utf-8-sig'))
        digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        if digest != meta['plan_sha256']: raise ValueError('Scene plan changed after rendering; render it again')
        image = folder/meta.get('vtt_image', 'map-vtt.webp')
        if not meta.get('vtt_image') or not image.is_file(): raise ValueError('Render scene with DEV0.5 before exporting')
        key = source.get('foundry', {}).get('key', folder.name)
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', key): raise ValueError('Scene key must be a lowercase ASCII slug')
        if key in keys: raise ValueError('Duplicate scene key')
        region_ids = [r['id'] for r in source.get('foundry', {}).get('regions', [])]
        if len(set(region_ids)) != len(region_ids): raise ValueError('Duplicate region id')
        keys[key] = set(region_ids)
        overhead = folder/meta['overhead_image'] if meta.get('overhead_image') else None
        if overhead and not overhead.is_file(): raise ValueError('Missing overhead image')
        if overhead:
            with Image.open(overhead) as im:
                if not im.convert('RGBA').getchannel('A').getbbox(): overhead = None
        with Image.open(image) as im:
            if im.size != (meta['width'], meta['height']): raise ValueError('Rendered image size mismatch')
        records.append((key, source, image, overhead))
    if not records: raise ValueError('At least one rendered scene is required')
    scenes = [compile_scene(plan, package_id, key, keys, f'wowmap/{package_id}/{key}', overhead is not None)
              for key, plan, image, overhead in records]
    # Validate all scene links and data before creating any deliverable files.
    root = output/'wowmap'/package_id
    root.mkdir(parents=True)
    for (key, plan, image, overhead), scene in zip(records, scenes):
        dest = root/key; dest.mkdir()
        with Image.open(image) as im: im.convert('RGB').save(dest/'background.webp', lossless=True)
        if overhead:
            with Image.open(overhead) as im: im.convert('RGBA').save(dest/'overhead.webp', lossless=True)
        (dest/'scene.json').write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding='utf-8')
    external = sorted({s['path'] for scene in scenes for s in scene['sounds']} |
                      {t['texture']['src'] for scene in scenes for t in scene['tiles'] if not t['texture']['src'].startswith(f'wowmap/{package_id}/')})
    bundle = dict(format='wowmap.foundry/1', target='13.351', mediaRoot=f'wowmap/{package_id}', scenes=scenes, externalMedia=external)
    (root/'bundle.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    macro = Path(__file__).with_name('import_foundry.js').read_text(encoding='utf-8')
    macro = macro.replace('__BUNDLE_URL__', f'wowmap/{package_id}/bundle.json')
    (output/'import-foundry.js').write_text(macro, encoding='utf-8')
    (output/'README.txt').write_text(
        'Foundry VTT 13.351 — импорт WoWMapTools\n\n'
        '1. Скопируйте папку wowmap в папку Data сервера Foundry, сохранив структуру.\n'
        '   Для хостинга загрузите её через файловый менеджер хостинга.\n'
        '2. Создайте Script-макрос, вставьте содержимое import-foundry.js и запустите от мастера.\n'
        '3. Укажите путь к bundle.json. Макрос проверяет данные и файлы перед созданием сцен.\n'
        '   Существующие сцены не заменяются. Повторный импорт остановится при совпадении ID.\n'
        '4. Этажи импортируйте вместе: переходы ссылаются на ID сцен и зон.\n\n'
        'Сетка рисуется только Foundry. Радиусы света пересчитаны в единицы сцены.\n'
        'Двери интерактивны через значки Foundry; текстура полотна в фон не запечена.\n'
        'Окна по умолчанию прозрачны для зрения и света, блокируют движение.\n'
        'Переходы по умолчанию запрашивают согласие игрока. Для перехода между сценами\n'
        'игроку нужны разрешения TOKEN_CREATE и TOKEN_DELETE.\n'
        'Верхний слой — один общий tile: при перекрытии может скрываться целиком.\n'
        'В комплект не входят токены персонажей, аудиофайлы и внешние изображения.\n'
        'Экспорт сверён с API v13; окончательная игровая проверка нужна в вашем Foundry.\n'
        + ('\nВнешние файлы (разместите отдельно в Data):\n'+'\n'.join(external) if external else ''), encoding='utf-8')
    return dict(output=str(output), scenes=len(scenes), walls=sum(len(s['walls']) for s in scenes),
                lights=sum(len(s['lights']) for s in scenes), regions=sum(len(s['regions']) for s in scenes), external_media=external)


def main():
    parser = argparse.ArgumentParser(description='Export rendered scenes to a Foundry VTT 13 bundle')
    parser.add_argument('--scene', action='append', help='Rendered scene directory; repeat for linked floors')
    parser.add_argument('--out'); parser.add_argument('--id', dest='package_id')
    args = parser.parse_args()
    if not args.scene:
        import tkinter as tk
        from tkinter import filedialog, messagebox, simpledialog
        window = tk.Tk(); window.withdraw(); args.scene = []
        while True:
            folder = filedialog.askdirectory(title='Select rendered scene folder (contains render.json)')
            if not folder: break
            args.scene.append(folder)
            if not messagebox.askyesno('Linked scenes', 'Add another floor or scene?'): break
        if not args.scene: window.destroy(); return
        args.package_id = simpledialog.askstring('Export package', 'Package id (ASCII lowercase, digits, hyphens):', initialvalue='wowmap-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        if not args.package_id: window.destroy(); return
        parent = filedialog.askdirectory(title='Choose parent folder for export')
        window.destroy()
        if not parent: return
        args.out = str(Path(parent)/('foundry-'+args.package_id))
    if not args.out or not args.package_id: parser.error('--out and --id are required with --scene')
    try: print(json.dumps(export_bundle(args.scene, args.out, args.package_id), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error: parser.exit(1, f'ERROR: {error}\n')


if __name__ == '__main__': main()
