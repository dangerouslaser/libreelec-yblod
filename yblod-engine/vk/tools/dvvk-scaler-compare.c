/* The FSR 1 upscaler (dvvk_set_scaler, src/scaler.rs) against a CPU
 * reference: AMD's EASU and RCAS (FidelityFX-FSR v1.20210629 ffx_fsr1.h
 * FsrEasuF, FsrRcasF with FSR_RCAS_DENOISE; MIT, Copyright (c) 2021 Advanced
 * Micro Devices, Inc., LICENSES/MIT-AMD-FidelityFX-FSR.txt) in double
 * precision, on one channel as shaders/common/fsr1.glsl runs them: the luma
 * codes / 4095 as a grey picture. What stays float is what AMD defines in
 * float: FsrEasuCon's constants, the position's mad (fused), and ffx_a.h's
 * bit-pattern approximations (APrxLoRcpF1, APrxMedRcpF1's first guess,
 * APrxLoRsqF1), so both sides take the same taps and the same shapes; one
 * deliberate change from AMD, in both: RCAS's resolve divides exactly.
 *
 * Both inputs are tunnel dumps of one picture (dvvk-bench --dump, the
 * default output: the luma codes are in the bytes, untouched by the
 * packets): SOURCE with the picture unscaled (--dest X,Y,W,H of its own
 * size), SCALED with it enlarged and --scaler easu or rcas. The source's
 * luma is SOURCE's; rows and columns of one value at its edges are its
 * letterbox bars, which the unscaled pack writes as black but the engine
 * reconstructs for EASU: a pixel whose taps (RCAS: its cross's) reach them
 * is left out and counted. The picture's own edges are compared: both
 * sides clamp the taps to the picture. Where EASU's direction test
 * (dirR < 1/32768) is within a relative 1e-5 of its threshold, float and
 * double can decide it either way and both are FSR's answer: the reference
 * is then the one of the two closer to the GPU's, and such pixels are
 * counted ("ties").
 *
 *   dvvk-scaler-compare [options] SOURCE.xrgb SCALED.xrgb
 *     --method M           easu or rcas (default rcas)
 *     --canvas W,H         SCALED's canvas (default 3840,2160)
 *     --source-canvas W,H  SOURCE's (default: the same)
 *     --source X,Y,W,H     the picture in SOURCE (required)
 *     --dest X,Y,W,H       the picture in SCALED (required)
 *     --max-diff N         exit 1 if a code differs by more than N (default 1)
 *
 * Build: cc -O2 -std=gnu11 -ffp-contract=off -o dvvk-scaler-compare
 * dvvk-scaler-compare.c -lm (tools/scaler-check.sh does).
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ffx_a.h's approximations on the float's bits */
static float bits_f(uint32_t u) { float f; memcpy(&f, &u, 4); return f; }
static uint32_t f_bits(float f) { uint32_t u; memcpy(&u, &f, 4); return u; }
static double rcp_lo(double a) { return bits_f(0x7ef07ebbu - f_bits((float)a)); }
static double rcp_med(double a)
{
    double b = bits_f(0x7ef19fffu - f_bits((float)a));
    return b * (-b * a + 2.0);
}
static double rsq_lo(double a) { return bits_f(0x5f347d74u - (f_bits((float)a) >> 1)); }
static double sat(double a) { return a < 0 ? 0 : a > 1 ? 1 : a; }
static double min2(double a, double b) { return a < b ? a : b; }
static double max2(double a, double b) { return a > b ? a : b; }

struct plane { int w, h; const double *v; };

static double tap(const struct plane *p, int x, int y)
{
    x = x < 0 ? 0 : x >= p->w ? p->w - 1 : x;
    y = y < 0 ? 0 : y >= p->h ? p->h - 1 : y;
    return p->v[(size_t)y * p->w + x];
}

/* FsrEasuTapF */
static void easu_tap(double *ac, double *aw, double offx, double offy, const double dir[2], const double len[2],
                     double lob, double clp, double c)
{
    double vx = (offx * dir[0] + offy * dir[1]) * len[0], vy = (offx * -dir[1] + offy * dir[0]) * len[1];
    double d2 = min2(vx * vx + vy * vy, clp);
    double wb = 2.0 / 5.0 * d2 - 1.0, wa = lob * d2 - 1.0;
    wb *= wb;
    wa *= wa;
    wb = 25.0 / 16.0 * wb - (25.0 / 16.0 - 1.0);
    double w = wb * wa;
    *ac += c * w;
    *aw += w;
}

