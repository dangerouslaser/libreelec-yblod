/* The LLDV pack against CroqueMr's own: CB1's AVX2 player-led pack
 * (tools/cb1/cb1_lldv_cpu.c, unchanged, CB1/src at b5149a09d7) on the same
 * linear picture as the engine's pack definition (dvvk-map-test's LLDV
 * reference), and on the engine's GPU dump. Test tool, not built with the
 * engine (x86-64 with AVX2; tools.sh doesn't build it):
 *
 *   gcc -O2 -std=gnu11 -I../include -I../yblod/placebo -I../yblod/placebo/include \
 *     $(pkg-config --cflags libavutil) -o dvvk-lldv-oracle dvvk-lldv-oracle.c \
 *     ../yblod/dv_map.c ../yblod/placebo/{common,colorspace,tone_mapping,gamut_mapping}.c \
 *     cb1/cb1_lldv_cpu.c -lpthread -lm -w
 *
 *   dvvk-lldv-oracle [dvvk-map-test's display options] [--overlay FILE] [--active X0,Y0,X1,Y1]
 *       --frame DV.dump [--gpu LLDV.dump] FIXTURE.bin
 *
 * From the tunnel picture (dvvk-bench --dump, the reconstructed codes) and its
 * metadata it makes, in double precision, the picture CB1's player-led
 * renderer hands its pack: each pixel's light in the display's primaries,
 * 0..1 of its peak (dvvk_map_expert_display, black outside the active area,
 * the overlay blended as player_led_gui), stored as RGBA32F. Then:
 *   A  cb1_lldv_cpu_submit on that picture (lldv_matrix, peak, bits, XRGB)
 *   B  the engine's pack definition on the same floats (dvvk_map_lldv_encode,
 *      BT.2020 Y'CbCr, the 1-2-1 chroma at the even pixel, the carrier grid)
 * and counts, per channel, the samples where A and B differ and by how much
 * (A's PQ is CB1's 22-bit table, B's the curve itself), and, with --gpu, the
 * GPU's bytes against A. Rows 24.. (the tunnel dump's first rows carry its
 * packets). 3840x2160 only (cb1_lldv_cpu's). */
#include "../include/dvvk_map.h"
#include "cb1/cb1_lldv_cpu.h"
#include <libavutil/dovi_meta.h>
#include "../../src/dvbridge_policy.c"
#include "../../src/dvbridge_placebo.c"
#include "../../src/dvbridge_creative.c"
#include "../../src/cb1_hdr10_expert.c"
#include "../yblod/placebo/libav_dovi.c"
#include "../yblod/placebo/cb1_expert_tone.c"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { W = 3840, H = 2160 };

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

static void unpack(const unsigned char *d, size_t stride, int x, int y, int *yy, int *c)
{
    const unsigned char *p = d + y * stride + 4 * x;
    *yy = (p[1] << 4) | (p[0] & 15);
    *c = (p[2] << 4) | (p[0] >> 4);
}

/* the differences of two carrier pictures (12-bit codes), per channel */
static void compare(const char *what, const uint32_t *a, size_t astride, const unsigned char *b, size_t bstride)
{
    long n[3] = {0}, diff[3] = {0}, hist[3][5] = {{0}};
    int worst[3] = {0};
    for (int y = 24; y < H; y++)
        for (int x = 0; x < W; x++) {
            int ya, ca, yb, cb;
            unpack((const unsigned char *)a, astride, x, y, &ya, &ca);
            unpack(b, bstride, x, y, &yb, &cb);
            const int d[2] = {abs(ya - yb), abs(ca - cb)}, ch[2] = {0, 1 + (x & 1)};
            for (int k = 0; k < 2; k++) {
                n[ch[k]]++;
                diff[ch[k]] += d[k] != 0;
                hist[ch[k]][d[k] > 4 ? 4 : d[k]]++;
                if (d[k] > worst[ch[k]])
                    worst[ch[k]] = d[k];
            }
        }
    static const char *names[3] = {"Y", "Cb", "Cr"};
    for (int c = 0; c < 3; c++)
        printf("  %s %-2s: %ld of %ld samples differ (%.4f%%), max %d codes; by 1: %ld, 2: %ld, 3: %ld, 4+: %ld\n", what,
               names[c], diff[c], n[c], 100.0 * diff[c] / n[c], worst[c], hist[c][1], hist[c][2], hist[c][3], hist[c][4]);
}

