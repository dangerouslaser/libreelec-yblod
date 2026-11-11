/* The output colour mapping's CPU half on metadata fixtures
 * (yblod/fixtures/*.bin, AVDOVIMetadata as dvvk-bench --metadata writes
 * them): what dvvk_map_plan decides, and how far a 3D LUT of N points per
 * axis (trilinear, as the pack samples it) is from the exact mapping over
 * random 12-bit Y'CbCr, in output codes (12-bit Y'CbCr for HDR10, the
 * display's 8-bit R'G'B' for SDR).
 *
 *   dvvk-map-test [options] FIXTURE.bin...
 *     --n N              the 3D LUT's points per axis (default 65)
 *     --samples K        random samples (default 200000)
 *     --output MODE      hdr10 (default) or sdr
 *     --white NITS       SDR: the display's white (default 203)
 *     --black NITS       SDR: its black (default white / 1000)
 *     --gamma22          SDR: a 2.2 power instead of BT.1886
 *     --limited          SDR: codes 16..235
 *     --no-dither        SDR: rounded codes in --out
 *     --frame DUMP       a Dolby Vision tunnel dump (dvvk-bench --dump, output
 *                        dv) mapped pixel by pixel: the share of its pixels
 *                        in cells the bake would mark, the LUT's error on it
 *     --out FILE         with --frame: the frame mapped exactly on the CPU, in
 *                        the engine's output bytes (the reference of
 *                        dvvk-hdr10-compare / dvvk-sdr-compare)
 *     --overlay FILE     SDR, with --out: an overlay blended over the mapped
 *                        frame as the pack blends the shell's layer (raw
 *                        3840x2160 BGRA premultiplied sRGB, rows top first:
 *                        dvvk-bench's --overlay file)
 *   The fixture's metadata changed before the plan (the research harness's
 *   titles, SDR-OUTPUT-PLAN.md 0.3):
 *     --src NITS,NITS    the source display's minimum and maximum
 *     --l1 MAXPQ,AVGPQ   L1 maximum and average (0..1); --no-l1: none
 *     --l9 INDEX         L9's primaries (0 P3-D65, 1 BT.709, 2 BT.2020)
 *     --no-l6            no L6 (the output peak is the source's maximum)
 *   Sanity of the SDR map without a GPU (needs a BT.2020 fixture, i.e. not
 *   Profile 5: the map's input is then BT.2020 PQ R'G'B' itself):
 *     --ramp             a grey ramp 0.005 .. the source's maximum as the
 *                        display shows it (cd/m2), with the checks: monotonic,
 *                        white only at the source's peak, black at code 0
 *                        (16), greys neutral
 *     --rgb              stdin lines of BT.2020 PQ R'G'B' (0..1) -> the
 *                        display's linear BT.709 light in cd/m2 (as the
 *                        research harness's ref printed) and the 8-bit codes
 *   THRESH=C: the marking threshold in output codes (the engine's defaults:
 *   0.5, SDR 0.35); POINTS=N: the points of a cell the marking looks at (7,
 *   SDR 19).
 */
#include "../include/dvvk_map.h"
#include <libavutil/dovi_meta.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static void *load(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *p = aligned_alloc(64, (n + 63) / 64 * 64);
    if (p && fread(p, 1, n, f) != (size_t)n) {
        free(p);
        p = NULL;
    }
    fclose(f);
    *size = n;
    return p;
}

static const dvvk_map_gpu *g;
static const uint32_t *tables;

/* dvvk_map_rgb's result as unrounded output codes: 12-bit limited-range
 * Y'CbCr, or the display's R'G'B' codes */
static void out_codes(const double rgb[3], double c[3])
{
    if (g->flags & DVVK_MAP_SDR) {
        for (int k = 0; k < 3; k++)
            c[k] = g->out_code[0] * rgb[k] + g->out_code[1];
        return;
    }
    double ycc[3];
    dvvk_map_ycc(rgb, ycc);
    c[0] = 256.0 + 3504.0 * ycc[0];
    c[1] = 2048.0 + 3584.0 * ycc[1];
    c[2] = 2048.0 + 3584.0 * ycc[2];
}

