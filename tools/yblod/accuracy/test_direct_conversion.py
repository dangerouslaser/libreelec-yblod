#!/usr/bin/env python3
"""CPU checks for the direct transport transform; not GPU/HDMI validation."""
import math
from pathlib import Path
import random
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
PATCHES = ROOT / "projects/Generic/patches/kodi"
CODE = (PATCHES / "kodi-9999-yblod-03-direct-conversion.patch").read_text()
CODE = "\n".join(line[1:] for line in CODE.splitlines() if line.startswith(("+", " ")))
ORIGINAL = (PATCHES / "kodi-9999-yblod-01-qsv-offload.patch").read_text()


def matrix(name):
    block = re.search(r"pl_matrix3x3 " + name + r" = (.*?);", CODE, re.S).group(1)
    values = [float(x) for x in re.findall(r"(-?\d+\.\d+)f", block)]
    assert len(values) == 9
    return [values[n:n+3] for n in (0, 3, 6)]


OUT = matrix("transport_from_hpe")
RGB = matrix("hpe_to_rgb")


def mv(m, v):
    return [sum(a*b for a, b in zip(row, v)) for row in m]


def mm(a, b):
    return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def inverse(m):
    a = [row[:] + [float(i == j) for j in range(3)] for i, row in enumerate(m)]
    for i in range(3):
        divisor = a[i][i]
        a[i] = [x/divisor for x in a[i]]
        for j in range(3):
            if j != i:
                factor = a[j][i]
                a[j] = [x-factor*y for x, y in zip(a[j], a[i])]
    return [row[3:] for row in a]


def encode(x):
    p = max(x, 0)**(2610/16384)
    return ((3424/4096 + 2413/128*p)/(1 + 2392/128*p))**(2523/32)


def decode(x):
    p = min(max(x, 0), 1)**(32/2523)
    return (max(p-3424/4096, 0)/(2413/128-2392/128*p))**(16384/2610)


def release(hpe):
    rgb = mv(RGB, hpe)
    rgb = [decode(encode(x)) for x in rgb]
    return [encode(x) for x in mv(OUT, rgb)]


def direct(hpe):
    return [encode(x) for x in mv(mm(OUT, RGB), hpe)]


class DirectConversionTests(unittest.TestCase):
    def test_matches_existing_glsl_matrix(self):
        values = re.search(r"DV_LMS_FROM_RGB = mat3\(([^)]+)\)", ORIGINAL).group(1)
        glsl = [float(x) for x in values.split(",")]
        self.assertEqual(OUT, [[glsl[j*3+i] for j in range(3)] for i in range(3)])

    def test_ordinary_colors_match_without_rgb_roundtrip(self):
        rng = random.Random(20261004)
        rgb_to_hpe = inverse(RGB)
        worst = 0
        for _ in range(10000):
            rgb = [10**rng.uniform(-7, -0.001) for _ in range(3)]
            hpe = mv(rgb_to_hpe, rgb)
            worst = max(worst, *(abs(a-b)*4096 for a, b in zip(release(hpe), direct(hpe))))
        self.assertLess(worst, 0.00001)

    def test_source_metadata_matrix_is_applied_once(self):
        source = [[1.02, -.01, -.01], [-.01, 1.02, -.01], [-.01, -.01, 1.02]]
        sample = [.03, .02, .01]
        expected = mv(OUT, mv(RGB, mv(source, sample)))
        actual = mv(mm(mm(OUT, RGB), source), sample)
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=14)

    def test_black_and_gray(self):
        rgb_to_hpe = inverse(RGB)
        for level in (0, 1e-7, .0001, .01, .1, 1):
            hpe = mv(rgb_to_hpe, [level]*3)
            for a, b in zip(release(hpe), direct(hpe)):
                self.assertLess(abs(a-b)*4096, 0.00001)

    def test_rgb_clipping_is_intentionally_not_reproduced(self):
        hpe = mv(inverse(RGB), [-.01, .05, .03])
        self.assertTrue(all(x > 0 for x in mv(OUT, [-.01, .05, .03])))
        self.assertGreater(max(abs(a-b)*4096 for a, b in zip(release(hpe), direct(hpe))), 1)

    def test_experiment_defaults_off_and_is_latched(self):
        self.assertIn('id="dvbridge.directconversion"', CODE)
        setting = CODE.split('id="dvbridge.directconversion"', 1)[1].split('</setting>', 1)[0]
        self.assertIn('<default>false</default>', setting)
        self.assertIn('playbackDirectConversion{false}', CODE)
        self.assertIn('playbackDirectConversion.store', CODE)


if __name__ == "__main__":
    unittest.main()
