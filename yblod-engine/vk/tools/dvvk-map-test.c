/* The output colour mapping's CPU half on metadata fixtures
 * (yblod/fixtures/*.bin, AVDOVIMetadata as dvvk-bench --metadata writes
 * them): what dvvk_map_plan decides, and how far a 3D LUT of N points per
 * axis (trilinear, as the pack samples it) is from the exact mapping over
 * random 12-bit Y'CbCr, in 12-bit output codes.
 *
 *   dvvk-map-test [--n N] [--samples K] FIXTURE.bin...
 */
#include "../include/dvvk_map.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

/* 12-bit limited-range codes of a Y'CbCr sample */
static void codes12(const double ycc[3], double c[3])
{
    c[0] = 256.0 + 3504.0 * ycc[0];
    c[1] = 2048.0 + 3584.0 * ycc[1];
    c[2] = 2048.0 + 3584.0 * ycc[2];
}

int main(int argc, char **argv)
{
    int n = 65, samples = 200000;
    const char *frame = NULL, *outpath = NULL;
    int i = 1;
    for (; i < argc && argv[i][0] == '-'; i++) {
        if (!strcmp(argv[i], "--n") && i + 1 < argc)
            n = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--samples") && i + 1 < argc)
            samples = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--frame") && i + 1 < argc)
            frame = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc)
            outpath = argv[++i];
    }
    for (; i < argc; i++) {
        size_t size;
        void *md = load(argv[i], &size);
        if (!md) {
            fprintf(stderr, "%s: can't read\n", argv[i]);
            return 1;
        }
        dvvk_output_mode mode = {.mode = DVVK_OUTPUT_HDR10};
        dvvk_map map;
        int r = dvvk_map_plan(&mode, md, size, &map);
        printf("%s: plan %d flags %#x key %016llx\n", argv[i], r, map.gpu.flags, (unsigned long long)map.key);
        if (r)
            continue;
        const dvvk_map_gpu *g = &map.gpu;
        printf("  tone in %.5f..%.5f out %.5f..%.5f (PQ); signal max %u min %u (1e-4) prim R %u,%u\n",
               g->tone_in[0], g->tone_in[1], g->tone_out[0], g->tone_out[1], map.signal.max_luminance,
               map.signal.min_luminance, map.signal.primaries[0][0], map.signal.primaries[0][1]);
        if (g->flags & 1)
            printf("  lut[0] %.5f lut[64] %.5f lut[128] %.5f lut[192] %.5f lut[255] %.5f\n", g->tone_lut[0],
                   g->tone_lut[64], g->tone_lut[128], g->tone_lut[192], g->tone_lut[255]);
        printf("  ycc %.5f %.5f %.5f / %.5f %.5f %.5f / %.5f %.5f %.5f off %.5f %.5f %.5f\n", g->ycc[0], g->ycc[1],
               g->ycc[2], g->ycc[4], g->ycc[5], g->ycc[6], g->ycc[8], g->ycc[9], g->ycc[10], g->ycc_offset[0],
               g->ycc_offset[1], g->ycc_offset[2]);
        /* the LUT: node values, then trilinear against the exact mapping */
        double *lut = malloc(sizeof(double) * 3 * n * n * n);
        uint32_t *reg = malloc(sizeof(uint32_t) * n * n * n);
        unsigned char *flag = calloc(n * n * n, 1);
        for (int z = 0; z < n; z++)
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++) {
                    double c[3] = {x / (n - 1.0), y / (n - 1.0), z / (n - 1.0)};
                    reg[(z * n + y) * n + x] = dvvk_map_rgb(g, c, lut + 3 * ((size_t)(z * n + y) * n + x));
                }
        /* cells whose interpolation misses the exact value by more than
         * THRESH codes at the centre or a face centre */
        double thresh = getenv("THRESH") ? atof(getenv("THRESH")) : 0.5;
        int m = n - 1;
        unsigned char *cellf = calloc((size_t)m * m * m, 1);
        long flagged_nodes = 0;
        static const double pts[7][3] = {{.5, .5, .5}, {0, .5, .5}, {1, .5, .5}, {.5, 0, .5}, {.5, 1, .5}, {.5, .5, 0}, {.5, .5, 1}};
        for (int z = 0; z < m; z++)
            for (int y = 0; y < m; y++)
                for (int x = 0; x < m; x++) {
                    double err = 0;
                    for (int q = 0; q < 7 && err <= thresh; q++) {
                        double nl[3] = {(x + pts[q][0]) / m, (y + pts[q][1]) / m, (z + pts[q][2]) / m}, ex[3], li[3] = {0};
                        dvvk_map_rgb(g, nl, ex);
                        for (int corner = 0; corner < 8; corner++) {
                            int dx = corner & 1, dy = (corner >> 1) & 1, dz = corner >> 2;
                            double wgt = (dx ? pts[q][0] : 1 - pts[q][0]) * (dy ? pts[q][1] : 1 - pts[q][1]) * (dz ? pts[q][2] : 1 - pts[q][2]);
                            const double *v = lut + 3 * ((size_t)((z + dz) * n + y + dy) * n + x + dx);
                            for (int k = 0; k < 3; k++)
                                li[k] += wgt * v[k];
                        }
                        double a[3], b[3], ya[3], yb[3];
                        dvvk_map_ycc(ex, ya);
                        dvvk_map_ycc(li, yb);
                        codes12(ya, a);
                        codes12(yb, b);
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
            dvvk_map_sample(g, c, exact);
            dvvk_map_nonlinear(g, c, nl);
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
            double ycc[3];
            dvvk_map_ycc(lerp, ycc);
            if (any_flag && !getenv("NOFLAG")) {
                exact_samples++;
                memcpy(ycc, exact, sizeof(ycc));
            }
            codes12(exact, a);
            codes12(ycc, b);
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
        printf("  LUT %d^3 trilinear vs exact, 12-bit codes: Y max %.2f mean %.3f >1: %ld; Cb max %.2f mean %.3f "
               ">1: %ld; Cr max %.2f mean %.3f >1: %ld (of %d)\n",
               n, worst[0], sum[0] / samples, over1[0], worst[1], sum[1] / samples, over1[1], worst[2],
               sum[2] / samples, over1[2], samples);
        printf("  flagged cells %.2f%%, samples computed exactly %.2f%%\n", 100.0 * flagged_nodes / ((double)m * m * m),
               100.0 * exact_samples / samples);
        if (frame) {
            /* a DV tunnel dump (dvvk-bench --dump, output dv): its 12-bit
             * 4:2:2 codes, each pixel with its pair's chroma */
            size_t fsize;
            unsigned char *fb = load(frame, &fsize);
            size_t stride = fsize / 2160;
            long px = 0, exact_px = 0, over[3] = {0};
            double lut_worst = 0, noflag_worst = 0;
            long cell_hist[8] = {0};
            for (int y = 8; y < 2160; y++)   /* packet rows left out */
                for (int x = 0; x < 3840; x += 2) {
                    const unsigned char *p = fb + y * stride + 4 * x;
                    int y0 = (p[1] << 4) | (p[0] & 15), cb = (p[2] << 4) | (p[0] >> 4);
                    int y1 = (p[5] << 4) | (p[4] & 15), cr = (p[6] << 4) | (p[4] >> 4);
                    int ys[2] = {y0, y1};
                    for (int l = 0; l < 2; l++) {
                        double c[3] = {ys[l], cb, cr}, nl[3], exact[3], lerp[3] = {0}, f[3], a[3], b[3], ycc[3];
                        int i0[3];
                        dvvk_map_nonlinear(g, c, nl);
                        dvvk_map_sample(g, c, exact);
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
                        dvvk_map_ycc(lerp, ycc);
                        codes12(exact, a);
                        codes12(ycc, b);
                        double e = fmax(fabs(a[0] - b[0]), fmax(fabs(a[1] - b[1]), fabs(a[2] - b[2])));
                        lut_worst = fmax(lut_worst, e);
                        if (!fl)
                            noflag_worst = fmax(noflag_worst, e);
                        over[0] += e > 0.5;
                        over[1] += e > 1;
                        over[2] += e > 2;
                        px++;
                        exact_px += fl;
                        int band = (int)fmin(7, nl[0] * 8);
                        if (fl)
                            cell_hist[band]++;
                    }
                }
            printf("  frame %s: %ld px, in flagged cells %.2f%%; LUT-only error worst %.2f, >0.5 %.3f%% >1 %.3f%% >2 %.3f%%; "
                   "worst outside flagged cells %.2f\n",
                   frame, px, 100.0 * exact_px / px, lut_worst, 100.0 * over[0] / px, 100.0 * over[1] / px,
                   100.0 * over[2] / px, noflag_worst);
            printf("  flagged by R' band (eighths): %ld %ld %ld %ld %ld %ld %ld %ld\n", cell_hist[0], cell_hist[1],
                   cell_hist[2], cell_hist[3], cell_hist[4], cell_hist[5], cell_hist[6], cell_hist[7]);
            if (outpath) {
                /* the frame mapped exactly on the CPU, in the engine's output bytes */
                unsigned char *o = malloc(fsize);
                memcpy(o, fb, fsize);
                for (int y = 0; y < 2160; y++)
                    for (int x = 0; x < 3840; x += 2) {
                        unsigned char *p = o + y * stride + 4 * x;
                        const unsigned char *q = fb + y * stride + 4 * x;
                        int y0 = (q[1] << 4) | (q[0] & 15), cb = (q[2] << 4) | (q[0] >> 4);
                        int y1 = (q[5] << 4) | (q[4] & 15), cr = (q[6] << 4) | (q[4] >> 4);
                        double c0[3] = {y0, cb, cr}, c1[3] = {y1, cb, cr}, a[3], b[3], ca[3], cbb[3];
                        dvvk_map_sample(g, c0, a);
                        dvvk_map_sample(g, c1, b);
                        codes12(a, ca);
                        codes12(b, cbb);
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
            }
            free(fb);
        }
        free(lut);
        free(md);
    }
    return 0;
}
