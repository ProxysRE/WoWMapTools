"""Static top-down water: shoreline depth, visible bed and non-periodic ripples.

This material changes RGB only. The compositor retains the layer's original mask;
it does not create collision, water depth rules, lights, or Foundry animation.
"""
import math
import numpy as np
from PIL import Image, ImageColor, ImageFilter
from .geometry import validate_shape, mask_shape


def validate_water(layer):
    options = layer['water']
    if not isinstance(options, dict):
        raise ValueError('water must be an object')
    if layer.get('shape', {}).get('type') not in ('polygon', 'rectangle'):
        raise ValueError('Water material requires a polygon or rectangle shape')
    for key in ('shore_color', 'shoal_color', 'deep_color'):
        if key in options:
            if not isinstance(options[key], str):
                raise ValueError(f'water.{key} must be a color string')
            color = ImageColor.getrgb(options[key])
            if len(color) != 3:
                raise ValueError(f'water.{key} must be an RGB color')
    for key, default, low, high in [('depth_cells', 4, .1, 100), ('ripple_cells', .45, .05, 10),
                                   ('ripple_strength', .1, 0, .4), ('bed_visibility', .35, 0, 1)]:
        value = options.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'water.{key} must be finite in [{low}, {high}]')
    flow = options.get('flow', [0, 1])
    if not isinstance(flow, (list, tuple)) or len(flow) != 2:
        raise ValueError('water.flow needs two coordinates')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in flow) or math.hypot(*flow) < 1e-8:
        raise ValueError('water.flow must be a finite nonzero vector')
    shallows = options.get('shallow_shapes', [])
    if not isinstance(shallows, list) or len(shallows) > 100:
        raise ValueError('water.shallow_shapes must be a list of up to 100 shapes')
    for shape in shallows:
        validate_shape(shape)
    def check_cutouts(shape):
        for cutout in shape.get('cutouts', []):
            if cutout['type'] not in ('polygon', 'rectangle'):
                raise ValueError('Water cutouts must be polygons or rectangles')
            check_cutouts(cutout)
    check_cutouts(layer['shape'])


def _field(size, rng, spacing):
    w, h = size
    small = rng.integers(0, 256, (max(2, math.ceil(h / spacing)), max(2, math.ceil(w / spacing))), dtype=np.uint8)
    return np.asarray(Image.fromarray(small).resize(size, Image.Resampling.BICUBIC), dtype=np.float32) / 255


def shoreline_distance(shape, size, ppc, scene_cells=None):
    """Distance in cells; scene-edge inlet/outlet segments are not shorelines."""
    w, h = size
    scene_w, scene_h = scene_cells or (w / ppc, h / ppc)
    if shape['type'] == 'rectangle':
        a, b, c, d = shape['bounds']; points = [[a, b], [c, b], [c, d], [a, d]]
    else:
        points = shape['points']
    rings = [points]
    for cutout in shape.get('cutouts', []):
        if cutout['type'] == 'polygon':
            rings.append(cutout['points'])
        elif cutout['type'] == 'rectangle':
            a, b, c, d = cutout['bounds']; rings.append([[a, b], [c, b], [c, d], [a, d]])
        else:
            raise ValueError('Water cutouts must be polygons or rectangles')
    X = (np.arange(w, dtype=np.float32)[None, :] + .5) / ppc
    Y = (np.arange(h, dtype=np.float32)[:, None] + .5) / ppc
    result = np.full((h, w), np.inf, dtype=np.float32)
    for ring_index, ring in enumerate(rings):
        for a, b in zip(ring, ring[1:] + ring[:1]):
            vx, vy = b[0] - a[0], b[1] - a[1]
            if vx * vx + vy * vy < 1e-12:
                continue
            if ring_index == 0 and any(abs(a[k] - edge) < 1e-5 and abs(b[k] - edge) < 1e-5 for k, edge in [(0, 0), (0, scene_w), (1, 0), (1, scene_h)]):
                continue
            t = np.clip(((X - a[0]) * vx + (Y - a[1]) * vy) / (vx * vx + vy * vy), 0, 1)
            dist = np.hypot(X - a[0] - t * vx, Y - a[1] - t * vy)
            np.minimum(result, dist, out=result)
    return result


