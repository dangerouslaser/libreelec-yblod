"""Policy/source guards only; hardware execution is a separate gate."""
from fractions import Fraction
from pathlib import Path
import unittest

SHADER = Path(__file__).resolve().parents[3] / "engine/experimental/native_gpu_reconstructed_ycc.comp"


def expand(plane, x, y):
    px, py = Fraction(x, 2), Fraction(2*y-1, 4)
    ix, iy = px.numerator // px.denominator, py.numerator // py.denominator
    fx, fy = px-ix, py-iy
    def at(xx, yy):
        return plane[max(0, min(len(plane)-1, yy))][max(0, min(len(plane[0])-1, xx))]
    left = at(ix, iy)*(1-fy)+at(ix, iy+1)*fy
    right = at(ix+1, iy)*(1-fy)+at(ix+1, iy+1)*fy
    return left*(1-fx)+right*fx


class ReconstructedYccPolicy(unittest.TestCase):
    def test_explicit_left_vertical_centres_and_edges(self):
        plane = [[0, 100], [200, 300]]
        self.assertEqual(expand(plane, 0, 0), 0)
        self.assertEqual(expand(plane, 1, 1), 100)
        self.assertEqual(expand(plane, 2, 2), 250)
        self.assertEqual(expand(plane, 3, 3), 300)

    def test_no_chroma_rounding(self):
        plane = [[0, 1], [1, 0]]
        self.assertEqual(expand(plane, 0, 1), Fraction(1, 4))
        self.assertEqual(expand(plane, 1, 1), Fraction(1, 2))

    def test_shader_explicit_route_and_atomic_rejection(self):
        source = SHADER.read_text()
        for guard in ("sampling_contract!=1u", "reconstructed_depth!=12u",
                      "atomicOr(error_flags,1u)", "atomicOr(error_flags,2u)",
                      "4095u", "/4096.0", "rgba32f", "textureSize(reconstructed_cb,0)"):
            self.assertIn(guard, source)
        self.assertNotIn("round(", source)


if __name__ == "__main__":
    unittest.main()