/* FsrEasuSetF */
static void easu_set(double dir[2], double *len, double w, double la, double lb, double lc, double ld, double le)
{
    double lenx = rcp_lo(max2(fabs(ld - lc), fabs(lc - lb))), dirx = ld - lb;
    dir[0] += dirx * w;
    lenx = sat(fabs(dirx) * lenx);
    *len += lenx * lenx * w;
    double leny = rcp_lo(max2(fabs(le - lc), fabs(lc - la))), diry = le - la;
    dir[1] += diry * w;
    leny = sat(fabs(diry) * leny);
    *len += leny * leny * w;
}

/* FsrEasuF at output pixel (ix, iy); scale and offset are FsrEasuCon's.
 * *tie: the direction test is on its threshold; flip: decide it the other
 * way then. */
static double easu(const struct plane *p, unsigned ix, unsigned iy, const float scale[2], const float offset[2],
                   int flip, int *tie)
{
    double ppx = fmaf((float)ix, scale[0], offset[0]), ppy = fmaf((float)iy, scale[1], offset[1]);
    double fx = floor(ppx), fy = floor(ppy);
    ppx -= fx;
    ppy -= fy;
    int x = (int)fx, y = (int)fy;
    double b = tap(p, x, y - 1), c = tap(p, x + 1, y - 1);
    double e = tap(p, x - 1, y), f = tap(p, x, y), g = tap(p, x + 1, y), h = tap(p, x + 2, y);
    double i = tap(p, x - 1, y + 1), j = tap(p, x, y + 1), k = tap(p, x + 1, y + 1), l = tap(p, x + 2, y + 1);
    double n = tap(p, x, y + 2), o = tap(p, x + 1, y + 2);
    double dir[2] = {0, 0}, len = 0;
    /* AMD's luma of a grey pixel: 2 Y */
    easu_set(dir, &len, (1 - ppx) * (1 - ppy), 2 * b, 2 * e, 2 * f, 2 * g, 2 * j);
    easu_set(dir, &len, ppx * (1 - ppy), 2 * c, 2 * f, 2 * g, 2 * h, 2 * k);
    easu_set(dir, &len, (1 - ppx) * ppy, 2 * f, 2 * i, 2 * j, 2 * k, 2 * n);
    easu_set(dir, &len, ppx * ppy, 2 * g, 2 * j, 2 * k, 2 * l, 2 * o);
    double dirr = dir[0] * dir[0] + dir[1] * dir[1];
    int zro = dirr < 1.0 / 32768.0;
    *tie = fabs(dirr * 32768.0 - 1.0) < 1e-5;
    zro ^= flip && *tie;
    dirr = zro ? 1.0 : rsq_lo(dirr);
    dir[0] = zro ? 1.0 : dir[0];
    dir[0] *= dirr;
    dir[1] *= dirr;
    len = len * 0.5;
    len *= len;
    double stretch = (dir[0] * dir[0] + dir[1] * dir[1]) * rcp_lo(max2(fabs(dir[0]), fabs(dir[1])));
    double len2[2] = {1.0 + (stretch - 1.0) * len, 1.0 - 0.5 * len};
    double lob = 0.5 + ((1.0 / 4.0 - 0.04) - 0.5) * len, clp = rcp_lo(lob);
    double ac = 0, aw = 0;
    easu_tap(&ac, &aw, 0 - ppx, -1 - ppy, dir, len2, lob, clp, b);
    easu_tap(&ac, &aw, 1 - ppx, -1 - ppy, dir, len2, lob, clp, c);
    easu_tap(&ac, &aw, -1 - ppx, 1 - ppy, dir, len2, lob, clp, i);
    easu_tap(&ac, &aw, 0 - ppx, 1 - ppy, dir, len2, lob, clp, j);
    easu_tap(&ac, &aw, 0 - ppx, 0 - ppy, dir, len2, lob, clp, f);
    easu_tap(&ac, &aw, -1 - ppx, 0 - ppy, dir, len2, lob, clp, e);
    easu_tap(&ac, &aw, 1 - ppx, 1 - ppy, dir, len2, lob, clp, k);
    easu_tap(&ac, &aw, 2 - ppx, 1 - ppy, dir, len2, lob, clp, l);
    easu_tap(&ac, &aw, 2 - ppx, 0 - ppy, dir, len2, lob, clp, h);
    easu_tap(&ac, &aw, 1 - ppx, 0 - ppy, dir, len2, lob, clp, g);
    easu_tap(&ac, &aw, 1 - ppx, 2 - ppy, dir, len2, lob, clp, o);
    easu_tap(&ac, &aw, 0 - ppx, 2 - ppy, dir, len2, lob, clp, n);
    double lo = min2(min2(f, g), min2(j, k)), hi = max2(max2(f, g), max2(j, k));
    return min2(hi, max2(lo, ac / aw));
}

