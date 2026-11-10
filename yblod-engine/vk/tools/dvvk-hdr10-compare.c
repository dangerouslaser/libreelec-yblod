/* HDR10 output dumps (dvvk-bench --output hdr10 --dump): 12-bit 4:2:2
 * limited-range BT.2020 PQ Y'CbCr in the tunnel's XRGB8888 bytes.
 *
 *   dvvk-hdr10-compare [options] OURS.bgra
 *     --preview FILE.ppm   a 960x540 SDR preview (PQ to nits, a soft clip at
 *                          203 nits white, BT.2020 to BT.709, sRGB)
 *     --ref FILE           a reference picture to compare with: raw RGB 3840x2160,
 *                          --ref-format rgb16 (default: 16-bit little-endian PQ
 *                          R'G'B' full range, 6 bytes a pixel) or rgb10a2
 *                          (A2B10G10R10/A2R10G10B10 words, --ref-order rgba|bgra)
 *                          or f32 (float R'G'B' PQ 0..1, 12 bytes a pixel)
 *     --ref-stride BYTES   the reference's row stride
 *     --flip               the reference's rows bottom first
 *     --rows A,B           compare rows A..B-1 only (the active area)
 *     --stats X0,Y0,X1,Y1  HDR10+ statistics of the dump's area [X0,X1) x
 *                          [Y0,Y1) (even X), the CPU reference of the engine's
 *                          (pack.comp STATS, DVVK_HDR10PLUS_TRACE=1): each
 *                          pixel's Y with its pair's Cb/Cr to PQ R'G'B'
 *                          (clamped 0..1), maxRGB light, 16-nit histogram,
 *                          channel maxima, sum of light; a JSON line, in double
 *   The comparison is in 12-bit codes of what the HDMI link would carry: the
 *   reference's R'G'B' converted to BT.2020 Y'CbCr, limited range, luma per
 *   pixel and chroma per pair (the even pixel's, as the engine does).
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define W 3840
#define H 2160

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

static double pq_eotf(double v)
{
    const double m1 = 2610.0 / 16384, m2 = 2523.0 / 32, c1 = 3424.0 / 4096, c2 = 2413.0 / 128, c3 = 2392.0 / 128;
    double p = pow(fmax(v, 0.0), 1.0 / m2);
    return 10000.0 * pow(fmax(p - c1, 0.0) / (c2 - c3 * p), 1.0 / m1);
}

/* the dump's pixel (x, y): 12-bit Y and its chroma channel (Cb even, Cr odd) */
static void unpack(const unsigned char *d, size_t stride, int x, int y, int *yy, int *c)
{
    const unsigned char *p = d + y * stride + 4 * x;
    int b = p[0], g = p[1], r = p[2];
    *yy = (g << 4) | (b & 15);
    *c = (r << 4) | (b >> 4);
}

static void ycc_codes(const double rgb[3], double out[3])
{
    double y = 0.2627 * rgb[0] + 0.6780 * rgb[1] + 0.0593 * rgb[2];
    out[0] = 256.0 + 3504.0 * y;
    out[1] = 2048.0 + 3584.0 * (rgb[2] - y) / 1.8814;
    out[2] = 2048.0 + 3584.0 * (rgb[0] - y) / 1.4746;
}

static int ref_format = 0, ref_order_bgra = 0;
static size_t ref_stride = 0;
static int ref_flip = 0;

static void ref_rgb(const unsigned char *ref, int x, int y, double rgb[3])
{
    if (ref_flip)
        y = H - 1 - y;
    if (ref_format == 0) {
        const uint16_t *p = (const uint16_t *)(ref + y * ref_stride + 6 * x);
        for (int k = 0; k < 3; k++)
            rgb[k] = p[k] / 65535.0;
    } else if (ref_format == 1) {
        uint32_t w;
        memcpy(&w, ref + y * ref_stride + 4 * x, 4);
        double a = (w & 1023) / 1023.0, b = ((w >> 10) & 1023) / 1023.0, c = ((w >> 20) & 1023) / 1023.0;
        rgb[0] = ref_order_bgra ? c : a;
        rgb[1] = b;
        rgb[2] = ref_order_bgra ? a : c;
    } else {
        const float *p = (const float *)(ref + y * ref_stride + 12 * x);
        for (int k = 0; k < 3; k++)
            rgb[k] = p[k];
    }
}

