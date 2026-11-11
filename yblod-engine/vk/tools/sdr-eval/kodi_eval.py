#!/usr/bin/env python3
"""Kodi's GLES HDR->SDR tone mapping (system/shaders/GLES/2.0/gles_yuv2rgb_basic.frag,
gles_tonemap.frag, YUV2RGBShaderGLES.cpp, ToneMappers.cpp, ConversionMatrix.cpp at Kodi
e6192109 + YBLOD's patches) evaluated against libplacebo's mapping (./ref, built from
yblod-engine/vk/yblod/placebo). Research harness for SDR-OUTPUT-PLAN.md."""
import math
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- PQ / HLG ----------
M1, M2 = 2610.0 / 16384, 2523.0 / 32
C1, C2, C3 = 3424.0 / 4096, 2413.0 / 128, 2392.0 / 128


def pq_eotf(v):  # -> 0..1 (1 = 10000 cd/m2)
    p = max(v, 0.0) ** (1.0 / M2)
    return (max(p - C1, 0.0) / (C2 - C3 * p)) ** (1.0 / M1)


def pq_oetf(l):
    p = max(l, 0.0) ** M1
    return ((C1 + C2 * p) / (1.0 + C3 * p)) ** M2


def nits_to_pq(n):
    return pq_oetf(n / 10000.0)


# ---------- matrices ----------
def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mv(m, v):
    return [m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3)]


def inv3(m):
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]


def rgb2xyz(prim, white):
    cols = [[x / y, 1.0, (1 - x - y) / y] for x, y in prim]
    m = [[cols[j][i] for j in range(3)] for i in range(3)]
    w = [white[0] / white[1], 1.0, (1 - white[0] - white[1]) / white[1]]
    s = mv(inv3(m), w)
    return [[m[i][j] * s[j] for j in range(3)] for i in range(3)]


D65 = (0.3127, 0.3290)
P709 = [(0.640, 0.330), (0.300, 0.600), (0.150, 0.060)]
P2020 = [(0.708, 0.292), (0.170, 0.797), (0.131, 0.046)]
PP3 = [(0.680, 0.320), (0.265, 0.690), (0.150, 0.060)]
X709, X2020, XP3 = rgb2xyz(P709, D65), rgb2xyz(P2020, D65), rgb2xyz(PP3, D65)
M_2020_709 = matmul(inv3(X709), X2020)   # Kodi's m_primMat (ConversionMatrix GenPrimMat)
M_709_2020 = inv3(M_2020_709)
M_P3_2020 = matmul(inv3(X2020), XP3)

# ---------- ICtCp / dE ITP (BT.2100, BT.2124) ----------
LMS = [[1688 / 4096, 2146 / 4096, 262 / 4096], [683 / 4096, 2951 / 4096, 462 / 4096],
       [99 / 4096, 309 / 4096, 3688 / 4096]]
ICTCP = [[0.5, 0.5, 0.0], [6610 / 4096, -13613 / 4096, 7003 / 4096], [17933 / 4096, -17390 / 4096, -543 / 4096]]


def itp_from_709_nits(rgb):
    lin2020 = mv(M_709_2020, rgb)
    lms = [pq_oetf(max(x, 0.0) / 10000.0) for x in mv(LMS, lin2020)]
    i, ct, cp = mv(ICTCP, lms)
    return (i, 0.5 * ct, cp)


def de_itp(a, b):
    x, y = itp_from_709_nits(a), itp_from_709_nits(b)
    return 720.0 * math.sqrt(sum((x[k] - y[k]) ** 2 for k in range(3)))


def chroma_hue(rgb):
    i, t, p = itp_from_709_nits(rgb)
    return math.hypot(t, p), math.degrees(math.atan2(p, t))


