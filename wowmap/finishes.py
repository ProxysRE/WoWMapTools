"""Small architectural finishes, kept separate from VTT collision and live lights."""
from PIL import Image, ImageDraw, ImageFilter, ImageColor
from .objects import finite, pair


def validate_finishes(plan):
    finish = plan.get('architecture', {})
    for name, default, upper in [('outline_cells', 0, .2), ('shadow_cells', 0, 1), ('shadow_opacity', .25, 1)]:
        value = finite(finish.get(name, default), name)
        if not 0 <= value <= upper: raise ValueError(f'Invalid architecture {name}')
    ids = set()
    for detail in plan.get('details', []):
        if not detail.get('id') or detail['id'] in ids: raise ValueError('Details require unique ids')
        ids.add(detail['id'])
        if detail['type'] not in ('line', 'rectangle', 'ellipse', 'polygon'): raise ValueError('Invalid detail type')
        for name in ('fill', 'stroke'):
            if detail.get(name) is not None: ImageColor.getcolor(detail[name], 'RGB')
        if not 0 <= finite(detail.get('opacity', 1), 'detail opacity') <= 1: raise ValueError('Invalid detail opacity')
        if not 0 < finite(detail.get('width_cells', .04), 'detail width') <= 2: raise ValueError('Invalid detail width')
        if detail['type'] in ('line', 'polygon'):
            if len(detail['points']) < (3 if detail['type'] == 'polygon' else 2): raise ValueError('Not enough detail points')
            for point in detail['points']: pair(point, 'detail point')
        else:
            a,b,c,d = detail['bounds']
            for value in (a,b,c,d): finite(value, 'detail bounds')
            if c <= a or d <= b: raise ValueError('Invalid detail bounds')


def wall_underlay(walls, ppc, settings):
    result = Image.new('RGBA', walls.size)
    alpha = walls.getchannel('A')
    radius = settings.get('shadow_cells', 0)*ppc
    if radius:
        mask = alpha.filter(ImageFilter.GaussianBlur(radius))
        mask = mask.point(lambda a: round(a*settings.get('shadow_opacity', .25)))
        shade = Image.new('RGBA',walls.size,(24,14,8,0));shade.putalpha(mask);result.alpha_composite(shade)
    edge = round(settings.get('outline_cells', 0)*ppc)
    if edge:
        mask = alpha.filter(ImageFilter.MaxFilter(edge*2+1))
        outline = Image.new('RGBA',walls.size,(39,26,18,0));outline.putalpha(mask);result.alpha_composite(outline)
    return result


def draw_details(plan, size, ppc):
    result = Image.new('RGBA',size)
    for detail in plan.get('details', []):
        patch = Image.new('RGBA',size);draw = ImageDraw.Draw(patch)
        def color(name):
            value=detail.get(name)
            return (*ImageColor.getcolor(value, 'RGB'),round(detail.get('opacity',1)*255)) if value else None
        width=max(1,round(detail.get('width_cells',.04)*ppc));kind=detail['type']
        if kind in ('rectangle','ellipse'):
            bounds=[round(v*ppc) for v in detail['bounds']]
            getattr(draw,kind)(bounds,fill=color('fill'),outline=color('stroke'),width=width)
        else:
            points=[tuple(v*ppc for v in point) for point in detail['points']]
            if kind=='polygon':draw.polygon(points,fill=color('fill'))
            if color('stroke'):
                if kind=='polygon':points.append(points[0])
                draw.line(points,fill=color('stroke'),width=width,joint='curve')
        result.alpha_composite(patch)
    return result
