"""Deterministic orthographic terrain compositor. Coordinates are grid cells."""
import hashlib
import json
import math
import io
from contextlib import ExitStack
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
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
    size = plan['size_cells']
    if len(size) != 2:
        raise ValueError('size_cells must contain two values')
    ppc = positive(plan['pixels_per_cell'], 'pixels_per_cell')
    width, height = [round(positive(v, 'size_cells') * ppc) for v in size]
    if width < 1 or height < 1 or width * height > 20_000_000:
        raise ValueError('Output must contain between 1 and 20 million pixels')
    layers = [plan['base']] + plan.get('layers', [])
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
        shape = layer.get('shape')
        if shape:
            kind = shape['type']
            if kind == 'ellipse':
                bounds = shape['bounds']
                if len(bounds) != 4 or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                    raise ValueError('Invalid ellipse bounds')
            elif kind in ('path', 'polygon'):
                points = shape['points']
                if len(points) < (2 if kind == 'path' else 3) or any(len(p) != 2 for p in points):
                    raise ValueError('Invalid shape points')
                if kind == 'path':
                    positive(shape['width'], 'path width')
            else:
                raise ValueError(f'Unknown shape: {kind}')
            if shape.get('feather', .4) < 0 or shape.get('roughness', 0) < 0:
                raise ValueError('feather and roughness must be nonnegative')
    for layer in plan.get('layers', []):
        if 'shape' not in layer:
            raise ValueError('Overlay layers require a shape')
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


def texture(path, size, tile_pixels, rng):
    # One periodic texture plane; do not randomly rotate individual tiles (visible seams).
    tile_pixels = max(1, tile_pixels)
    with (path.copy() if isinstance(path, Image.Image) else Image.open(path)) as source:
        ratio = source.height / source.width
        tile = source.convert('RGB').resize((tile_pixels, max(1, round(tile_pixels * ratio))), Image.Resampling.LANCZOS)
    ox = int(rng.integers(tile.width)); oy = int(rng.integers(tile.height))
    canvas = Image.new('RGB', size)
    for y in range(-oy, size[1], tile.height):
        for x in range(-ox, size[0], tile.width):
            canvas.paste(tile, (x, y))
    return canvas


def mask_for(shape, size, ppc, rng):
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    if shape['type'] == 'ellipse':
        draw.ellipse([round(v * ppc) for v in shape['bounds']], fill=255)
    else:
        points = [(round(x * ppc), round(y * ppc)) for x, y in shape['points']]
        if shape['type'] == 'polygon':
            draw.polygon(points, fill=255)
        else:
            radius = shape['width'] * ppc / 2
            draw.line(points, fill=255, width=max(1, round(radius * 2)), joint='curve')
            for x, y in points:
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    feather = shape.get('feather', .4) * ppc
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    a = np.asarray(mask, dtype=np.float32) / 255
    rough = shape.get('roughness', 0)
    if rough:
        noise = random_field(size, rng, max(4, ppc * .7)) * 2 - 1
        # Modulate transition only: do not create speckles in solid regions.
        a = np.clip(a + noise * rough * 4 * a * (1-a), 0, 1)
    return a


def render(plan, assets_root, output, packages=None):
    size = validate(plan)
    if plan.get('objects') and packages is None:
        raise ValueError('A scene with model objects requires --packages')
    with ExitStack() as stack:
        raw = None
        if packages is not None:
            from .models import RawAssets
            raw = stack.enter_context(RawAssets(packages))
        assets = Assets(assets_root) if (Path(assets_root)/'catalog.json').is_file() else None
        paths = []
        for layer in [plan['base']] + plan.get('layers', []):
            selector = layer['asset']
            if raw is not None and raw.has(selector):
                with Image.open(io.BytesIO(raw.read(selector))) as image:
                    image.load(); paths.append(image.copy())
            elif assets is not None:
                paths.append(assets.resolve(selector))
            else:
                raise ValueError(f'Terrain resource unavailable: {selector}')
        # Resolve all model dependencies before writing any output files.
        if raw is not None:
            from .models import inspect_model
            for model in sorted({obj['model'] for obj in plan.get('objects', [])}):
                info = inspect_model(raw, model)
                if info['missing']:
                    raise ValueError('Missing model dependencies: '+', '.join(info['missing']))
        return _render(plan, size, paths, output, raw)


def _render(plan, size, paths, output, raw):
    all_layers = [plan['base']] + plan.get('layers', [])
    ppc = plan['pixels_per_cell']
    seed = plan['seed']
    image = None
    for i, (layer, path) in enumerate(zip(all_layers, paths)):
        rng = layer_rng(seed, layer['id'])
        plane = texture(path, size, round(layer.get('tile_cells', 4) * ppc), rng)
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
    object_report = None
    if plan.get('objects'):
        from .objects import compose_objects
        props, overhead, object_report = compose_objects(plan['objects'], raw, size, ppc, output.parent/'.sprite-cache')
        ground = Image.alpha_composite(image.convert('RGBA'), props)
        image = Image.alpha_composite(ground, overhead).convert('RGB')
        output.mkdir(parents=True, exist_ok=True)
        props.save(output/'objects-ground.png')
        overhead.save(output/'objects-overhead.png')
        ground.convert('RGB').save(output/'map-ground.png')
        (output/'objects.json').write_text(json.dumps(object_report,ensure_ascii=False,indent=2),encoding='utf-8')
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / 'map.png')
    preview = image.copy()
    preview.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    preview.save(output / 'preview.jpg', quality=90)
    grid = image.copy(); draw = ImageDraw.Draw(grid, 'RGBA')
    for x in range(0, size[0], max(1, round(ppc))):
        draw.line((x, 0, x, size[1]), fill=(255,255,255,45))
    for y in range(0, size[1], max(1, round(ppc))):
        draw.line((0, y, size[0], y), fill=(255,255,255,45))
    grid.save(output / 'map-grid.png')
    (output / 'scene-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    metadata = dict(format='wowmap.render/1', name=plan.get('name', ''), width=size[0], height=size[1],
                    pixels_per_cell=ppc, distance_per_cell=plan.get('distance_per_cell', 5),
                    units=plan.get('units', 'ft'), origin='top-left', axis_y='down', seed=seed,
                    image='map.png', foundry_scene_export=False, object_count=len(plan.get('objects', [])),
                    overhead_image='objects-overhead.png' if object_report else None,
                    plan_sha256=hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest())
    (output / 'render.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    return metadata