def lum709(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


# ---------- the display: BT.1886, white lw, black lw / 1000 ----------
def display(v, lw):
    lb = lw / 1000.0
    a, b = lw ** (1 / 2.4), lb ** (1 / 2.4)
    return [((a - b) * min(max(x, 0.0), 1.0) + b) ** 2.4 for x in v]


def encode(nits, lw):
    lb = lw / 1000.0
    a, b = lw ** (1 / 2.4), lb ** (1 / 2.4)
    return [min(max((max(x, 0.0) ** (1 / 2.4) - b) / (a - b), 0.0), 1.0) for x in nits]


# ---------- Kodi ----------
def kodi_luminance(mastering, maxcll, maxfall):
    """CToneMappers::GetLuminanceValue"""
    result, maxlum = 400.0, 400
    if mastering:
        maxlum = int(mastering)
    if maxcll:
        lum1 = float(maxlum) if maxcll >= maxlum else float(maxcll)
        lum2 = float(maxcll) if maxcll >= maxlum else float(maxlum)
        result = lum1 * 0.5 + lum2 * 0.2 + maxfall * 0.3
    elif mastering:
        result = float(maxlum)
    return result


def kodi(rgb, method, mastering, maxcll, maxfall, param=1.0):
    """gles_yuv2rgb_basic.frag after m_yuvmat (full-range output, contrast 1, black 0):
    rgb = the stream's PQ R'G'B'. Returns (framebuffer value before the clamp, clipped?)."""
    v = [max(0.0, x) ** 2.4 for x in rgb]                 # m_gammaSrc: BT.2020 -> 2.4
    v = [max(0.0, x) for x in mv(M_2020_709, v)]          # m_primMat, negative clipped
    v = [x ** (1 / 2.2) for x in v]                       # m_gammaDstInv: BT.709 -> 2.2
    if method == "reinhard":
        p = 0.7
        if maxcll:
            p = math.log10(100) / math.log10(maxcll)
        elif mastering:
            p = math.log10(100) / math.log10(mastering)
        if p < 0.1 or p > 5.0:
            p = 0.7
        p *= param
        luma = lum709(v)
        if luma > 0:
            k = (luma * (1.0 + luma / (p * p)) / (1.0 + luma)) / luma
            v = [x * k for x in v]
    elif method == "aces":
        lum = kodi_luminance(mastering, maxcll, maxfall)
        v = [pq_eotf(x) * (10000.0 / lum) * (2.0 / param) for x in v]
        v = [(x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14) for x in v]
        v = [(x * 1.24 / param) ** 0.27 for x in v]
    elif method == "hable":
        lum = kodi_luminance(mastering, maxcll, maxfall)
        p1 = (10000.0 / lum) * (2.0 / param)

        def hable(x):
            A, B, C, D, E, F = 0.15, 0.5, 0.1, 0.2, 0.02, 0.3
            return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F

        wp = lum / 100.0
        v = [hable(pq_eotf(x) * p1 * wp) / hable(wp) for x in v]
        v = [max(x, 0.0) ** (1 / 2.2) for x in v]
    elif method != "off":
        raise ValueError(method)
    clipped = any(x > 1.0 + 1e-6 for x in v)
    return v, clipped


# ---------- the reference ----------
def ref(pq_rgbs, src_peak, dst_peak, tone="spline", gamut="perceptual", l1=None):
    args = [os.path.join(HERE, "ref"), str(src_peak), str(dst_peak), tone, gamut]
    if l1:
        args += [repr(l1[0]), repr(l1[1])]
    text = "".join("%.10f %.10f %.10f\n" % tuple(c) for c in pq_rgbs)
    out = subprocess.run(args, input=text, capture_output=True, text=True, check=True)
    res = []
    for line in out.stdout.splitlines():
        r, g, b, f = line.split()
        res.append(([float(r), float(g), float(b)], int(f)))
    return res, out.stderr.strip()


# ---------- test colours (as BT.2020 PQ R'G'B') ----------
def pq_from_2020_nits(rgb):
    return [nits_to_pq(max(x, 0.0)) for x in rgb]


def srgb_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def patch_709(srgb8, white_nits):
    lin = [srgb_lin(c) * white_nits for c in srgb8]
    return pq_from_2020_nits(mv(M_709_2020, lin))


def patch_prim(prim_matrix, rgb, level_nits):
    """a primary/secondary of `prim_matrix`'s gamut at the signal level where white is level_nits"""
    lin = [x * level_nits for x in rgb]
    if prim_matrix:
        lin = mv(prim_matrix, lin)
    return pq_from_2020_nits(lin)


GREYS = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 18, 26, 50, 100, 203, 300, 400, 600, 800, 1000, 1500,
         2000, 3000, 4000, 6000, 8000, 10000]
