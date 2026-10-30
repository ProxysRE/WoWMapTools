"""Textured orthographic stair flights; visual geometry, not VTT teleport logic."""
import numpy as np
from PIL import Image,ImageColor
from .objects import finite


def validate_stairs(plan):
    stairs=plan.get('stairs',[])
    if not isinstance(stairs,list) or len(stairs)>100:raise ValueError('stairs must be a list of up to 100 flights')
    ids=set();width,height=plan['size_cells']
    for stair in stairs:
        if not isinstance(stair,dict) or not isinstance(stair.get('id'),str) or not stair['id'] or stair['id'] in ids:
            raise ValueError('Stairs require unique string ids')
        ids.add(stair['id'])
        if not isinstance(stair.get('asset'),str) or not stair['asset']:raise ValueError('Stairs need an original texture asset')
        bounds=stair.get('bounds')
        if not isinstance(bounds,(list,tuple)) or len(bounds)!=4:raise ValueError('Stair bounds need four coordinates')
        a,b,c,d=[finite(v,'stair bounds') for v in bounds]
        if not (0<=a<c<=width and 0<=b<d<=height):raise ValueError('Stair bounds must be inside scene')
        if stair.get('down','south') not in ('north','south','east','west'):raise ValueError('Invalid stair down direction')
        if type(stair.get('steps')) is not int or not 1<=stair['steps']<=64:raise ValueError('Stair steps must be 1..64')
        for name,default,low,high in [('tile_cells',2,.05,20),('riser_fraction',.18,.05,.45),('depth_shade',.3,0,.6)]:
            if not low<=finite(stair.get(name,default),'stair '+name)<=high:raise ValueError('Invalid stair '+name)
        if 'tint' in stair:ImageColor.getrgb(stair['tint'])


def render_stairs(plan,images,size,ppc):
    """One source strip per tread/riser; cardinal rotation keeps pixels aligned.

    The default UV split suits a stair texture with a bright tread above its
    darker riser. Each step receives both portions, never a random floor tile.
    """
    validate_stairs(plan);result=Image.new('RGBA',size)
    for stair in plan.get('stairs',[]):
        a,b,c,d=[round(v*ppc) for v in stair['bounds']]
        direction=stair.get('down','south');w,h=c-a,d-b
        cross,length=(h,w) if direction in ('east','west') else (w,h)
        cross=max(1,cross);length=max(1,length)
        texture=images[stair['asset']].convert('RGB')
        tw=max(1,round(stair.get('tile_cells',2)*ppc))
        tread=texture.crop((0,0,texture.width,max(1,round(texture.height*.46))))
        riser=texture.crop((0,round(texture.height*.46),texture.width,max(round(texture.height*.85),round(texture.height*.46)+1)))
        pixels=np.zeros((length,cross,3),dtype=np.float32)
        tint=np.array(ImageColor.getrgb(stair.get('tint','#ffffff')))/255
        for i in range(stair['steps']):
            start=round(i*length/stair['steps']);end=round((i+1)*length/stair['steps'])
            if end<=start:continue
            sh=end-start;rh=max(1,min(sh,round(sh*stair.get('riser_fraction',.18))));th=sh-rh
            step=Image.new('RGB',(cross,sh))
            # Repeat across the flight; stretch only the vertical relief bands.
            for strip,y,band_height in [(tread,0,th),(riser,th,rh)]:
                if band_height<=0:continue
                tile=strip.resize((tw,band_height),Image.Resampling.LANCZOS)
                for x in range(0,cross,tw):step.paste(tile,(x,y))
            values=np.asarray(step,dtype=np.float32)*tint
            values*=1-stair.get('depth_shade',.3)*i/max(1,stair['steps']-1)
            if th>0:values[0]*=1.12
            values[-1]*=.65
            pixels[start:end]=values
        patch=Image.fromarray(np.uint8(np.clip(pixels,0,255))).convert('RGBA')
        rotation={'south':None,'north':Image.Transpose.ROTATE_180,'east':Image.Transpose.ROTATE_90,'west':Image.Transpose.ROTATE_270}[direction]
        if rotation is not None:patch=patch.transpose(rotation)
        result.alpha_composite(patch,(a,b))
    return result
