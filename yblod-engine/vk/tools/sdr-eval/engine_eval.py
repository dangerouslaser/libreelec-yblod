#!/usr/bin/env python3
"""SDR output's CPU map (dvvk-map-test --output sdr --rgb, i.e. yblod/dv_map.c)
against libplacebo's own functions called directly (./ref: pl_tone_map_generate,
pl_gamut_map_sample), on the research's grey ramps and colour patches
(kodi_eval.py), as displayed light in dE ITP (BT.2124). The engine samples the
gamut mapping from a 48x32x256 16-bit LUT as libplacebo's shader does, the
reference calls the function itself: the difference is what that LUT costs.

  engine_eval.py DVVK_MAP_TEST FIXTURE.bin

FIXTURE: AVDOVIMetadata of a BT.2020 stream (yblod/fixtures/28yl-p81.0.bin); its
source luminance, L1 and L9 are replaced by each test title's. Exit 1 when a
title's mean exceeds 0.5 dE ITP or one colour 5 (the colours the LUT is worst
at are BT.2020's own primaries at 1000 cd/m2, on the gamut's boundary: about 4)."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kodi_eval as k  # noqa: E402


def engine(map_test, fixture, pq_rgbs, peak, lw, l1=None):
    args = [map_test, "--output", "sdr", "--white", str(lw), "--src", "0.005,%d" % peak, "--l9", "2", "--rgb"]
    args += ["--l1", "%r,%r" % l1] if l1 else ["--no-l1"]
    text = "".join("%.10f %.10f %.10f\n" % tuple(c) for c in pq_rgbs)
    out = subprocess.run(args + [fixture], input=text, capture_output=True, text=True, check=True)
    res = []
    for line in out.stdout.splitlines():
        f = line.split()
        if len(f) == 6:
            try:
                res.append([float(f[0]), float(f[1]), float(f[2])])
            except ValueError:
                pass
    if len(res) != len(pq_rgbs):
        sys.exit("dvvk-map-test gave %d of %d colours:\n%s" % (len(res), len(pq_rgbs), out.stdout))
    return res


def main():
    map_test, fixture = sys.argv[1], sys.argv[2]
    bad = False
    print("%5s %6s %-12s | %-9s %-15s %s" % ("disp", "peak", "metadata", "colours", "mean / max dE", "worst colour"))
    for lw in (100, 203):
        for peak in (1000, 4000, 10000):
            # static metadata, and two scenes' L1 (max, avg as PQ)
            for l1 in (None, (k.nits_to_pq(min(peak, 400)), k.nits_to_pq(40)), (k.nits_to_pq(120), k.nits_to_pq(12))):
                names = ["grey %g" % g for g in k.GREYS if g <= peak]
                pq = [[k.nits_to_pq(g)] * 3 for g in k.GREYS if g <= peak]
                for name, c, _group in k.colour_set(peak):
                    names.append(name)
                    pq.append(c)
                ref = [k.display(k.encode(r[0], lw), lw) for r in k.ref(pq, peak, lw, "spline", "perceptual", l1)[0]]
                ours = engine(map_test, fixture, pq, peak, lw, l1)
                de = [k.de_itp(a, b) for a, b in zip(ours, ref)]
                worst = max(range(len(de)), key=lambda i: de[i])
                mean = sum(de) / len(de)
                label = "static" if not l1 else "L1 %.0f/%.0f" % (10000 * k.pq_eotf(l1[0]), 10000 * k.pq_eotf(l1[1]))
                print("%5d %6d %-12s | %-9d %6.3f / %6.3f %s" % (lw, peak, label, len(de), mean, de[worst], names[worst]))
                bad |= mean > 0.5 or de[worst] > 5.0
    print("engine_eval: %s" % ("FAILED" if bad else "ok"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