NAMES6 = [("red", (1, 0, 0)), ("green", (0, 1, 0)), ("blue", (0, 0, 1)), ("yellow", (1, 1, 0)), ("cyan", (0, 1, 1)),
          ("magenta", (1, 0, 1))]


def colour_set(peak):
    s = []
    for lvl in (10, 100, 203, 1000):
        if lvl > peak:
            continue
        for n, c in NAMES6:
            s.append(("BT.2020 %s @%g" % (n, lvl), patch_prim(None, c, lvl), "2020"))
    for lvl in (100, 203, 1000):
        if lvl > peak:
            continue
        for n, c in NAMES6:
            s.append(("P3 %s @%g" % (n, lvl), patch_prim(M_P3_2020, c, lvl), "p3"))
    # natural colours (ColorChecker sRGB values), diffuse white at 203 cd/m2 (BT.2408)
    for n, c in (("dark skin", (115, 82, 68)), ("light skin", (194, 150, 130)), ("blue sky", (98, 122, 157)),
                 ("foliage", (87, 108, 67)), ("orange", (214, 126, 44)), ("white 9.5", (243, 243, 242)),
                 ("neutral 5", (122, 122, 121)), ("black 2", (52, 52, 52))):
        s.append((n + " (white 203)", patch_709(c, 203), "natural"))
    # a bright sky and sunlit skin, 2x diffuse white (a specular/outdoor HDR scene)
    for n, c in (("light skin", (194, 150, 130)), ("bright sky", (135, 206, 235))):
        s.append((n + " (white 406)", patch_709(c, 406), "natural"))
    # near black
    for n, c in (("dark red", (1, 0.1, 0.1)), ("dark blue", (0.1, 0.1, 1)), ("dark green", (0.1, 1, 0.1))):
        s.append((n + " @0.5", patch_prim(M_P3_2020, c, 0.5), "dark"))
    # saturated highlights
    for lvl in (600, 1000, 4000):
        if lvl > peak:
            continue
        s.append(("P3 fire orange @%g" % lvl, patch_prim(M_P3_2020, (1, 0.35, 0.05), lvl), "highlight"))
        s.append(("P3 neon blue @%g" % lvl, patch_prim(M_P3_2020, (0.1, 0.3, 1), lvl), "highlight"))
    return s


TITLES = {  # peak: (mastering max, MaxCLL, MaxFALL)
    1000: (1000, 1000, 180),
    4000: (4000, 4000, 400),
    10000: (10000, 10000, 1000),
}
METHODS = ["off", "reinhard", "aces", "hable"]


def fmt(x):
    return "%7.2f" % x if x < 1000 else "%7.0f" % x


