/* SDR output dumps (dvvk-bench --output sdr --dump): 8-bit R'G'B' in
 * XRGB8888, checked against a reference.
 *
 *   dvvk-sdr-compare [options] OURS.xrgb
 *     --size W,H           the dumps' size (default 3840,2160)
 *     --ref FILE           another XRGB8888 dump of the same size: the CPU's
 *                          double-precision map of the same picture
 *                          (dvvk-map-test --output sdr --frame DV.dump --out
 *                          FILE), or another engine run. Per channel: how
 *                          many samples differ by 0, 1, 2 and more codes, the
 *                          largest difference and where.
 *     --oracle FILE        an independent rendering of the same picture: raw
 *                          float R'G'B' (0..1, the display's, before any
 *                          dither; 12 bytes a pixel, rows top first), as
 *                          tools/sdr-oracle writes them (real libplacebo).
 *                          The comparison is in 8-bit codes and in dE ITP
 *                          (BT.2124) of the light the display shows.
 *     --f32                OURS is float R'G'B' too (two oracle renderings
 *                          compared: no --ref, no statistics, no preview)
 *     --white NITS         the display the pictures were made for (default
 *     --black NITS         203, white / 1000, BT.1886): dE ITP's display
 *     --gamma22            model
 *     --limited            OURS holds codes 16..235
 *     --rows A,B           compare rows A..B-1 only (the active picture)
 *     --cols A,B           and columns A..B-1
 *     --blur               compare 2x2 box means instead of pixels (dither
 *                          and chroma siting average out)
 *     --preview FILE.ppm   OURS at a quarter of its size
 *   Exit 0; with --max-diff N (and --ref): 1 if any sample differs by more
 *   than N codes.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int W = 3840, H = 2160;

static unsigned char *load(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *p = malloc(n);
    if (p && fread(p, 1, n, f) != (size_t)n) {
        free(p);
        p = NULL;
    }
    fclose(f);
    *size = n;
    return p;
}

static double white = 203.0, black = 0.0;
static int gamma22 = 0, limited = 0, ours_f32 = 0;

/* The light an SDR display shows for R'G'B' v (dv_map.c's target: BT.1886
 * with the display's black, or a 2.2 power scaled between black and white). */
static double shown(double v)
{
    v = fmin(fmax(v, 0.0), 1.0);
    if (gamma22)
        return black + (white - black) * pow(v, 2.2);
    double lb = pow(black, 1 / 2.4), lw = pow(white, 1 / 2.4);
    return pow((lw - lb) * (v + lb / (lw - lb)), 2.4);
}

static double pq(double nits)
{
    const double m1 = 2610.0 / 16384, m2 = 2523.0 / 32, c1 = 3424.0 / 4096, c2 = 2413.0 / 128, c3 = 2392.0 / 128;
    double p = pow(fmax(nits, 0.0) / 10000.0, m1);
    return pow((c1 + c2 * p) / (1.0 + c3 * p), m2);
}

/* BT.2124: ITP of BT.709 R'G'B' as the display shows it. */
static void itp(const double rgb[3], double out[3])
{
    double r = shown(rgb[0]), g = shown(rgb[1]), b = shown(rgb[2]);
    /* BT.709 to BT.2020 (BT.2087), then BT.2100's LMS */
    double R = 0.6274 * r + 0.3293 * g + 0.0433 * b, G = 0.0691 * r + 0.9195 * g + 0.0114 * b,
           B = 0.0164 * r + 0.0880 * g + 0.8956 * b;
    double l = pq((1688 * R + 2146 * G + 262 * B) / 4096), m = pq((683 * R + 2951 * G + 462 * B) / 4096),
           s = pq((99 * R + 309 * G + 3688 * B) / 4096);
    out[0] = 0.5 * l + 0.5 * m;
    out[1] = 0.5 * (6610 * l - 13613 * m + 7003 * s) / 4096;
    out[2] = (17933 * l - 17390 * m - 543 * s) / 4096;
}

static void ours_rgb(const unsigned char *d, size_t stride, int x, int y, double rgb[3])
{
    if (ours_f32) {
        const float *q = (const float *)d + 3 * ((size_t)y * W + x);
        for (int k = 0; k < 3; k++)
            rgb[k] = fmin(fmax(q[k], 0.0), 1.0);
        return;
    }
    const unsigned char *p = d + (size_t)y * stride + 4 * (size_t)x;
    for (int k = 0; k < 3; k++)
        rgb[k] = limited ? (p[2 - k] - 16.0) / 219.0 : p[2 - k] / 255.0;
}

