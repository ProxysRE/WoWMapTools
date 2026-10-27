import io
import struct
import unittest
import numpy as np
from PIL import Image
from wowmap.images import decode_image


def palette_blp(depth,alpha=b''):
    # Three pixels deliberately share a palette entry but have independent alpha.
    header=bytearray(148)
    struct.pack_into('<4sI4BII',header,0,b'BLP2',1,1,depth,8,1,3,1)
    struct.pack_into('<I',header,20,1172);struct.pack_into('<I',header,84,3+len(alpha))
    palette=bytearray(1024);palette[:4]=bytes([30,20,10,0])
    return bytes(header+palette)+b'\0\0\0'+alpha


class ImageDecodeTests(unittest.TestCase):
    def test_palette_alpha_plane_8_bit_is_per_pixel_not_per_palette_entry(self):
        image=decode_image(palette_blp(8,bytes([0,127,255])))
        self.assertEqual(np.asarray(image).reshape(-1,4).tolist(),[[10,20,30,0],[10,20,30,127],[10,20,30,255]])

    def test_one_bit_four_bit_and_no_alpha(self):
        for depth,data,expected in [(0,b'',[255,255,255]),(1,bytes([5]),[255,0,255]),
                                    (4,bytes([0x80,0x0f]),[0,136,255])]:
            pixels=np.asarray(decode_image(palette_blp(depth,data)))
            self.assertEqual(pixels[0,:,3].tolist(),expected)

    def test_bounds_invalid_depth_and_dimensions_are_checked_before_decode(self):
        for data in [palette_blp(8,b'\xff'),palette_blp(3,b'\xff'),palette_blp(8,b'\xff'*3)[:-1],b'BLP2'+b'\1\0\0\0\1\10\10\1']:
            with self.assertRaises(ValueError):decode_image(data)
        with self.assertRaisesRegex(ValueError,'dimensions'):decode_image(palette_blp(0),max_pixels=2)

    def test_non_blp_fallback_preserves_rgba(self):
        buffer=io.BytesIO();Image.new('RGBA',(3,2),(4,6,8,100)).save(buffer,format='PNG')
        self.assertEqual(decode_image(buffer.getvalue()).getpixel((1,1)),(4,6,8,100))