def main():
    out = []
    P = out.append
    P("Kodi 2020->709 matrix (m_primMat): " + "; ".join(" ".join("%.4f" % x for x in r) for r in M_2020_709))
    summary = {}
    for lw in (100, 203):
        for peak in (1000, 4000, 10000):
            mast, cll, fall = TITLES[peak]
            lumv = kodi_luminance(mast, cll, fall)
            P("")
            P("=" * 110)
            P("SOURCE peak %d cd/m2 (mastering %d, MaxCLL %d, MaxFALL %d; Kodi luminance value %.0f, Reinhard param %.3f)"
              "   DISPLAY BT.1886 %d cd/m2 (black %.3f)" % (peak, mast, cll, fall, lumv, math.log10(100) / math.log10(cll), lw, lw / 1000))
            greys = [g for g in GREYS if g <= peak]
            gpq = [[nits_to_pq(g)] * 3 for g in greys]
            refs = {}
            for tone in ("spline", "bt2390", "bt2446a"):
                r, info = ref(gpq, peak, lw, tone)
                refs[tone] = r
                P("  ref %-8s %s" % (tone, info))
            P("  GREY RAMP: displayed cd/m2 (and dE ITP against the spline reference)")
            P("  %8s | %8s %8s %8s | %s" % ("in", "spline", "bt2390", "bt2446a",
                                              " ".join("%16s" % m for m in METHODS)))
            clip_at = {m: None for m in METHODS}
            for k, g in enumerate(greys):
                rs = {t: display(encode(refs[t][k][0], lw), lw) for t in refs}
                row = "  %8g | %s %s %s |" % (g, fmt(rs["spline"][1]), fmt(rs["bt2390"][1]), fmt(rs["bt2446a"][1]))
                for m in METHODS:
                    v, clipped = kodi(gpq[k], m, mast, cll, fall)
                    d = display(v, lw)
                    e = de_itp(d, rs["spline"])
                    if clipped and clip_at[m] is None:
                        clip_at[m] = g
                    row += " %s%s(%5.1f)" % (fmt(d[1]), "*" if clipped else " ", e)
                    summary.setdefault((lw, peak, m, "grey"), []).append(e)
                summary.setdefault((lw, peak, "bt2390", "grey"), []).append(de_itp(rs["bt2390"], rs["spline"]))
                summary.setdefault((lw, peak, "bt2446a", "grey"), []).append(de_itp(rs["bt2446a"], rs["spline"]))
                P(row)
            P("  first grey level whose framebuffer value exceeds 1.0 (clipped white): " +
              ", ".join("%s %s" % (m, clip_at[m] if clip_at[m] else "never") for m in METHODS))

            cols = colour_set(peak)
            cpq = [c[1] for c in cols]
            cref = {t: ref(cpq, peak, lw, t)[0] for t in ("spline", "bt2390")}
            cclip = ref(cpq, peak, lw, "spline", "clip")[0]
            P("  COLOURS: dE ITP against the spline+perceptual reference; [Y ratio, chroma ratio, hue shift deg] of Kodi vs the reference")
            P("  %-28s | %7s %7s %6s | %7s | %s" % ("patch", "refY", "refC", "refH", "bt2390",
                                                      " ".join("%30s" % m for m in METHODS)))
            for k, (name, pq, group) in enumerate(cols):
                rd = display(encode(cref["spline"][k][0], lw), lw)
                rd2 = display(encode(cref["bt2390"][k][0], lw), lw)
                rc, rh = chroma_hue(rd)
                e2 = de_itp(rd2, rd)
                summary.setdefault((lw, peak, "bt2390", group), []).append(e2)
                row = "  %-28s | %s %7.4f %6.1f | %7.1f |" % (name, fmt(lum709(rd)), rc, rh, e2)
                for m in METHODS:
                    v, clipped = kodi(pq, m, mast, cll, fall)
                    d = display(v, lw)
                    e = de_itp(d, rd)
                    c, h = chroma_hue(d)
                    dh = (h - rh + 180) % 360 - 180
                    row += " %6.1f%s[%5.2f %5.2f %+6.1f]" % (e, "*" if clipped else " ", lum709(d) / lum709(rd),
                                                             c / rc if rc > 1e-6 else float("nan"), dh)
                    summary.setdefault((lw, peak, m, group), []).append(e)
                P(row)

    P("")
    P("=" * 110)
    P("SUMMARY: mean / max dE ITP against libplacebo spline+perceptual (bt2390 and bt2446a rows: the spread between reference curves)")
    groups = ["grey", "natural", "p3", "2020", "dark", "highlight"]
    P("  %5s %6s %-9s | %s" % ("disp", "peak", "method", " ".join("%15s" % g for g in groups)))
    for lw in (100, 203):
        for peak in (1000, 4000, 10000):
            for m in METHODS + ["bt2390", "bt2446a"]:
                row = "  %5d %6d %-9s |" % (lw, peak, m)
                for g in groups:
                    v = summary.get((lw, peak, m, g))
                    row += " %6.1f / %6.1f" % (sum(v) / len(v), max(v)) if v else " %15s" % "-"
                P(row)
    print("\n".join(out))


if __name__ == "__main__":
    main()