int main(int argc, char **argv)
{
    const char *ours = NULL, *refpath = NULL, *oracle = NULL, *preview = NULL;
    int row0 = 0, row1 = -1, col0 = 0, col1 = -1, blur = 0, max_diff = -1;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--size") && i + 1 < argc)
            sscanf(argv[++i], "%d,%d", &W, &H);
        else if (!strcmp(argv[i], "--ref") && i + 1 < argc)
            refpath = argv[++i];
        else if (!strcmp(argv[i], "--oracle") && i + 1 < argc)
            oracle = argv[++i];
        else if (!strcmp(argv[i], "--white") && i + 1 < argc)
            white = atof(argv[++i]);
        else if (!strcmp(argv[i], "--black") && i + 1 < argc)
            black = atof(argv[++i]);
        else if (!strcmp(argv[i], "--gamma22"))
            gamma22 = 1;
        else if (!strcmp(argv[i], "--limited"))
            limited = 1;
        else if (!strcmp(argv[i], "--f32"))
            ours_f32 = 1;
        else if (!strcmp(argv[i], "--blur"))
            blur = 1;
        else if (!strcmp(argv[i], "--rows") && i + 1 < argc)
            sscanf(argv[++i], "%d,%d", &row0, &row1);
        else if (!strcmp(argv[i], "--cols") && i + 1 < argc)
            sscanf(argv[++i], "%d,%d", &col0, &col1);
        else if (!strcmp(argv[i], "--max-diff") && i + 1 < argc)
            max_diff = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--preview") && i + 1 < argc)
            preview = argv[++i];
        else if (argv[i][0] != '-')
            ours = argv[i];
        else
            return fprintf(stderr, "unknown option %s\n", argv[i]), 2;
    }
    if (!ours)
        return fprintf(stderr, "usage: dvvk-sdr-compare [--ref F] [--oracle F] [options] OURS.xrgb\n"), 2;
    if (row1 < 0)
        row1 = H;
    if (col1 < 0)
        col1 = W;
    if (black <= 0)
        black = white / 1000.0;
    size_t size;
    unsigned char *d = load(ours, &size);
    if (!d || size < (size_t)W * (ours_f32 ? 12 : 4) * H)
        return fprintf(stderr, "%s: can't read a %dx%d dump\n", ours, W, H), 1;
    size_t stride = size / H;
    if (ours_f32)
        refpath = preview = NULL;
    else {
        double sum[3] = {0};
        int lo[3] = {255, 255, 255}, hi[3] = {0};
        long alpha_bad = 0;
        for (int y = row0; y < row1; y++)
            for (int x = col0; x < col1; x++) {
                const unsigned char *p = d + (size_t)y * stride + 4 * (size_t)x;
                for (int k = 0; k < 3; k++) {
                    int c = p[2 - k];
                    sum[k] += c;
                    lo[k] = c < lo[k] ? c : lo[k];
                    hi[k] = c > hi[k] ? c : hi[k];
                }
                alpha_bad += p[3] != 0xff;
            }
        double n = (double)(row1 - row0) * (col1 - col0);
        printf("%s: R %d..%d mean %.2f, G %d..%d mean %.2f, B %d..%d mean %.2f; X byte not 0xff: %ld\n", ours, lo[0],
               hi[0], sum[0] / n, lo[1], hi[1], sum[1] / n, lo[2], hi[2], sum[2] / n, alpha_bad);
    }
    int status = 0;
    if (refpath) {
        size_t rsize;
        unsigned char *ref = load(refpath, &rsize);
        if (!ref || rsize < (size_t)W * 4 * H)
            return fprintf(stderr, "%s: can't read a %dx%d dump\n", refpath, W, H), 1;
        size_t rstride = rsize / H;
        long hist[3][4] = {{0}}, n = 0;
        int worst[3] = {0}, wx[3] = {0}, wy[3] = {0};
        double sum[3] = {0};
        for (int y = row0; y < row1; y++)
            for (int x = col0; x < col1; x++) {
                const unsigned char *p = d + (size_t)y * stride + 4 * (size_t)x;
                const unsigned char *q = ref + (size_t)y * rstride + 4 * (size_t)x;
                for (int k = 0; k < 3; k++) {
                    int e = abs((int)p[2 - k] - (int)q[2 - k]);
                    hist[k][e > 3 ? 3 : e]++;
                    sum[k] += (int)p[2 - k] - (int)q[2 - k];
                    if (e > worst[k]) {
                        worst[k] = e;
                        wx[k] = x;
                        wy[k] = y;
                    }
                }
                n++;
            }
        const char *names[3] = {"R", "G", "B"};
        for (int k = 0; k < 3; k++) {
            printf("  %s vs ref (8-bit codes): equal %.4f%%, 1 off %.4f%%, 2 off %.5f%%, more %.5f%%; mean %+.5f, max %d at "
                   "%d,%d\n",
                   names[k], 100.0 * hist[k][0] / n, 100.0 * hist[k][1] / n, 100.0 * hist[k][2] / n,
                   100.0 * hist[k][3] / n, sum[k] / n, worst[k], wx[k], wy[k]);
            if (max_diff >= 0 && worst[k] > max_diff)
                status = 1;
        }
        free(ref);
    }
    if (oracle) {
        size_t osize;
        unsigned char *o = load(oracle, &osize);
        if (!o || osize < (size_t)W * 12 * H)
            return fprintf(stderr, "%s: can't read %dx%d float R'G'B'\n", oracle, W, H), 1;
        const float *of = (const float *)o;
        const int step = blur ? 2 : 1;
        long n = 0, over[4] = {0};
        double code_sum[3] = {0}, code_abs[3] = {0}, code_max[3] = {0}, de_sum = 0, de_max = 0;
        int dx = 0, dy = 0;
        static long de_hist[64];
        for (int y = row0; y + step <= row1; y += step)
            for (int x = col0; x + step <= col1; x += step) {
                double a[3] = {0}, b[3] = {0};
                for (int j = 0; j < step; j++)
                    for (int i = 0; i < step; i++) {
                        double v[3];
                        ours_rgb(d, stride, x + i, y + j, v);
                        const float *q = of + 3 * ((size_t)(y + j) * W + x + i);
                        for (int k = 0; k < 3; k++) {
                            a[k] += v[k] / (step * step);
                            b[k] += fmin(fmax(q[k], 0.0), 1.0) / (step * step);
                        }
                    }
                double ia[3], ib[3];
                itp(a, ia);
                itp(b, ib);
                double de = 720.0 * sqrt((ia[0] - ib[0]) * (ia[0] - ib[0]) + (ia[1] - ib[1]) * (ia[1] - ib[1]) +
                                         (ia[2] - ib[2]) * (ia[2] - ib[2]));
                de_sum += de;
                de_hist[de >= 63 ? 63 : (int)de]++;
                if (de > de_max) {
                    de_max = de;
                    dx = x;
                    dy = y;
                }
                over[0] += de > 1;
                over[1] += de > 2;
                over[2] += de > 3;
                over[3] += de > 6;
                for (int k = 0; k < 3; k++) {
                    double e = 255.0 * (a[k] - b[k]);
                    code_sum[k] += e;
                    code_abs[k] += fabs(e);
                    code_max[k] = fmax(code_max[k], fabs(e));
                }
                n++;
            }
        printf("  vs oracle%s (8-bit codes, ours - oracle): R mean %+.3f |%.3f| max %.1f; G mean %+.3f |%.3f| max %.1f; B "
               "mean %+.3f |%.3f| max %.1f\n",
               blur ? " (2x2 means)" : "", code_sum[0] / n, code_abs[0] / n, code_max[0], code_sum[1] / n,
               code_abs[1] / n, code_max[1], code_sum[2] / n, code_abs[2] / n, code_max[2]);
        printf("  dE ITP on a %.0f cd/m2 %s display: mean %.3f, max %.1f at %d,%d; >1 %.3f%% >2 %.3f%% >3 %.4f%% >6 %.4f%%\n",
               white, gamma22 ? "gamma 2.2" : "BT.1886", de_sum / n, de_max, dx, dy, 100.0 * over[0] / n,
               100.0 * over[1] / n, 100.0 * over[2] / n, 100.0 * over[3] / n);
        free(o);
    }
    if (preview) {
        FILE *f = fopen(preview, "wb");
        if (!f)
            return fprintf(stderr, "%s: can't write\n", preview), 1;
        fprintf(f, "P6\n%d %d\n255\n", W / 4, H / 4);
        for (int py = 0; py < H / 4; py++)
            for (int px = 0; px < W / 4; px++) {
                unsigned sum[3] = {0};
                for (int j = 0; j < 4; j++)
                    for (int i = 0; i < 4; i++) {
                        const unsigned char *p = d + (size_t)(py * 4 + j) * stride + 4 * (size_t)(px * 4 + i);
                        for (int k = 0; k < 3; k++)
                            sum[k] += p[2 - k];
                    }
                unsigned char px3[3] = {(unsigned char)((sum[0] + 8) / 16), (unsigned char)((sum[1] + 8) / 16),
                                        (unsigned char)((sum[2] + 8) / 16)};
                fwrite(px3, 1, 3, f);
            }
        fclose(f);
    }
    free(d);
    return status;
}
