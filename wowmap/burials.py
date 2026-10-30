"""Explicit open/broken stone burial structures using supplied WoW textures.

This is authored 2D architectural geometry, not a repaired or invented M2 model.
"""
import numpy as np
from PIL import Image,ImageDraw,ImageEnhance
from .objects import finite


def validate_burials(plan):
    ids=set()
    for row in plan.get('burials',[]):
        if not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids:raise ValueError('Burials need unique ids')
        ids.add(row['id'])
        if row.get('state','open') not in ('open','broken'):raise ValueError('Burial state must be open or broken')
        if not isinstance(row.get('asset'),str) or not row['asset']:raise ValueError('Burial requires a real stone texture')
        b=row['bounds']
        if len(b)!=4:raise ValueError('Burial bounds need four coordinates')
        a,y,c,d=[finite(v,'burial bounds') for v in b]
        if not 0<=a<c<=plan['size_cells'][0] or not 0<=y<d<=plan['size_cells'][1]:raise ValueError('Burial outside scene')
        if min(c-a,d-y)<.5:raise ValueError('Burial footprint is too small')
        if type(row.get('blocks_movement',True)) is not bool:raise ValueError('blocks_movement must be boolean')


def render_burials(plan,images,size,ppc):
    validate_burials(plan);result=Image.new('RGBA',size)
    for row in plan.get('burials',[]):
        a,b,c,d=[round(v*ppc) for v in row['bounds']];w,h=c-a,d-b
        tile=images[row['asset']].convert('RGB');tile=tile.resize((max(1,round(1.5*ppc)),max(1,round(1.5*ppc))),Image.Resampling.LANCZOS)
        stone=Image.new('RGB',(w,h))
        for y in range(0,h,tile.height):
            for x in range(0,w,tile.width):stone.paste(tile,(x,y))
        rim=max(2,min(round(.12*ppc),min(w,h)//4))
        patch=stone.convert('RGBA');cavity=ImageEnhance.Brightness(stone).enhance(.32)
        patch.paste(cavity.crop((rim,rim,w-rim,h-rim)),(rim,rim))
        draw=ImageDraw.Draw(patch)
        draw.line([(rim,rim),(w-rim-1,rim)],fill=(29,27,25,255),width=max(1,rim//3))
        draw.line([(rim,rim),(rim,h-rim-1)],fill=(24,23,22,255),width=max(1,rim//3))
        draw.line([(1,h-2),(w-2,h-2)],fill=(41,37,33,255),width=max(1,rim//2))
        draw.line([(1,1),(w-2,1)],fill=(150,145,133,255),width=1)
        if row.get('state')=='broken':
            draw.polygon([(w-rim*3,0),(w,0),(w,rim*3),(w-rim*2,rim*2)],fill=(0,0,0,0))
            draw.line([(w//2,h-1),(w//2-rim,h-rim),(w//2+rim,h-rim*2)],fill=(24,22,21,255),width=max(1,round(ppc*.035)))
        result.alpha_composite(patch,(a,b))
    return result