static double pq_oetf(double nits)
{
    const double m1 = 2610.0 / 16384, m2 = 2523.0 / 32, c1 = 3424.0 / 4096, c2 = 2413.0 / 128, c3 = 2392.0 / 128;
    double p = pow(fmax(nits, 0.0) / 10000.0, m1);
    return pow((c1 + c2 * p) / (1.0 + c3 * p), m2);
}

/* the light the display shows for R'G'B' v (the inverse of out_trc), cd/m2 */
static double shown(double v)
{
    return 10000.0 * (pow(v + g->out_trc[3], 1.0 / g->out_trc[2]) - g->out_trc[1]) / g->out_trc[0];
}

static uint16_t pq12(double nits)
{
    return (uint16_t)lround(pq_oetf(nits) * 4095.0);
}

/* The fixture's metadata as the options ask. */
static void edit(void *md, const char *src, const char *l1, int no_l1, int l9, int no_l6)
{
    AVDOVIMetadata *m = md;
    AVDOVIColorMetadata *colour = (AVDOVIColorMetadata *)av_dovi_get_color(m);
    double a, b;
    if (src && sscanf(src, "%lf,%lf", &a, &b) == 2) {
        colour->source_min_pq = pq12(a);
        colour->source_max_pq = pq12(b);
    }
    for (int i = 0; i < m->num_ext_blocks; i++) {
        AVDOVIDmData *e = (AVDOVIDmData *)av_dovi_get_ext(m, i);
        if (e->level == 1 && no_l1)
            e->level = 254;   /* an unknown level: ignored */
        else if (e->level == 1 && l1 && sscanf(l1, "%lf,%lf", &a, &b) == 2) {
            e->l1.min_pq = 0;
            e->l1.max_pq = (uint16_t)lround(a * 4095.0);
            e->l1.avg_pq = (uint16_t)lround(b * 4095.0);
        } else if (e->level == 9 && l9 >= 0)
            e->l9.source_primary_index = (uint8_t)l9;
        else if (e->level == 6 && no_l6)
            e->level = 254;
        else if (e->level == 6 && src)
            e->l6.max_luminance = (uint16_t)lround(atof(strchr(src, ',') + 1));
    }
}

static int ramp(void)
{
    static const double levels[] = {0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 18, 26, 50, 100, 203, 300,
                                    400, 600, 800, 1000, 1500, 2000, 4000, 10000};
    const double white = shown(1.0), black = shown(0.0);
    double peak = 10000.0 * pow(fmax(pow(g->tone_in[1], 32.0 / 2523) - 3424.0 / 4096, 0.0) /
                                (2413.0 / 128 - 2392.0 / 128 * pow(g->tone_in[1], 32.0 / 2523)), 16384.0 / 2610);
    int bad = 0;
    double last = -1;
    printf("  grey ramp (display %.4g..%.4g cd/m2; the curve's input ends at %.0f cd/m2)\n", black, white, peak);
    printf("      in cd/m2 |  shown cd/m2 |   R'G'B' codes (rounded)\n");
    for (size_t i = 0; i < sizeof(levels) / sizeof(*levels); i++) {
        double nl[3] = {pq_oetf(levels[i]), pq_oetf(levels[i]), pq_oetf(levels[i])}, rgb[3], c[3];
        dvvk_map_rgb(g, tables, nl, rgb);
        out_codes(rgb, c);
        double y = 0.2126 * shown(rgb[0]) + 0.7152 * shown(rgb[1]) + 0.0722 * shown(rgb[2]);
        printf("    %10g | %12.4f | %7.2f %7.2f %7.2f\n", levels[i], y, c[0], c[1], c[2]);
        if (y < last - 1e-9) {
            printf("    NOT MONOTONIC at %g\n", levels[i]);
            bad = 1;
        }
        if (levels[i] < peak * 0.999 && rgb[0] >= 1.0 && rgb[1] >= 1.0 && rgb[2] >= 1.0) {
            printf("    WHITE BELOW THE PEAK at %g\n", levels[i]);
            bad = 1;
        }
        /* libplacebo's gamut mapper works in float through a tabulated PQ
         * curve: a grey leaves it a few hundredths of a code off neutral */
        if (fabs(c[0] - c[1]) > 0.1 || fabs(c[1] - c[2]) > 0.1) {
            printf("    GREY NOT NEUTRAL at %g\n", levels[i]);
            bad = 1;
        }
        last = y;
    }
    /* signal black and the source's peak */
    double z[3] = {0, 0, 0}, top[3] = {g->tone_in[1], g->tone_in[1], g->tone_in[1]}, rz[3], rt[3], cz[3], ct[3];
    dvvk_map_rgb(g, tables, z, rz);
    dvvk_map_rgb(g, tables, top, rt);
    out_codes(rz, cz);
    out_codes(rt, ct);
    printf("  signal black -> codes %.3f %.3f %.3f; the curve's peak -> %.3f %.3f %.3f\n", cz[0], cz[1], cz[2], ct[0],
           ct[1], ct[2]);
    for (int k = 0; k < 3; k++) {
        if (floor(cz[k] + 0.5) != g->out_code[1]) {
            printf("    BLACK NOT AT CODE %g\n", g->out_code[1]);
            bad = 1;
        }
        if (floor(ct[k] + 0.5) != g->out_code[0] + g->out_code[1]) {
            printf("    PEAK NOT AT WHITE\n");
            bad = 1;
        }
    }
    printf("  ramp checks: %s\n", bad ? "FAILED" : "ok");
    return bad;
}

