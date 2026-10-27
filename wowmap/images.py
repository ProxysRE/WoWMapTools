"""Decode original images, including the separate alpha plane of palettized BLP2.

Pillow handles the other supported encodings. Its palettized BLP2 reader uses
palette alpha, whereas WoW stores alpha after the mip's palette indices.
"""
import io
import struct
import numpy as np
from PIL import Image


def decode_image(data,max_pixels=4096*4096,max_dimension=4096):
    def check(width,height):
        if width<=0 or height<=0 or width*height>max_pixels or (max_dimension and max(width,height)>max_dimension):
            raise ValueError('Image exceeds allowed dimensions or pixel count')
    if data[:4]==b'BLP2' and len(data)>=12 and struct.unpack_from('<I',data,4)[0]==1 and data[8]==1:
        if len(data)<1172:raise ValueError('Truncated palettized BLP2 header/palette')
        depth=data[9]
        if depth not in (0,1,4,8):raise ValueError('Unsupported BLP2 alpha depth')
        width,height=struct.unpack_from('<II',data,12);check(width,height);count=width*height
        offset=struct.unpack_from('<I',data,20)[0];length=struct.unpack_from('<I',data,84)[0]
        alpha_bytes=(count*depth+7)//8
        if offset<1172 or length<count+alpha_bytes or offset+length>len(data):
            raise ValueError('Invalid palettized BLP2 mip bounds')
        palette=np.frombuffer(data,dtype='u1',count=1024,offset=148).reshape(256,4)
        indices=np.frombuffer(data,dtype='u1',count=count,offset=offset)
        pixels=palette[indices][:,[2,1,0,3]]
        if depth==0:pixels[:,3]=255
        else:
            plane=np.frombuffer(data,dtype='u1',count=alpha_bytes,offset=offset+count)
            if depth==8:alpha=plane
            elif depth==1:alpha=np.unpackbits(plane,bitorder='little')[:count]*255
            else:alpha=((plane[:,None]>>np.array([0,4],dtype='u1'))&15).reshape(-1)[:count]*17
            pixels[:,3]=alpha
        return Image.fromarray(pixels.reshape(height,width,4))
    with Image.open(io.BytesIO(data)) as source:
        check(source.width,source.height);source.load()
        return source.convert('RGBA')