int main(int argc, char **argv)
{
    const char *preview = NULL, *refpath = NULL, *ours = NULL;
    int row0 = 0, row1 = H, sx0 = -1, sy0 = 0, sx1 = 0, sy1 = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--preview") && i + 1 < argc)
            preview = argv[++i];
        else if (!strcmp(argv[i], "--ref") && i + 1 < argc)
            refpath = argv[++i];
        else if (!strcmp(argv[i], "--ref-format") && i + 1 < argc) {
            i++;
            ref_format = !strcmp(argv[i], "rgb10a2") ? 1 : !strcmp(argv[i], "f32") ? 2 : 0;
        } else if (!strcmp(argv[i], "--ref-order") && i + 1 < argc)
            ref_order_bgra = !strcmp(argv[++i], "bgra");
        else if (!strcmp(argv[i], "--ref-stride") && i + 1 < argc)
            ref_stride = strtoul(argv[++i], NULL, 0);
        else if (!strcmp(argv[i], "--flip"))
            ref_flip = 1;
        else if (!strcmp(argv[i], "--stats") && i + 1 < argc)
            sscanf(argv[++i], "%d,%d,%d,%d", &sx0, &sy0, &sx1, &sy1);
        else if (!strcmp(argv[i], "--rows") && i + 1 < argc)
            sscanf(argv[++i], "%d,%d", &row0, &row1);
        else
            ours = argv[i];
    }
    if (!ours)
        return fprintf(stderr, "usage: dvvk-hdr10-compare [--preview F] [--ref F ...] OURS.bgra\n"), 2;
    size_t size;
    unsigned char *d = load(ours, &size);
    if (!d || size < (size_t)W * 4 * H)
        return fprintf(stderr, "%s: can't read a 3840x2160 dump\n", ours), 1;
    size_t stride = size / H;
    /* code statistics */
    long hist_y[4096] = {0};
    double ysum = 0;
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            int yy, c;
            unpack(d, stride, x, y, &yy, &c);
            hist_y[yy]++;
            ysum += yy;
        }
    int ymin = 0, ymax = 4095;
    while (ymin < 4095 && !hist_y[ymin])
        ymin++;
    while (ymax > 0 && !hist_y[ymax])
        ymax--;
    printf("%s: Y codes %d..%d mean %.1f; peak %.1f nits\n", ours, ymin, ymax, ysum / ((double)W * H),
           pq_eotf((ymax - 256) / 3504.0));
    if (sx0 >= 0) {
        unsigned long hist[256] = {0};
        double maxq[3] = {0}, sum = 0;
        unsigned long count = 0;
        for (int y = sy0; y < sy1; y++)
            for (int x = sx0 & ~1; x + 1 < sx1; x += 2) {
                int y0, cb, y1, cr;
                unpack(d, stride, x, y, &y0, &cb);
                unpack(d, stride, x + 1, y, &y1, &cr);
                for (int k = 0; k < 2; k++) {
                    double Y = ((k ? y1 : y0) - 256) / 3504.0, Cb = (cb - 2048) / 3584.0, Cr = (cr - 2048) / 3584.0;
                    double R = Y + 1.4746 * Cr, B = Y + 1.8814 * Cb, G = (Y - 0.2627 * R - 0.0593 * B) / 0.6780;
                    double rgb[3] = {fmin(fmax(R, 0), 1), fmin(fmax(G, 0), 1), fmin(fmax(B, 0), 1)};
                    double m = 0;
                    for (int c = 0; c < 3; c++) {
                        maxq[c] = fmax(maxq[c], rgb[c]);
                        m = fmax(m, rgb[c]);
                    }
                    double nits = pq_eotf(m);
                    int bin = (int)floor(nits / 16.0 + 0.5);
                    hist[bin > 255 ? 255 : bin]++;
                    sum += nits;
                    count++;
                }
            }
        printf("{\"cpu_stats\":\"%s\",\"count\":%lu,\"average_maxrgb\":%.4f,\"maxscl\":[%.4f,%.4f,%.4f],\"histogram\":[",
               ours, count, count ? sum / count : 0.0, pq_eotf(maxq[0]), pq_eotf(maxq[1]), pq_eotf(maxq[2]));
        for (int i = 0; i < 256; i++)
            printf(i ? ",%lu" : "%lu", hist[i]);
        printf("]}\n");
    }
    if (preview) {
        FILE *f = fopen(preview, "wb");
        fprintf(f, "P6\n960 540\n255\n");
        for (int py = 0; py < 540; py++)
            for (int px = 0; px < 960; px++) {
                int x = px * 4 & ~1, y = py * 4, yy, cb, cr;
                unpack(d, stride, x, y, &yy, &cb);
                unpack(d, stride, x + 1, y, &yy, &cr);
                unpack(d, stride, x, y, &yy, &cb);
                double Y = (yy - 256) / 3504.0, Cb = (cb - 2048) / 3584.0, Cr = (cr - 2048) / 3584.0;
                double R = Y + 1.4746 * Cr, B = Y + 1.8814 * Cb, G = (Y - 0.2627 * R - 0.0593 * B) / 0.6780;
                double lin[3] = {pq_eotf(R) / 203.0, pq_eotf(G) / 203.0, pq_eotf(B) / 203.0};
                static const double m[9] = {1.6605, -0.5876, -0.0728, -0.1246, 1.1329, -0.0083, -0.0182, -0.1006, 1.1187};
                unsigned char px3[3];
                for (int k = 0; k < 3; k++) {
                    double v = m[3 * k] * lin[0] + m[3 * k + 1] * lin[1] + m[3 * k + 2] * lin[2];
                    v = v / (1.0 + 0.25 * v);   /* a soft clip */
                    v = fmin(fmax(v * 1.25, 0.0), 1.0);
                    v = v <= 0.0031308 ? 12.92 * v : 1.055 * pow(v, 1 / 2.4) - 0.055;
                    px3[k] = (unsigned char)lround(v * 255.0);
                }
                fwrite(px3, 1, 3, f);
            }
        fclose(f);
    }
    if (refpath) {
        size_t rsize;
        unsigned char *ref = load(refpath, &rsize);
        if (!ref)
            return fprintf(stderr, "%s: can't read\n", refpath), 1;
        if (!ref_stride)
            ref_stride = rsize / H;
        long n = 0, over[3][4] = {{0}};
        double sum[3] = {0}, sq[3] = {0}, worst[3] = {0};
        int wx[3] = {0}, wy[3] = {0};
        for (int y = row0; y < row1; y++)
            for (int x = 0; x < W; x += 2) {
                double rgb0[3], rgb1[3], c0[3], c1[3];
                ref_rgb(ref, x, y, rgb0);
                ref_rgb(ref, x + 1, y, rgb1);
                ycc_codes(rgb0, c0);
                ycc_codes(rgb1, c1);
                int y0, cb, y1, cr;
                unpack(d, stride, x, y, &y0, &cb);
                unpack(d, stride, x + 1, y, &y1, &cr);
                double dv[4][2] = {{y0 - c0[0], 0}, {y1 - c1[0], 0}, {cb - c0[1], 1}, {cr - c0[2], 2}};
                for (int k = 0; k < 4; k++) {
                    int ch = (int)dv[k][1];
                    double e = fabs(dv[k][0]);
                    sum[ch] += dv[k][0];
                    sq[ch] += e * e;
                    if (e > worst[ch]) {
                        worst[ch] = e;
                        wx[ch] = x + (k == 1);
                        wy[ch] = y;
                    }
                    over[ch][0] += e > 1.0;
                    over[ch][1] += e > 2.0;
                    over[ch][2] += e > 4.0;
                    over[ch][3] += e > 16.0;
                }
                n++;
            }
        const char *names[3] = {"Y", "Cb", "Cr"};
        for (int ch = 0; ch < 3; ch++) {
            double cnt = ch == 0 ? 2.0 * n : (double)n;
            printf("  %-2s vs ref (12-bit): mean %+.3f rms %.3f max %.1f at %d,%d; >1 %.4f%% >2 %.4f%% >4 %.4f%% >16 %.4f%%\n",
                   names[ch], sum[ch] / cnt, sqrt(sq[ch] / cnt), worst[ch], wx[ch], wy[ch], 100.0 * over[ch][0] / cnt,
                   100.0 * over[ch][1] / cnt, 100.0 * over[ch][2] / cnt, 100.0 * over[ch][3] / cnt);
        }
    }
    return 0;
}