def water_surface(bed, layer, ppc, rng):
    validate_water(layer)
    cfg = layer['water']; full_size = bed.size
    # Bounded work plane keeps 20M-pixel maps practical without extra dependencies.
    factor = min(1, 1600 / max(full_size)); size = tuple(max(1, round(v * factor)) for v in full_size)
    # Preserve scene coordinates exactly for unequal dimension rounding.
    work_ppc = ppc * factor
    depth = shoreline_distance(layer['shape'], size, work_ppc, (full_size[0] / ppc, full_size[1] / ppc))
    noise = _field(size, rng, max(8, work_ppc * 1.5))
    fine = _field(size, rng, max(3, work_ppc * .22))
    d = np.clip(depth / cfg.get('depth_cells', 4), 0, 1)
    d = np.clip(d + (noise - .5) * .15 * np.minimum(depth, 1), 0, 1)
    for shape in cfg.get('shallow_shapes', []):
        values = mask_shape(shape, size, work_ppc, rng)
        mask = Image.fromarray(np.uint8(values * 255)).filter(ImageFilter.GaussianBlur(max(1, work_ppc * .25)))
        weight = np.asarray(mask, dtype=np.float32) / 255
        d = d * (1 - weight) + np.minimum(d, .16) * weight
    shore = np.array(ImageColor.getrgb(cfg.get('shore_color', '#8d9877')), dtype=np.float32)
    shoal = np.array(ImageColor.getrgb(cfg.get('shoal_color', '#4d8c83')), dtype=np.float32)
    deep = np.array(ImageColor.getrgb(cfg.get('deep_color', '#244e5a')), dtype=np.float32)
    wet = np.clip(depth / .65, 0, 1)[..., None]
    rgb = shore * (1 - wet) + shoal * wet
    blend = np.power(d, .65)[..., None]
    rgb = rgb * (1 - blend) + deep * blend
    bottom = np.asarray(bed.resize(size, Image.Resampling.LANCZOS).convert('RGB'), dtype=np.float32)
    bottom = bottom / np.maximum(bottom.mean(axis=2, keepdims=True), 1) - 1
    visibility = cfg.get('bed_visibility', .35) * np.exp(-d * 6)
    rgb += bottom * (visibility * 28)[..., None]
    rgb *= (1 + (noise - .5) * .13 + (fine - .5) * .035)[..., None]
    w, h = size; X = (np.arange(w, dtype=np.float32)[None, :] + .5) / work_ppc; Y = (np.arange(h, dtype=np.float32)[:, None] + .5) / work_ppc
    flow = np.asarray(cfg.get('flow', [0, 1]), dtype=np.float32); flow /= np.linalg.norm(flow)
    along = X * flow[0] + Y * flow[1]; across = X * flow[1] - Y * flow[0]
    phase = 2 * math.pi * (along / cfg.get('ripple_cells', .45) + (noise - .5) * 2.8 + .17 * np.sin(across * 1.7))
    wave = np.sin(phase); wave2 = np.sin(phase * 1.43 + across * 2.3 + fine * 2.1)
    strength = cfg.get('ripple_strength', .1)
    broken = np.clip((noise - .25) * 2.5, 0, 1) * np.clip((fine - .42) * 4, 0, 1)
    highlights = np.maximum(wave, 0) ** 24 * np.maximum(wave2, 0) ** 3 * broken
    ripples = (wave * .07 + wave2 * .06 + highlights * 1.6) * strength * 90
    rgb += ripples[..., None] * np.array([.75, .96, 1.05], dtype=np.float32)
    # Small interrupted wet glints at the land/water boundary, never a solid foam line.
    shore_glint = np.exp(-((depth - .08) / .06) ** 2) * np.clip((fine - .55) * 4, 0, 1)
    rgb += (shore_glint * strength * 65)[..., None]
    return Image.fromarray(np.uint8(np.clip(rgb, 0, 255))).resize(full_size, Image.Resampling.LANCZOS)
