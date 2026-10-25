"""Deterministic orthographic terrain compositor. Coordinates are grid cells."""
import hashlib
import json
import math
import io
from contextlib import ExitStack
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageColor
from .assets import Assets


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a positive finite number')
    return value


def validate(plan):
    if plan.get('format') != 'wowmap.scene/1':
        raise ValueError('Expected format wowmap.scene/1')
    if not isinstance(plan.get('seed'), int):
        raise ValueError('seed must be an integer')
    if plan.get('export_format','png') not in ('png','webp'):raise ValueError('export_format must be png or webp')
    size = plan['size_cells']
    if len(size) != 2:
        raise ValueError('size_cells must contain two values')
    ppc = positive(plan['pixels_per_cell'], 'pixels_per_cell')
    width, height = [round(positive(v, 'size_cells') * ppc) for v in size]
    if width < 1 or height < 1 or width * height > 20_000_000:
        raise ValueError('Output must contain between 1 and 20 million pixels')
    layers = [plan['base']] + plan.get('layers', []) + plan.get('floors', [])
    ids = set()
    for layer in layers:
        if not isinstance(layer['id'], str) or layer['id'] in ids:
            raise ValueError('Each layer needs a unique string id')
        ids.add(layer['id'])
        if not isinstance(layer['asset'], str):
            raise ValueError('asset must be a string')
        positive(layer.get('tile_cells', 4), 'tile_cells')
        if not 0 <= layer.get('opacity', 1) <= 1:
            raise ValueError('opacity must be in [0, 1]')
        rotation=layer.get('tile_rotation',0)
        if rotation not in (0,90,180,270):raise ValueError('tile_rotation must be 0, 90, 180 or 270')
        if not 0<=layer.get('texture_variation',0)<=.5:raise ValueError('texture_variation must be 0..0.5')
        if 'tint' in layer:ImageColor.getrgb(layer['tint'])
        shape = layer.get('shape')
        if shape:
            from .geometry import validate_shape
            validate_shape(shape)
    for layer in plan.get('layers', []) + plan.get('floors', []):
        if 'shape' not in layer:
            raise ValueError('Overlay layers require a shape')
    from .structures import validate_structures
    validate_structures(plan)
    from .objects import validate_objects
    validate_objects(plan.get('objects', []))
    return width, height


def random_field(size, rng, spacing):
    width, height = size
    small = rng.integers(0, 256, (max(2, math.ceil(height / spacing)),
                                  max(2, math.ceil(width / spacing))), dtype=np.uint8)
    return np.asarray(Image.fromarray(small).resize(size, Image.Resampling.BICUBIC), dtype=np.float32) / 255


def layer_rng(seed, identifier):
    digest = hashlib.sha256(f'{seed}:{identifier}'.encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], 'little'))


def texture(path, size, tile_pixels, rng, rotation=0, variation=0, tint=None):
    # One periodic texture plane; do not randomly rotate individual tiles (visible seams).
    tile_pixels = max(1, tile_pixels)
    with (path.copy() if isinstance(path, Image.Image) else Image.open(path)) as source:
        ratio = source.height / source.width
        tile = source.convert('RGB').resize((tile_pixels, max(1, round(tile_pixels * ratio))), Image.Resampling.LANCZOS)
    if rotation:tile=tile.rotate(rotation,expand=True)
    ox = int(rng.integers(tile.width)); oy = int(rng.integers(tile.height))
    canvas = Image.new('RGB', size)
    for y in range(-oy, size[1], tile.height):
        for x in range(-ox, size[0], tile.width):
            canvas.paste(tile, (x, y))
    if variation:
        alternate=tile.rotate(180)
        other=Image.new('RGB',size)
        dx=int(rng.integers(tile.width));dy=int(rng.integers(tile.height))
        for y in range(-dy,size[1],tile.height):
            for x in range(-dx,size[0],tile.width):other.paste(alternate,(x,y))
        weights=random_field(size,rng,max(16,tile_pixels*1.7))*variation
        canvas=Image.composite(other,canvas,Image.fromarray(np.uint8(weights*255)))
    if tint:
        rgb=np.asarray(canvas,dtype=np.float32)*np.array(ImageColor.getrgb(tint),dtype=np.float32)/255
        canvas=Image.fromarray(np.uint8(np.clip(rgb,0,255)))
    return canvas


def mask_for(shape,size,ppc,rng):
    from .geometry import mask_shape
    return mask_shape(shape,size,ppc,rng)


def resource_names(plan):
    names={layer['asset'] for layer in [plan['base']]+plan.get('layers',[])+plan.get('floors',[])}
    for wall in plan.get('walls',[]):
        names.add(wall['asset'])
        for opening in wall.get('openings',[]):
            if opening.get('asset'):names.add(opening['asset'])
    return names