/* FsrRcasF with FSR_RCAS_DENOISE, one stop (con.x 0.5). A limiter's 0 / 0
 * is a NaN in AMD's HLSL, which max() passes over: the other operand. The
 * resolve divides exactly, as fsr1.glsl does (AMD's APrxMedRcpF1 there is
 * up to 0.32 % low). */
static double rcas(double b, double d, double e, double f, double h)
{
    double bl = 2 * b, dl = 2 * d, el = 2 * e, fl = 2 * f, hl = 2 * h;
    double nz = 0.25 * bl + 0.25 * dl + 0.25 * fl + 0.25 * hl - el;
    double mx = max2(max2(max2(bl, dl), el), max2(fl, hl)), mn = min2(min2(min2(bl, dl), el), min2(fl, hl));
    nz = sat(fabs(nz) * rcp_med(mx - mn));
    nz = -0.5 * nz + 1.0;
    double mn4 = min2(min2(min2(b, d), f), h), mx4 = max2(max2(max2(b, d), f), h);
    double hitmin = min2(mn4, e) / (4.0 * mx4), hitmax = (1.0 - max2(mx4, e)) / (4.0 * mn4 - 4.0);
    double lobe = mx4 == 0.0 ? hitmax : mn4 == 1.0 ? -hitmin : max2(-hitmin, hitmax);
    lobe = max2(-(0.25 - 1.0 / 16.0), min2(lobe, 0.0)) * 0.5;
    lobe *= nz;
    return (lobe * b + lobe * d + lobe * h + lobe * f + e) / (4.0 * lobe + 1.0);
}

static uint8_t *load(const char *path, size_t want)
{
    FILE *f = fopen(path, "rb");
    uint8_t *buf = malloc(want + 1);
    size_t got = f && buf ? fread(buf, 1, want + 1, f) : 0;
    if (f)
        fclose(f);
    if (got != want) {
        fprintf(stderr, "dvvk-scaler-compare: %s: %zu bytes, not %zu\n", path, got, want);
        exit(2);
    }
    return buf;
}

/* a tunnel pixel's 12-bit luma (pack.comp finish()) */
static unsigned luma(const uint8_t *px) { return (unsigned)px[1] << 4 | (px[0] & 15u); }

/* whether row r (or column c from row a0 to a1) of the source is one value */
static int row_flat(const double *v, unsigned sw, unsigned r)
{
    for (unsigned x = 1; x < sw; x++)
        if (v[(size_t)r * sw + x] != v[(size_t)r * sw])
            return 0;
    return 1;
}
static int col_flat(const double *v, unsigned sw, unsigned c, unsigned a0, unsigned a1)
{
    for (unsigned y = a0 + 1; y < a1; y++)
        if (v[(size_t)y * sw + c] != v[(size_t)a0 * sw + c])
            return 0;
    return 1;
}

/* EASU's taps for output row / column i reach texels floor(pos) - 1 ..
 * floor(pos) + 2, clamped to the picture: whether they stay in [lo, hi) */
static int taps_in(unsigned i, float scale, float offset, unsigned n, unsigned lo, unsigned hi)
{
    int f = (int)floorf(fmaf((float)i, scale, offset)), a = f - 1, b = f + 2;
    a = a < 0 ? 0 : a;
    b = b >= (int)n ? (int)n - 1 : b;
    return a >= (int)lo && b < (int)hi;
}

static int parse4(const char *s, unsigned v[4]) { return sscanf(s, "%u,%u,%u,%u", &v[0], &v[1], &v[2], &v[3]) == 4; }

