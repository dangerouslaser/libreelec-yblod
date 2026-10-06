"""Exact dyadic expansion arithmetic checks; not device pixel qualification."""
import itertools
from pathlib import Path
import struct
import unittest


def f32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


def expand(samples, x, y):
    a, b, c, d = samples
    left = f32(f32(a * (1 - y)) + f32(b * y))
    right = f32(f32(c * (1 - y)) + f32(d * y))
    return f32(f32(f32(left * (1 - x)) + f32(right * x)) / 4096)


class PlanarMath(unittest.TestCase):
    def test_gles_integer_sampler_precision_explicit(self):
        root = Path(__file__).resolve().parents[3]
        adapter = (root/'packages/mediacenter/kodi/patches/kodi-9999-yblod-17-native-planar-output.patch').read_text()
        self.assertIn('float native_chroma(highp usampler2D plane,ivec2 p)', adapter)
        self.assertNotIn('float native_chroma(usampler2D plane,ivec2 p)', adapter)

    def test_all_phases_extreme_and_neighbor_codes_exact(self):
        for samples in itertools.product((0, 1, 2047, 2048, 4094, 4095), repeat=4):
            for x, y in itertools.product((0, .5), (.25, .75)):
                # Every intermediate is dyadic and exactly representable at12bit.
                numerator = sum(int(value * weight * 8) for value, weight in zip(samples, ((1-x)*(1-y), (1-x)*y, x*(1-y), x*y)))
                self.assertEqual(expand(samples, x, y), f32(numerator / 32768))

    def test_native_coordinates_and_clamped_edges(self):
        width, height = 8, 6
        touched = set()
        for y in range(height):
            for x in range(width):
                self.assertEqual(int((x+.5)//1), x)
                self.assertEqual(int((y+.5)//1), y)
                first_x, first_y = x//2, (2*y-1)//4
                for dx, dy in ((0,0),(0,1),(1,0),(1,1)):
                    touched.add((min(max(first_x+dx,0),width//2-1), min(max(first_y+dy,0),height//2-1)))
        self.assertEqual(touched, set(itertools.product(range(width//2), range(height//2))))

    def test_validator_readonly_and_route_proof(self):
        root = Path(__file__).resolve().parents[3]
        backend = (root/'engine/experimental/native_gpu_ycc_backend.c').read_text()
        validator = backend.split('static const char source[]=',1)[1].split('struct backend_gl *g=',1)[0]
        self.assertNotIn('imageStore', validator)
        self.assertIn('texelFetch(reconstructed_y,p,0)', validator)
        self.assertIn('texelFetch(reconstructed_cb,p,0)', validator)
        self.assertIn('texelFetch(reconstructed_cr,p,0)', validator)
        self.assertIn('value>4095u', validator)
        self.assertIn('b->allocation_width!=p->width',backend)
        adapter = (root/'packages/mediacenter/kodi/patches/kodi-9999-yblod-17-native-planar-output.patch').read_text()
        self.assertIn('m_nativePrepared && m_nativePlanarPrepared ? 1 : 0',adapter)
        self.assertIn('m_nativePlanarFrames += planar != nullptr',adapter)


if __name__ == '__main__':
    unittest.main()