int main(int argc, char **argv)
{
    dvvk_output_mode mode = {.mode = DVVK_OUTPUT_LLDV, .peak_nits = 1000.0f};
    dvvk_display_primaries display = {0};
    const char *frame = NULL, *gpu = NULL, *overlay = NULL, *fixture = NULL;
    int given[4] = {-1, -1, -1, -1};
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--output") && i + 1 < argc)
            i++;   /* lldv: dvvk-map-test's spelling */
        else if (!strcmp(argv[i], "--peak") && i + 1 < argc)
            mode.peak_nits = (float)atof(argv[++i]);
        else if (!strcmp(argv[i], "--black") && i + 1 < argc)
            mode.min_nits = (float)atof(argv[++i]);
        else if (!strcmp(argv[i], "--gamut") && i + 1 < argc) {
            i++;
            mode.reserved[DVVK_TARGET_GAMUT_WORD] = !strcmp(argv[i], "709") ? DVVK_GAMUT_BT709
                                                    : !strcmp(argv[i], "p3") ? DVVK_GAMUT_P3D65
                                                                             : DVVK_GAMUT_BT2020;
        } else if (!strcmp(argv[i], "--primaries") && i + 1 < argc) {
            float *xy = &display.xy[0][0];
            if (sscanf(argv[++i], "%f,%f,%f,%f,%f,%f", xy, xy + 1, xy + 2, xy + 3, xy + 4, xy + 5) != 6)
                return fprintf(stderr, "--primaries rx,ry,gx,gy,bx,by\n"), 2;
            if (!display.edid_version)
                display.edid_version = 2;
        } else if (!strcmp(argv[i], "--edid-version") && i + 1 < argc)
            display.edid_version = (uint32_t)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--bits") && i + 1 < argc)
            mode.flags = atoi(argv[++i]) == 10 ? DVVK_LLDV_10BIT : 0;
        else if (!strcmp(argv[i], "--frame") && i + 1 < argc)
            frame = argv[++i];
        else if (!strcmp(argv[i], "--gpu") && i + 1 < argc)
            gpu = argv[++i];
        else if (!strcmp(argv[i], "--overlay") && i + 1 < argc)
            overlay = argv[++i];
        else if (!strcmp(argv[i], "--active") && i + 1 < argc)
            sscanf(argv[++i], "%d,%d,%d,%d", &given[0], &given[1], &given[2], &given[3]);
        else if (argv[i][0] != '-')
            fixture = argv[i];
        else
            return fprintf(stderr, "unknown option %s\n", argv[i]), 2;
    }
    if (!frame || !fixture)
        return fprintf(stderr, "usage: dvvk-lldv-oracle [display options] --frame DV.dump [--gpu LLDV.dump] FIXTURE.bin\n"), 2;
    size_t msize, fsize, lsize = 0, gsize = 0;
    void *md = load(fixture, &msize);
    unsigned char *fb = load(frame, &fsize), *layer = overlay ? load(overlay, &lsize) : NULL,
                  *gb = gpu ? load(gpu, &gsize) : NULL;
    if (!md || !fb || fsize < (size_t)W * H * 4 || (overlay && lsize < (size_t)W * H * 4) ||
        (gpu && gsize < (size_t)W * H * 4))
        return fprintf(stderr, "can't read the inputs\n"), 1;
    const size_t stride = fsize / H;
    static dvvk_map map;
    if (dvvk_map_plan_display(&mode, &display, md, msize, &map))
        return fprintf(stderr, "%s: no LLDV plan\n", fixture), 1;
    const dvvk_map_gpu *g = &map.gpu;
    uint32_t *tables = malloc(sizeof(uint32_t) * DVVK_MAP_TABLE_WORDS);
    if (g->flags & DVVK_MAP_GAMUT)
        dvvk_map_tables(&map, tables);
    int area[4] = {0, 0, W, H};
    if (given[0] >= 0)
        memcpy(area, given, sizeof(area));
    else
        for (int i = 0; i < ((AVDOVIMetadata *)md)->num_ext_blocks; i++) {
            const AVDOVIDmData *e = av_dovi_get_ext(md, i);
            if (e->level == 5) {
                area[0] = e->l5.left_offset;
                area[1] = e->l5.top_offset;
                area[2] = W - e->l5.right_offset;
                area[3] = H - e->l5.bottom_offset;
            }
        }
    printf("%s: LLDV %.6g cd/m2, black %.6g, %u bits, EDID %u, flags %#x, expert %#x; active %d,%d..%d,%d\n", fixture,
           mode.peak_nits, mode.min_nits, g->ex_bits, display.edid_version, g->flags, g->ex_flags, area[0], area[1],
           area[2], area[3]);
    /* the picture CB1's pack takes: RGBA32F, the display's linear light 0..1 of its peak */
    float *linear = malloc(sizeof(float) * 4 * W * H);
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            const unsigned char *q = fb + y * stride + 4 * (x & ~1);
            const double c[3] = {(q[4 * (x & 1) + 1] << 4) | (q[4 * (x & 1)] & 15), (q[2] << 4) | (q[0] >> 4),
                                 (q[6] << 4) | (q[4] >> 4)};
            double nl[3], v[3] = {0, 0, 0};
            if (x >= area[0] && x < area[2] && y >= area[1] && y < area[3]) {
                dvvk_map_nonlinear(g, c, nl);
                dvvk_map_expert_display(g, tables, nl, v);
            }
            if (layer) {
                const unsigned char *lp = layer + ((size_t)y * W + x) * 4;
                const uint8_t rgba[4] = {lp[2], lp[1], lp[0], lp[3]};
                dvvk_map_lldv_gui(g, rgba, v);
            }
            float *o = linear + 4 * ((size_t)y * W + x);
            o[0] = (float)v[0], o[1] = (float)v[1], o[2] = (float)v[2], o[3] = 1.0f;
        }
    /* A: CB1's pack */
    const size_t cstride = W * 4;
    uint32_t *a = aligned_alloc(32, cstride * H);
    float to2020[9];
    int identity = 1;
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++) {
            to2020[3 * i + j] = g->ex_out[4 * i + j];
            identity &= g->ex_out[4 * i + j] == (i == j);
        }
    struct cb1_lldv_cpu *cpu = cb1_lldv_cpu_create(4);
    if (!cpu)
        return fprintf(stderr, "cb1_lldv_cpu_create failed (x86-64 with AVX2 only)\n"), 77;
    const struct cb1_lldv_cpu_frame cf = {.linear = linear, .carrier = a, .stride = cstride,
                                          .to_bt2020 = identity ? NULL : to2020,
                                          .peak_nits = mode.peak_nits, .bits = g->ex_bits, .xrgb = true};
    if (!cb1_lldv_cpu_submit(cpu, &cf) || !cb1_lldv_cpu_ready(cpu, true))
        return fprintf(stderr, "cb1_lldv_cpu_submit failed\n"), 1;
    cb1_lldv_cpu_destroy(cpu);
    /* B: the engine's pack definition on the same floats */
    unsigned char *b = malloc(cstride * H);
    double *ycc = malloc(sizeof(double) * 3 * W);
    const double step = (double)(1u << (12 - g->ex_bits));
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            const float *p = linear + 4 * ((size_t)y * W + x);
            const double v[3] = {p[0], p[1], p[2]};
            double pq[3];
            dvvk_map_lldv_encode(g, v, pq);
            dvvk_map_ycc(pq, ycc + 3 * x);
        }
        for (int x = 0; x < W; x += 2) {
            const double *e = ycc + 3 * x, *od = ycc + 3 * (x + 1), *l = ycc + 3 * (x ? x - 1 : 0);
            const double cbf = (l[1] + 2.0 * e[1] + od[1]) * 0.25, crf = (l[2] + 2.0 * e[2] + od[2]) * 0.25;
            const double code[4] = {256.0 + 3504.0 * fmin(fmax(e[0], 0.0), 1.0), 2048.0 + 3584.0 * fmin(fmax(cbf, -0.5), 0.5),
                                    256.0 + 3504.0 * fmin(fmax(od[0], 0.0), 1.0), 2048.0 + 3584.0 * fmin(fmax(crf, -0.5), 0.5)};
            for (int k = 0; k < 2; k++) {
                const int yy = (int)(floor(code[2 * k] / step + 0.5) * step), cc = (int)(floor(code[2 * k + 1] / step + 0.5) * step);
                unsigned char *o = b + y * cstride + 4 * (x + k);
                o[0] = (unsigned char)(((cc & 15) << 4) | (yy & 15));
                o[1] = (unsigned char)(yy >> 4);
                o[2] = (unsigned char)(cc >> 4);
                o[3] = 0xff;
            }
        }
    }
    compare("CB1's pack vs the engine's (same linear input)", a, cstride, b, cstride);
    if (gb)
        compare("CB1's pack vs the GPU", a, cstride, gb, gsize / H);
    return 0;
}