int main(int argc, char **argv)
{
    int n = 65, samples = 200000, do_ramp = 0, do_rgb = 0, no_l1 = 0, l9 = -1, no_l6 = 0;
    const char *frame = NULL, *outpath = NULL, *src = NULL, *l1 = NULL, *overlay = NULL;
    dvvk_output_mode mode = {.mode = DVVK_OUTPUT_HDR10};
    int i = 1, failed = 0;
    for (; i < argc && argv[i][0] == '-'; i++) {
        if (!strcmp(argv[i], "--n") && i + 1 < argc)
            n = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--samples") && i + 1 < argc)
            samples = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--frame") && i + 1 < argc)
            frame = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc)
            outpath = argv[++i];
        else if (!strcmp(argv[i], "--overlay") && i + 1 < argc)
            overlay = argv[++i];
        else if (!strcmp(argv[i], "--output") && i + 1 < argc)
            mode.mode = !strcmp(argv[++i], "sdr") ? DVVK_OUTPUT_SDR : DVVK_OUTPUT_HDR10;
        else if (!strcmp(argv[i], "--white") && i + 1 < argc)
            mode.peak_nits = (float)atof(argv[++i]);
        else if (!strcmp(argv[i], "--black") && i + 1 < argc)
            mode.min_nits = (float)atof(argv[++i]);
        else if (!strcmp(argv[i], "--gamma22"))
            mode.flags |= DVVK_SDR_GAMMA22;
        else if (!strcmp(argv[i], "--limited"))
            mode.flags |= DVVK_SDR_LIMITED;
        else if (!strcmp(argv[i], "--no-dither"))
            mode.flags |= DVVK_SDR_NO_DITHER;
        else if (!strcmp(argv[i], "--src") && i + 1 < argc)
            src = argv[++i];
        else if (!strcmp(argv[i], "--l1") && i + 1 < argc)
            l1 = argv[++i];
        else if (!strcmp(argv[i], "--no-l1"))
            no_l1 = 1;
        else if (!strcmp(argv[i], "--no-l6"))
            no_l6 = 1;
        else if (!strcmp(argv[i], "--l9") && i + 1 < argc)
            l9 = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--ramp"))
            do_ramp = 1;
        else if (!strcmp(argv[i], "--rgb"))
            do_rgb = 1;
        else
            return fprintf(stderr, "unknown option %s\n", argv[i]), 2;
    }
    const int sdr = mode.mode == DVVK_OUTPUT_SDR;
    uint32_t *words = malloc(sizeof(uint32_t) * DVVK_MAP_TABLE_WORDS);
    uint64_t have_gamut = 0;
    for (; i < argc; i++) {
        size_t size;
        void *md = load(argv[i], &size);
        if (!md) {
            fprintf(stderr, "%s: can't read\n", argv[i]);
            return 1;
        }
        edit(md, src, l1, no_l1, l9, no_l6);
        static dvvk_map map;
        int r = dvvk_map_plan(&mode, md, size, &map);
        printf("%s: plan %d flags %#x key %016llx\n", argv[i], r, map.gpu.flags, (unsigned long long)map.key);
        if (r)
            continue;
        g = &map.gpu;
        tables = words;
        if (sdr && (!have_gamut || have_gamut != map.gamut_key)) {
            struct timespec t0, t1;
            clock_gettime(CLOCK_MONOTONIC, &t0);
            dvvk_map_tables(&map, words);
            clock_gettime(CLOCK_MONOTONIC, &t1);
            printf("  tables: gamut key %016llx, input primaries R %.4f,%.4f G %.4f,%.4f B %.4f,%.4f, %.1f ms\n",
                   (unsigned long long)map.gamut_key, map.gamut_prim[0][0], map.gamut_prim[0][1],
                   map.gamut_prim[0][2], map.gamut_prim[0][3], map.gamut_prim[0][4], map.gamut_prim[0][5],
                   (t1.tv_sec - t0.tv_sec) * 1e3 + (t1.tv_nsec - t0.tv_nsec) / 1e6);
            have_gamut = map.gamut_key;
        }
        /* the stream's black as yblod/plan.c has it (dvvk_plan.black): the
         * RPU's offsets as 12-bit codes */
        uint32_t stream_black[3];
        for (int k = 0; k < 3; k++)
            stream_black[k] = (uint32_t)floor(av_q2d(av_dovi_get_color((AVDOVIMetadata *)md)->ycc_to_rgb_offset[k]) *
                                              4096.0 + 1e-9);
        dvvk_map_set_black(&map.gpu, words, stream_black);
        printf("  tone in %.5f..%.5f out %.5f..%.5f (PQ); signal max %u min %u (1e-4) prim R %u,%u\n",
               g->tone_in[0], g->tone_in[1], g->tone_out[0], g->tone_out[1], map.signal.max_luminance,
               map.signal.min_luminance, map.signal.primaries[0][0], map.signal.primaries[0][1]);
        if (g->flags & 1)
            printf("  lut[0] %.5f lut[64] %.5f lut[128] %.5f lut[192] %.5f lut[255] %.5f\n", g->tone_lut[0],
                   g->tone_lut[64], g->tone_lut[128], g->tone_lut[192], g->tone_lut[255]);
        printf("  ycc %.5f %.5f %.5f / %.5f %.5f %.5f / %.5f %.5f %.5f off %.5f %.5f %.5f\n", g->ycc[0], g->ycc[1],
               g->ycc[2], g->ycc[4], g->ycc[5], g->ycc[6], g->ycc[8], g->ycc[9], g->ycc[10], g->ycc_offset[0],
               g->ycc_offset[1], g->ycc_offset[2]);
        if (sdr)
            printf("  display: V = pow(max(%.6g L + %.6g, 0), %.5f) - %.6g; codes %g V + %g; gamut I at %.5f I + %.5f\n",
                   g->out_trc[0], g->out_trc[1], g->out_trc[2], g->out_trc[3], g->out_code[0], g->out_code[1],
                   g->gamut_at[0], g->gamut_at[1]);
        if (do_ramp && sdr)
            failed |= ramp();
        if (do_rgb && sdr) {
            double nl[3], rgb[3];
            while (scanf("%lf %lf %lf", &nl[0], &nl[1], &nl[2]) == 3) {
                dvvk_map_rgb(g, tables, nl, rgb);
                printf("%.9g %.9g %.9g  %u %u %u\n", shown(rgb[0]), shown(rgb[1]), shown(rgb[2]),
                       (unsigned)floor(g->out_code[0] * rgb[0] + 0.5), (unsigned)floor(g->out_code[0] * rgb[1] + 0.5),
                       (unsigned)floor(g->out_code[0] * rgb[2] + 0.5));
            }
            free(md);
            continue;
        }
        /* the LUT: node values, then trilinear against the exact mapping */
        double *lut = malloc(sizeof(double) * 3 * n * n * n);
        for (int z = 0; z < n; z++)
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++) {
                    double c[3] = {x / (n - 1.0), y / (n - 1.0), z / (n - 1.0)};
                    dvvk_map_rgb(g, tables, c, lut + 3 * ((size_t)(z * n + y) * n + x));
                }
        /* cells whose interpolation misses the exact value by more than
         * THRESH codes at the centre or a face centre */
        double thresh = getenv("THRESH") ? atof(getenv("THRESH")) : sdr ? 0.35 : 0.5;
        int m = n - 1;
        unsigned char *cellf = calloc((size_t)m * m * m, 1);
        long flagged_nodes = 0;
        /* the bake's points: the cell's centre and its faces' centres; with
         * DVVK_MAP_SDR its edges' centres too (map_bake.comp) */
        static const double pts[19][3] = {{.5, .5, .5}, {0, .5, .5}, {1, .5, .5}, {.5, 0, .5}, {.5, 1, .5}, {.5, .5, 0},
                                          {.5, .5, 1}, {.5, 0, 0}, {.5, 1, 0}, {.5, 0, 1}, {.5, 1, 1}, {0, .5, 0},
                                          {1, .5, 0}, {0, .5, 1}, {1, .5, 1}, {0, 0, .5}, {1, 0, .5}, {0, 1, .5},
                                          {1, 1, .5}};
        const int npts = getenv("POINTS") ? atoi(getenv("POINTS")) : sdr ? 19 : 7;
        for (int z = 0; z < m; z++)
            for (int y = 0; y < m; y++)
                for (int x = 0; x < m; x++) {
                    double err = 0;
                    for (int q = 0; q < npts && err <= thresh; q++) {
                        double nl[3] = {(x + pts[q][0]) / m, (y + pts[q][1]) / m, (z + pts[q][2]) / m}, ex[3], li[3] = {0};
                        dvvk_map_rgb(g, tables, nl, ex);
                        for (int corner = 0; corner < 8; corner++) {
                            int dx = corner & 1, dy = (corner >> 1) & 1, dz = corner >> 2;
                            double wgt = (dx ? pts[q][0] : 1 - pts[q][0]) * (dy ? pts[q][1] : 1 - pts[q][1]) * (dz ? pts[q][2] : 1 - pts[q][2]);
                            const double *v = lut + 3 * ((size_t)((z + dz) * n + y + dy) * n + x + dx);
                            for (int k = 0; k < 3; k++)
                                li[k] += wgt * v[k];
                        }
                        double a[3], b[3];
                        out_codes(ex, a);
                        out_codes(li, b);
                        for (int k = 0; k < 3; k++)
                            err = fmax(err, fabs(a[k] - b[k]));
                    }
                    if (err > thresh) {
                        cellf[(z * m + y) * m + x] = 1;
                        flagged_nodes++;
                    }
                }
        long exact_samples = 0;
        double worst[3] = {0}, sum[3] = {0};
        long over1[3] = {0};
        srand(1);
        for (int s = 0; s < samples; s++) {
            /* plausible signals: luma anywhere, chroma near neutral mostly */
            double c[3] = {rand() % 4096, 2048 + (rand() % 1600 - 800) * ((s & 3) ? 0.3 : 1.0),
                           2048 + (rand() % 1600 - 800) * ((s & 3) ? 0.3 : 1.0)};
            double exact[3], lerp[3] = {0}, a[3], b[3], nl[3];
            dvvk_map_nonlinear(g, c, nl);
            dvvk_map_rgb(g, tables, nl, exact);
            double f[3];
            int i0[3];
            for (int k = 0; k < 3; k++) {
                double t = nl[k] * (n - 1);
                i0[k] = (int)fmin(floor(t), n - 2);
                f[k] = t - i0[k];
            }
            int any_flag = cellf[(i0[2] * m + i0[1]) * m + i0[0]];
            for (int corner = 0; corner < 8; corner++) {
                int dx = corner & 1, dy = (corner >> 1) & 1, dz = corner >> 2;
                double wgt = (dx ? f[0] : 1 - f[0]) * (dy ? f[1] : 1 - f[1]) * (dz ? f[2] : 1 - f[2]);
                const double *v = lut + 3 * ((size_t)((i0[2] + dz) * n + i0[1] + dy) * n + i0[0] + dx);
                for (int k = 0; k < 3; k++)
                    lerp[k] += wgt * v[k];
            }
            if (any_flag && !getenv("NOFLAG")) {
                exact_samples++;
                memcpy(lerp, exact, sizeof(lerp));
            }
            out_codes(exact, a);
            out_codes(lerp, b);
            for (int k = 0; k < 3; k++) {
                double d = fabs(a[k] - b[k]);
                if (d > worst[k] && getenv("WORST"))
                    printf("    worst %d: codes %.0f %.0f %.0f nl %.4f %.4f %.4f exact %.1f %.1f %.1f lut %.1f %.1f %.1f\n", k,
                           c[0], c[1], c[2], nl[0], nl[1], nl[2], a[0], a[1], a[2], b[0], b[1], b[2]);
                worst[k] = fmax(worst[k], d);
                sum[k] += d;
                over1[k] += d > 1.0;
            }
        }
        const char *names[3] = {sdr ? "R" : "Y", sdr ? "G" : "Cb", sdr ? "B" : "Cr"};
        printf("  LUT %d^3 trilinear vs exact, %s codes: %s max %.2f mean %.3f >1: %ld; %s max %.2f mean %.3f "
               ">1: %ld; %s max %.2f mean %.3f >1: %ld (of %d)\n",
               n, sdr ? "output" : "12-bit", names[0], worst[0], sum[0] / samples, over1[0], names[1], worst[1],
               sum[1] / samples, over1[1], names[2], worst[2], sum[2] / samples, over1[2], samples);
        printf("  flagged cells %.2f%%, samples computed exactly %.2f%%\n", 100.0 * flagged_nodes / ((double)m * m * m),
               100.0 * exact_samples / samples);
        if (frame) {
            /* a DV tunnel dump (dvvk-bench --dump, output dv): its 12-bit
             * 4:2:2 codes, each pixel with its pair's chroma */
            size_t fsize;
            unsigned char *fb = load(frame, &fsize);
            size_t stride = fsize / 2160;
            long px = 0, exact_px = 0, over[4] = {0};
            double lut_worst = 0, noflag_worst = 0;
            long cell_hist[8] = {0};
            for (int y = 8; y < 2160; y++)   /* packet rows left out */
                for (int x = 0; x < 3840; x += 2) {
                    const unsigned char *p = fb + y * stride + 4 * x;
                    int y0 = (p[1] << 4) | (p[0] & 15), cb = (p[2] << 4) | (p[0] >> 4);
                    int y1 = (p[5] << 4) | (p[4] & 15), cr = (p[6] << 4) | (p[4] >> 4);
                    int ys[2] = {y0, y1};
                    for (int l = 0; l < 2; l++) {
                        double c[3] = {ys[l], cb, cr}, nl[3], exact[3], lerp[3] = {0}, f[3], a[3], b[3];
                        int i0[3];
                        dvvk_map_nonlinear(g, c, nl);
                        dvvk_map_rgb(g, tables, nl, exact);
                        for (int k = 0; k < 3; k++) {
                            double t = nl[k] * (n - 1);
                            i0[k] = (int)fmin(floor(t), n - 2);
                            f[k] = t - i0[k];
                        }
                        int fl = cellf[(i0[2] * m + i0[1]) * m + i0[0]];
                        for (int corner = 0; corner < 8; corner++) {
                            int dx = corner & 1, dy = (corner >> 1) & 1, dz = corner >> 2;
                            double wgt = (dx ? f[0] : 1 - f[0]) * (dy ? f[1] : 1 - f[1]) * (dz ? f[2] : 1 - f[2]);
                            const double *v = lut + 3 * ((size_t)((i0[2] + dz) * n + i0[1] + dy) * n + i0[0] + dx);
                            for (int k = 0; k < 3; k++)
                                lerp[k] += wgt * v[k];
                        }
                        out_codes(exact, a);
                        out_codes(lerp, b);
                        double e = fmax(fabs(a[0] - b[0]), fmax(fabs(a[1] - b[1]), fabs(a[2] - b[2])));
                        lut_worst = fmax(lut_worst, e);
                        if (!fl)
                            noflag_worst = fmax(noflag_worst, e);
                        over[0] += e > 0.25;
                        over[1] += e > 0.5;
                        over[2] += e > 1;
                        over[3] += e > 2;
                        px++;
                        exact_px += fl;
                        int band = (int)fmin(7, nl[0] * 8);
                        if (fl)
                            cell_hist[band]++;
                    }
                }
            printf("  frame %s: %ld px, in flagged cells %.2f%%; LUT-only error worst %.2f, >0.25 %.3f%% >0.5 %.3f%% >1 "
                   "%.3f%% >2 %.3f%%; worst outside flagged cells %.2f\n",
                   frame, px, 100.0 * exact_px / px, lut_worst, 100.0 * over[0] / px, 100.0 * over[1] / px,
                   100.0 * over[2] / px, 100.0 * over[3] / px, noflag_worst);
            printf("  flagged by R' band (eighths): %ld %ld %ld %ld %ld %ld %ld %ld\n", cell_hist[0], cell_hist[1],
                   cell_hist[2], cell_hist[3], cell_hist[4], cell_hist[5], cell_hist[6], cell_hist[7]);
            if (outpath) {
                /* the frame mapped exactly on the CPU, in the engine's output bytes */
                unsigned char *o = malloc(fsize);
                memcpy(o, fb, fsize);
                size_t lsize = 0;
                unsigned char *layer = overlay ? load(overlay, &lsize) : NULL;
                if (overlay && (!layer || lsize < (size_t)3840 * 2160 * 4))
                    return fprintf(stderr, "%s: can't read a 3840x2160 BGRA overlay\n", overlay), 1;
                for (int y = 0; y < 2160; y++)
                    for (int x = 0; x < 3840; x += 2) {
                        unsigned char *p = o + y * stride + 4 * x;
                        const unsigned char *q = fb + y * stride + 4 * x;
                        int y0 = (q[1] << 4) | (q[0] & 15), cb = (q[2] << 4) | (q[0] >> 4);
                        int y1 = (q[5] << 4) | (q[4] & 15), cr = (q[6] << 4) | (q[4] >> 4);
                        double c0[3] = {y0, cb, cr}, c1[3] = {y1, cb, cr}, a[3], b[3], ca[3], cbb[3];
                        dvvk_map_sample(g, tables, c0, a);
                        dvvk_map_sample(g, tables, c1, b);
                        if (sdr) {
                            /* XRGB8888: B, G, R, 0xff. The stream's black is
                             * its exact code; the layer (premultiplied, its
                             * colour at most its alpha, as the pack reads it)
                             * goes over the unrounded codes. */
                            for (int l = 0; l < 2; l++) {
                                const double *v = l ? b : a;
                                const int yy = l ? y1 : y0;
                                const int is_black = (uint32_t)yy == g->black_in[0] && (uint32_t)cb == g->black_in[1] &&
                                                     (uint32_t)cr == g->black_in[2];
                                const unsigned char *lp = layer ? layer + ((size_t)y * 3840 + x + l) * 4 : NULL;
                                for (int k = 0; k < 3; k++) {
                                    double c = is_black ? (double)g->black_out[k] : g->out_code[0] * v[k] + g->out_code[1];
                                    if (lp && lp[3]) {
                                        double al = lp[3] / 255.0, col = (lp[2 - k] < lp[3] ? lp[2 - k] : lp[3]) / 255.0;
                                        c = (g->out_code[0] * col + g->out_code[1] * al) + (1.0 - al) * c;
                                    }
                                    /* back to dvvk_map_sdr_code's R'G'B' */
                                    p[4 * l + 2 - k] = (unsigned char)dvvk_map_sdr_code(
                                        g, tables, (c - g->out_code[1]) / g->out_code[0], (uint32_t)(x + l), (uint32_t)y);
                                }
                            }
                            p[3] = p[7] = 0xff;
                            continue;
                        }
                        ca[0] = 256.0 + 3504.0 * a[0];
                        ca[1] = 2048.0 + 3584.0 * a[1];
                        ca[2] = 2048.0 + 3584.0 * a[2];
                        cbb[0] = 256.0 + 3504.0 * b[0];
                        int Y0 = (int)floor(ca[0] + .5), Cb = (int)floor(ca[1] + .5), Cr = (int)floor(ca[2] + .5),
                            Y1 = (int)floor(cbb[0] + .5);
                        int v[2][2] = {{Y0, Cb}, {Y1, Cr}};
                        for (int l = 0; l < 2; l++) {
                            int yy = v[l][0], cc = v[l][1];
                            p[4 * l] = (unsigned char)(((cc & 15) << 4) | (yy & 15));
                            p[4 * l + 1] = (unsigned char)(yy >> 4);
                            p[4 * l + 2] = (unsigned char)(cc >> 4);
                        }
                    }
                FILE *f = fopen(outpath, "wb");
                fwrite(o, 1, fsize, f);
                fclose(f);
                free(o);
                free(layer);
            }
            free(fb);
        }
        free(cellf);
        free(lut);
        free(md);
    }
    free(words);
    return failed;
}
