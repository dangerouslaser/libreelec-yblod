import math
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SHADERS = ROOT / 'engine/experimental'


class CoordinateCandidateTests(unittest.TestCase):
    def test_all_horizontal_positions(self):
        for x in range(3840):
            position = x * 0.5
            expected = (math.floor(position), position - math.floor(position))
            self.assertEqual((x // 2, 0.5 if x & 1 else 0.0), expected)
            self.assertEqual((x >> 1, 0.5 if x & 1 else 0.0), expected)

    def test_all_vertical_positions_and_borders(self):
        for y in range(2160):
            position = (y - 0.5) * 0.5
            expected = (math.floor(position), position - math.floor(position))
            fraction = 0.25 if y & 1 else 0.75
            self.assertEqual((-1 if y == 0 else (y - 1) // 2, fraction), expected)
            self.assertEqual(((y >> 1) - (1 - (y & 1)), fraction), expected)

    def test_sampling_arithmetic_and_flags_unchanged(self):
        original = (SHADERS / 'native_gpu_reconstructed_ycc.comp').read_text()
        start = original.index('    ivec2 last=')
        end = original.index('\n}\nvoid main()', start)
        body = original[start:end]
        for name in ('integer', 'bit'):
            candidate = (SHADERS / f'native_gpu_reconstructed_ycc_{name}_coords.comp').read_text()
            a = candidate.index('    ivec2 last=')
            b = candidate.index('\n}\nvoid main()', a)
            self.assertEqual(candidate[a:b], body)
            self.assertIn('layout(rgba32f,binding=0)', candidate)
            self.assertIn('layout(local_size_x=8, local_size_y=8)', candidate)
            self.assertIn('reconstructed_depth!=12u', candidate)
            self.assertIn('if (y>4095u) atomicOr(error_flags,2u);', candidate)
            self.assertIn('/4096.0,1.0)', candidate)


if __name__ == '__main__':
    unittest.main()