def render(plan, assets_root, output, packages=None):
    from .planning import expand
    source_plan = plan
    plan, placement_report = expand(plan)
    size = validate(plan)
    if plan.get('objects') and packages is None:
        raise ValueError('A scene with model objects requires --packages')
    with ExitStack() as stack:
        raw = None
        if packages is not None:
            from .models import RawAssets
            raw = stack.enter_context(RawAssets(packages))
        assets = Assets(assets_root) if (Path(assets_root)/'catalog.json').is_file() else None
        images = {}
        for selector in sorted(resource_names(plan)):
            if raw is not None and raw.has(selector):
                with Image.open(io.BytesIO(raw.read(selector))) as image:
                    image.load(); images[selector]=image.copy()
            elif assets is not None:
                with Image.open(assets.resolve(selector)) as image:
                    image.load(); images[selector]=image.copy()
            else:
                raise ValueError(f'Terrain resource unavailable: {selector}')
        paths=[images[layer['asset']] for layer in [plan['base']]+plan.get('layers',[])+plan.get('floors',[])]
        # Resolve all model dependencies before writing any output files.
        if raw is not None:
            from .models import inspect_model
            for model in sorted({obj['model'] for obj in plan.get('objects', [])}):
                info = inspect_model(raw, model)
                if info['missing']:
                    raise ValueError('Missing model dependencies: '+', '.join(info['missing']))
        return _render(plan, size, paths, output, raw, images, source_plan, placement_report)


def _render(plan, size, paths, output, raw, images, source_plan, placement_report):
    all_layers = [plan['base']] + plan.get('layers', []) + plan.get('floors', [])
    ppc = plan['pixels_per_cell']
    seed = plan['seed']
    image = None
    for i, (layer, path) in enumerate(zip(all_layers, paths)):
        rng = layer_rng(seed, layer['id'])
        plane = texture(path, size, round(layer.get('tile_cells', 4) * ppc), rng, layer.get('tile_rotation',0), layer.get('texture_variation',0), layer.get('tint'))
        if i == 0:
            image = plane
        else:
            a = mask_for(layer['shape'], size, ppc, rng) * layer.get('opacity', 1)
            image = Image.composite(plane, image, Image.fromarray(np.uint8(a * 255)))
    # Broad, subtle color variation; this is not a baked point-light effect.
    rng = layer_rng(seed, 'surface-variation')
    variation = random_field(size, rng, max(16, ppc * 5))
    strength = plan.get('surface_variation', .08)
    if not 0 <= strength <= .3:
        raise ValueError('surface_variation must be in [0, .3]')
    rgb = np.asarray(image, dtype=np.float32)
    rgb *= (1 + (variation - .5) * strength)[..., None]
    image = Image.fromarray(np.uint8(np.clip(rgb, 0, 255)))
    output = Path(output)
    extension=plan.get('export_format','png')
    def save_image(image,stem):
        path=output/(stem+'.'+extension)
        if extension=='webp':image.save(path,lossless=True,method=4)
        else:image.save(path)
    object_report = None
    overhead = Image.new('RGBA',size)
    props = Image.new('RGBA',size)
    if plan.get('objects'):
        from .objects import compose_objects
        props, overhead, object_report = compose_objects(plan['objects'], raw, size, ppc, output.parent/'.sprite-cache')
    ground=Image.alpha_composite(image.convert('RGBA'),props)
    from .structures import render_walls
    walls,geometry=render_walls(plan.get('walls',[]),lambda name:images[name],size,ppc)
    vtt_walls,_=render_walls(plan.get('walls',[]),lambda name:images[name],size,ppc,draw_doors=False)
    vtt_ground=Image.alpha_composite(ground,vtt_walls).convert('RGB')
    ground=Image.alpha_composite(ground,walls)
    image=Image.alpha_composite(ground,overhead).convert('RGB')
    output.mkdir(parents=True, exist_ok=True)
    vtt_ground.save(output/'map-vtt.webp',lossless=True,method=4)
    if object_report:
        save_image(props,'objects-ground')
        save_image(overhead,'objects-overhead')
        save_image(ground.convert('RGB'),'map-ground')
        (output/'objects.json').write_text(json.dumps(object_report,ensure_ascii=False,indent=2),encoding='utf-8')
    if plan.get('walls'):
        save_image(walls,'structures')
        (output/'scene-geometry.json').write_text(json.dumps(dict(format='wowmap.geometry/1',units='cells',elements=geometry),ensure_ascii=False,indent=2),encoding='utf-8')
    if placement_report:
        (output/'placement-report.json').write_text(json.dumps(placement_report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Remove only the obsolete generated grid variant from a reused output directory.
    (output/'map-grid.png').unlink(missing_ok=True)
    save_image(image,'map')
    preview = image.copy()
    preview.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    preview.save(output / 'preview.jpg', quality=90)
    (output / 'scene-plan.json').write_text(json.dumps(source_plan, ensure_ascii=False, indent=2), encoding='utf-8')
    if placement_report:(output/'expanded-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    metadata = dict(format='wowmap.render/1', name=plan.get('name', ''), width=size[0], height=size[1],
                    pixels_per_cell=ppc, distance_per_cell=plan.get('distance_per_cell', 5),
                    units=plan.get('units', 'ft'), origin='top-left', axis_y='down', seed=seed,
                    image='map.'+extension, vtt_image='map-vtt.webp', foundry_scene_export=False, grid_baked=False, wall_count=len(plan.get('walls',[])), object_count=len(plan.get('objects', [])),
                    overhead_image='objects-overhead.'+extension if object_report else None,
                    plan_sha256=hashlib.sha256(json.dumps(source_plan, sort_keys=True).encode()).hexdigest(),
                    expanded_plan_sha256=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest())
    (output / 'render.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    return metadata