int main(int argc, char **argv)
{
    unsigned cw = 3840, ch = 2160, scw = 0, sch = 0, src[4] = {0}, dst[4] = {0};
    int rcas_on = 1, have_src = 0, have_dst = 0;
    long max_diff = 1;
    const char *paths[2] = {NULL, NULL};
    int npaths = 0;
    for (int a = 1; a < argc; a++) {
        if (!strcmp(argv[a], "--method") && a + 1 < argc) {
            const char *m = argv[++a];
            if (strcmp(m, "easu") && strcmp(m, "rcas"))
                return fprintf(stderr, "--method: easu or rcas\n"), 2;
            rcas_on = !strcmp(m, "rcas");
        } else if (!strcmp(argv[a], "--canvas") && a + 1 < argc) {
            if (sscanf(argv[++a], "%u,%u", &cw, &ch) != 2)
                return fprintf(stderr, "--canvas W,H\n"), 2;
        } else if (!strcmp(argv[a], "--source-canvas") && a + 1 < argc) {
            if (sscanf(argv[++a], "%u,%u", &scw, &sch) != 2)
                return fprintf(stderr, "--source-canvas W,H\n"), 2;
        } else if (!strcmp(argv[a], "--source") && a + 1 < argc)
            have_src = parse4(argv[++a], src);
        else if (!strcmp(argv[a], "--dest") && a + 1 < argc)
            have_dst = parse4(argv[++a], dst);
        else if (!strcmp(argv[a], "--max-diff") && a + 1 < argc)
            max_diff = atol(argv[++a]);
        else if (argv[a][0] != '-' && npaths < 2)
            paths[npaths++] = argv[a];
        else
            return fprintf(stderr, "dvvk-scaler-compare: %s? (see the source)\n", argv[a]), 2;
    }
    if (!scw)
        scw = cw, sch = ch;
    if (npaths != 2 || !have_src || !have_dst || !src[2] || !src[3] || src[0] + src[2] > scw ||
        src[1] + src[3] > sch || dst[0] + dst[2] > cw || dst[1] + dst[3] > ch || dst[2] < src[2] || dst[3] < src[3])
        return fprintf(stderr, "usage: dvvk-scaler-compare [--method easu|rcas] [--canvas W,H] --source X,Y,W,H "
                               "--dest X,Y,W,H SOURCE.xrgb SCALED.xrgb (an enlargement; see the source)\n"), 2;
    uint8_t *s = load(paths[0], (size_t)scw * sch * 4), *t = load(paths[1], (size_t)cw * ch * 4);
    const unsigned sw = src[2], sh = src[3], dw = dst[2], dh = dst[3];
    double *v = malloc(sizeof(double) * sw * sh);
    for (unsigned y = 0; y < sh; y++)
        for (unsigned x = 0; x < sw; x++)
            v[(size_t)y * sw + x] = luma(s + (((size_t)(src[1] + y) * scw) + src[0] + x) * 4) / 4095.0;
    struct plane p = {(int)sw, (int)sh, v};
    /* the bars: rows / columns of one value at the edges */
    unsigned a0 = 0, a1 = sh, b0 = 0, b1 = sw;
    while (a0 < sh && row_flat(v, sw, a0))
        a0++;
    while (a1 > a0 && row_flat(v, sw, a1 - 1))
        a1--;
    while (b0 < sw && col_flat(v, sw, b0, a0, a1))
        b0++;
    while (b1 > b0 && col_flat(v, sw, b1 - 1, a0, a1))
        b1--;
    /* FsrEasuCon, as src/scaler.rs easu_push */
    float scale[2], offset[2];
    for (int k = 0; k < 2; k++) {
        float sz = (float)(k ? sh : sw), r = 1.0f / (float)(k ? dh : dw);
        scale[k] = sz * r;
        offset[k] = 0.5f * sz * r - 0.5f;
    }
    double *e = malloc(sizeof(double) * dw * dh);
    unsigned char *ties = malloc((size_t)dw * dh);
    /* per destination row / column: whether EASU's taps stay in the film */
    unsigned char *row_ok = calloc(dh, 1), *col_ok = calloc(dw, 1);
    for (unsigned y = 0; y < dh; y++)
        row_ok[y] = taps_in(y, scale[1], offset[1], sh, a0, a1);
    for (unsigned x = 0; x < dw; x++)
        col_ok[x] = taps_in(x, scale[0], offset[0], sw, b0, b1);
    for (unsigned y = 0; y < dh; y++)
        for (unsigned x = 0; x < dw; x++) {
            int tie;
            e[(size_t)y * dw + x] = easu(&p, x, y, scale, offset, 0, &tie);
            ties[(size_t)y * dw + x] = (unsigned char)tie;
        }
    long hist[9] = {0};   /* GPU - reference: <= -4, -3 .. 3, >= 4 */
    long compared = 0, left_out = 0, worst = 0, tied = 0;
    unsigned wx = 0, wy = 0;
    double umax = 0, usum = 0;
    for (unsigned y = 0; y < dh; y++)
        for (unsigned x = 0; x < dw; x++) {
            unsigned yu = y ? y - 1 : 0, yd = y + 1 < dh ? y + 1 : dh - 1;
            unsigned xl = x ? x - 1 : 0, xr = x + 1 < dw ? x + 1 : dw - 1;
            int ok = rcas_on ? row_ok[yu] && row_ok[y] && row_ok[yd] && col_ok[xl] && col_ok[x] && col_ok[xr]
                             : row_ok[y] && col_ok[x];
            if (!ok) {
                left_out++;
                continue;
            }
            /* the EASU values the result is made of (RCAS: the cross b, d, e, f, h) */
            const unsigned cx[5] = {x, xl, x, xr, x}, cy[5] = {yu, y, y, y, yd};
            const int first = rcas_on ? 0 : 2, last = rcas_on ? 4 : 2;
            int tie_at[5], nt = 0;
            for (int k = first; k <= last; k++)
                if (ties[(size_t)cy[k] * dw + cx[k]])
                    tie_at[nt++] = k;
            long gpu = luma(t + (((size_t)(dst[1] + y) * cw) + dst[0] + x) * 4);
            double ref = 0;
            /* each tied value decided both ways: the result closest to the GPU's */
            for (int combo = 0; combo < 1 << nt; combo++) {
                double in[5];
                for (int k = first; k <= last; k++)
                    in[k] = e[(size_t)cy[k] * dw + cx[k]];
                for (int i = 0; i < nt; i++)
                    if (combo >> i & 1) {
                        int tie;
                        in[tie_at[i]] = easu(&p, cx[tie_at[i]], cy[tie_at[i]], scale, offset, 1, &tie);
                    }
                double r = sat(rcas_on ? rcas(in[0], in[1], in[2], in[3], in[4]) : in[2]) * 4095.0;
                if (combo == 0 || fabs((double)gpu - r) < fabs((double)gpu - ref))
                    ref = r;
            }
            tied += nt != 0;
            long code = (long)floor(ref + 0.5);
            long d = gpu - code;
            hist[d <= -4 ? 0 : d >= 4 ? 8 : d + 4]++;
            if (labs(d) > labs(worst) || compared == 0)
                worst = d, wx = x, wy = y;
            double u = fabs((double)gpu - ref);
            umax = u > umax ? u : umax;
            usum += u;
            compared++;
        }
    printf("dvvk-scaler-compare: %s, %ux%u -> %ux%u at %u,%u; film rows %u..%u, columns %u..%u of the source\n",
           rcas_on ? "EASU + RCAS" : "EASU", sw, sh, dw, dh, dst[0], dst[1], a0, a1, b0, b1);
    printf("dvvk-scaler-compare: %ld pixels compared (%ld on EASU's direction threshold), %ld left out (their "
           "taps reach the bars); largest difference %+ld code (at %u,%u), GPU - reference:",
           compared, tied, left_out, worst, wx, wy);
    static const char *names[9] = {"<=-4", "-3", "-2", "-1", "0", "+1", "+2", "+3", ">=+4"};
    for (int k = 0; k < 9; k++)
        if (hist[k])
            printf(" %s %.4f%%", names[k], 100.0 * hist[k] / (double)compared);
    printf("; from the unrounded reference max %.3f mean %.4f code\n", umax, compared ? usum / compared : 0.0);
    free(s), free(t), free(v), free(e), free(ties), free(row_ok), free(col_ok);
    return compared == 0 || labs(worst) > max_diff;
}
