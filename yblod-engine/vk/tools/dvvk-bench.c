/* dv-engine-vk alone, headless: GPU cost of tunnel pictures with the film in a
 * rectangle of the canvas and a full-screen overlay (the desktop) over it,
 * the case of docs/research/media-following-colour.md (M2). No OpenCL, no
 * display, no audio: VAAPI decode on the render node, the engine writing
 * into 4 linear GBM buffers as mpv-yblod's tunnel does, frames submitted
 * asynchronously at a fixed rate. Run with DVVK_PROFILE=1 for the engine's
 * GPU time per pass (printed every 120 frames).
 *
 *   dvvk-bench [options] FILE
 *     --frames N         pictures (default 240)
 *     --start S          seconds into the file
 *     --rate HZ          submit rate (default 23.976; 0: as fast as possible)
 *     --canvas W,H       the engine's canvas (dvvk_create_canvas; default
 *                        3840,2160): the output buffers', the overlay
 *                        file's and the dumps' size
 *     --dest X,Y,W,H     the film's rectangle (default: aspect-fit full screen)
 *     --fel 0|1          FEL off/on (default 1)
 *     --el-scaler M      annexb (1, the default) or bilinear (2): the FEL's
 *                        EL upsampling (dvvk_plan_in.el_scaler); --cb1 is Annex B
 *     --overlay FILE     the overlay: raw BGRA of the canvas's size (ARGB8888 bytes, as
 *                        `ffmpeg -i shot.png -vf scale=3840:2160 -pix_fmt bgra
 *                        -f rawvideo FILE`), premultiplied; pixels inside
 *                        --dest are made transparent (the hole)
 *     --mode M           none: no overlay; static: the same overlay every
 *                        frame; change: every pixel changes every frame (two
 *                        buffers alternating); rect: only a 256x256 square
 *                        changes every frame (focus, cursor)
 *     --white NITS       overlay white (default 203)
 *     --flip             the overlay's rows stored bottom first and set with
 *                        DVVK_OVERLAY_FLIP_Y (Kodi's GUI framebuffer, read in
 *                        place): the output must equal the run without it
 *     --fp16             the overlay as linear half float (AB4H, 1.0 = the
 *                        overlay's white), as a compositor's HDR-capable
 *                        desktop: the same picture, sRGB decoded
 *     --desktop          desktop mode: static graphics display management
 *                        (DVVK_FRAME_DESKTOP; DVVK_DESKTOP_L1=MIN,MAX,AVG)
 *     --cb1              CB1's Master Reference contract as mpv-yblod's
 *                        engine_vulkan.c sets it (--dv-cb1, the default):
 *                        unscaled pictures in a siting the engine does get
 *                        cb1_contract, the Annex B EL scaler, CB1's siting and
 *                        refresh rule (first picture, a step back or a gap
 *                        over 0.1 s); a film in a box stays yblod's
 *     --cm4 MODE         CM4 metadata (dvvk_plan_in.dm_options): off, no-l2,
 *                        always, auto, auto2 (mpv-yblod's --dv-cm4)
 *     --cm4-trigger T    auto's trigger: source (the TV peak), 1000, 2000,
 *                        4000, 10000
 *     --cm4-headroom P   auto2's headroom, 0..50 (default 20)
 *     --tv-peak NITS     the TV's peak (0: unknown)
 *     --output MODE      dv (the tunnel, default), hdr10 or hdr10plus: the
 *                        engine converts to HDR10 / HDR10+ (dvvk_set_output_mode;
 *                        the dumps are then 12-bit 4:2:2 BT.2020 PQ Y'CbCr in
 *                        the tunnel's bytes). hdr10plus prints each picture's
 *                        dvvk_hdr10plus_packet as a JSON line ("hdr10plus":
 *                        right after submit, "late" statistics allowed; and
 *                        for dumped pictures once done, "own")
 *                        sdr: the engine converts to an SDR display's picture
 *                        (the dumps are then 8-bit R'G'B' XRGB8888)
 *     --white NITS       sdr: the display's white (default 203); also the
 *                        overlay's white in the other modes
 *     --black NITS       sdr: the display's black (default white / 1000)
 *     --gamma22          sdr: a 2.2 power instead of BT.1886
 *     --limited          sdr: codes 16..235
 *     --no-dither        sdr: rounded codes
 *     --hdr10plus-v0     HDR10+ application version 0 (default 1)
 *     --no-l2            L2 trims left out of the metadata
 *     --dump FILE        the last picture's XRGB8888 bytes
 *     --dump-at N[,M..]  dump picture N instead of the last; with several,
 *                        picture N goes to FILE.N
 *     --metadata PREFIX  write the first --metadata-frames (default 2)
 *                        pictures' AVDOVIMetadata to PREFIX.N.bin and a line
 *                        each (N width height has_el nv12 top_left bytes) to
 *                        PREFIX.txt: plan.c's fixtures (src/plan.rs tests)
 */
#define _GNU_SOURCE
#include "decode.h"
#include "../include/dv_engine_vk.h"
#include <gbm.h>
#include <drm_fourcc.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static int W = 3840, H = 2160;   /* the canvas */
#define SLOTS 4

/* One dvvk_hdr10plus_packet as a JSON line. */
static void print_hdr10plus(dvvk_engine *e, int n, uint64_t ticket, uint32_t flags, const char *when)
{
    dvvk_hdr10plus_metadata m;
    memset(&m, 0, sizeof(m));
    int st = dvvk_hdr10plus_packet(e, ticket, flags, &m);
    printf("{\"hdr10plus\":\"%s\",\"picture\":%d,\"ticket\":%llu,\"status\":%d", when, n,
           (unsigned long long)ticket, st);
    if (st == 0 || st == DVVK_HDR10PLUS_FALLBACK) {
        printf(",\"statistics_ticket\":%llu,\"pixels\":%llu,\"average_maxrgb\":%.4f,\"maxscl\":[%.4f,%.4f,%.4f]"
               ",\"coverage\":%u,\"reason\":%u,\"l1\":[%u,%u,%u],\"l3\":%u,\"curve_error\":%.6f,\"color_error\":%.6f,\"vsif\":\"",
               (unsigned long long)m.statistics_ticket, (unsigned long long)m.pixels, m.average_maxrgb, m.maxscl[0],
               m.maxscl[1], m.maxscl[2], m.coverage, m.reason, m.effective_l1[0], m.effective_l1[1], m.effective_l1[2],
               m.l3_used, m.maximum_curve_pq_error, m.maximum_color_pq_error);
        for (int i = 0; i < 31; i++)
            printf("%02x", m.vsif[i]);
        printf("\"");
    }
    printf("}\n");
}

static double now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
}

struct bo {
    struct gbm_bo *bo;
    int fd;
    uint32_t stride;
};

static uint32_t bo_format = GBM_FORMAT_ARGB8888;

static uint16_t half(float f)
{
    union { float f; uint32_t u; } v = {f};
    uint32_t sign = (v.u >> 16) & 0x8000, e = (v.u >> 23) & 0xff, m = v.u & 0x7fffff;
    if (e == 0xff)
        return sign | 0x7c00 | (m ? 0x200 : 0);
    int ne = (int)e - 127 + 15;
    if (ne >= 31)
        return sign | 0x7c00;
    if (ne <= 0) {
        if (ne < -10)
            return sign;
        m |= 0x800000;
        return sign | (uint16_t)((m >> (14 - ne)) + ((m >> (13 - ne)) & 1));
    }
    return sign | (uint16_t)(ne << 10 | m >> 13) + ((m >> 12) & 1);
}

static float srgb_linear(float c)
{
    return c <= 0.04045f ? c / 12.92f : powf((c + 0.055f) / 1.055f, 2.4f);
}

static int make_bo(struct gbm_device *gbm, struct bo *b)
{
    b->bo = gbm_bo_create(gbm, W, H, bo_format, GBM_BO_USE_LINEAR | GBM_BO_USE_RENDERING);
    if (!b->bo)
        return -1;
    b->fd = gbm_bo_get_fd(b->bo);
    b->stride = gbm_bo_get_stride(b->bo);
    return b->fd < 0 ? -1 : 0;
}

static int fill_bo(struct bo *b, const uint8_t *src)
{
    uint32_t stride = 0;
    void *map = NULL;
    uint8_t *p = gbm_bo_map(b->bo, 0, 0, W, H, GBM_BO_TRANSFER_WRITE, &stride, &map);
    if (!p)
        return -1;
    if (bo_format == GBM_FORMAT_ABGR16161616F) {
        /* BGRA8 premultiplied sRGB -> RGBA half, premultiplied linear */
        for (int y = 0; y < H; y++) {
            uint16_t *row = (uint16_t *)(p + (size_t)y * stride);
            const uint8_t *s = src + (size_t)y * W * 4;
            for (int x = 0; x < W; x++) {
                float a = s[4 * x + 3] / 255.0f;
                float rgb[3] = {s[4 * x + 2], s[4 * x + 1], s[4 * x + 0]};
                for (int c = 0; c < 3; c++)
                    row[4 * x + c] = half(a > 0 ? srgb_linear(rgb[c] / 255.0f / a) * a : 0);
                row[4 * x + 3] = half(a);
            }
        }
        gbm_bo_unmap(b->bo, map);
        return 0;
    }
    for (int y = 0; y < H; y++)
        memcpy(p + (size_t)y * stride, src + (size_t)y * W * 4, W * 4);
    gbm_bo_unmap(b->bo, map);
    return 0;
}

static int read_bo(struct bo *b, uint8_t *dst)
{
    uint32_t stride = 0;
    void *map = NULL;
    uint8_t *p = gbm_bo_map(b->bo, 0, 0, W, H, GBM_BO_TRANSFER_READ, &stride, &map);
    if (!p)
        return -1;
    for (int y = 0; y < H; y++)
        memcpy(dst + (size_t)y * W * 4, p + (size_t)y * stride, W * 4);
    gbm_bo_unmap(b->bo, map);
    return 0;
}

/* mpv-yblod tunnel.c cb1_siting(): 0 left, 1 top-left, -1 another. */
static int cb1_siting(enum AVChromaLocation coded, const AVDOVIMetadata *m)
{
    const AVDOVIRpuDataHeader *hdr = av_dovi_get_header(m);
    int profile7 = hdr->vdr_rpu_profile == 1 && !hdr->disable_residual_flag;
    switch (coded) {
    case AVCHROMA_LOC_UNSPECIFIED: return profile7 ? 1 : 0;
    case AVCHROMA_LOC_TOPLEFT:     return 1;
    case AVCHROMA_LOC_CENTER:
    case AVCHROMA_LOC_TOP:
    case AVCHROMA_LOC_BOTTOMLEFT:
    case AVCHROMA_LOC_BOTTOM:      return -1;
    default:                       return 0;
    }
}

#define MAX_DUMPS 64

static void dump_bo(struct bo *b, const char *path)
{
    uint8_t *buf = malloc((size_t)W * H * 4);
    FILE *df = buf && !read_bo(b, buf) ? fopen(path, "wb") : NULL;
    if (df) {
        fwrite(buf, 1, (size_t)W * H * 4, df);
        fclose(df);
    } else
        fprintf(stderr, "dump %s failed\n", path);
    free(buf);
}

static void sleep_until(double t_ms)
{
    double d = t_ms - now_ms();
    if (d <= 0)
        return;
    struct timespec ts = {(time_t)(d / 1e3), (long)(fmod(d, 1e3) * 1e6)};
    nanosleep(&ts, NULL);
}

int main(int argc, char **argv)
{
    int frames = 240, fel = 1, scaler = DVVK_EL_ANNEXB, have_dest = 0, desktop = 0, fp16 = 0, cb1 = 0, flip = 0;
    unsigned cm4 = 0, cm4_trigger = 0, cm4_headroom = 20, tv_peak = 0, no_l2 = 0, output = DVVK_OUTPUT_DV;
    int hdr10plus_v0 = 0;
    uint32_t last_dm_status = UINT32_MAX;
    int dump_at[MAX_DUMPS], dumps = 0, dumped = 0, metadata_frames = 2;
    const char *metadata_prefix = NULL;
    double start = 0, rate = 23.976, white = 203.0, black = 0;
    unsigned sdr_flags = 0;
    unsigned dx = 0, dy = 0, dwid = 0, dhei = 0;
    const char *file = NULL, *overlay_path = NULL, *mode = "none", *dump = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--frames") && i + 1 < argc)
            frames = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--canvas") && i + 1 < argc) {
            if (sscanf(argv[++i], "%d,%d", &W, &H) != 2 || W <= 0 || H <= 0)
                return fprintf(stderr, "--canvas W,H\n"), 2;
        }
        else if (!strcmp(argv[i], "--start") && i + 1 < argc)
            start = atof(argv[++i]);
        else if (!strcmp(argv[i], "--rate") && i + 1 < argc)
            rate = atof(argv[++i]);
        else if (!strcmp(argv[i], "--dest") && i + 1 < argc) {
            if (sscanf(argv[++i], "%u,%u,%u,%u", &dx, &dy, &dwid, &dhei) != 4)
                return fprintf(stderr, "--dest X,Y,W,H\n"), 2;
            have_dest = 1;
        } else if (!strcmp(argv[i], "--fel") && i + 1 < argc)
            fel = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--el-scaler") && i + 1 < argc)
        {
            const char *m = argv[++i];
            scaler = !strcmp(m, "bilinear") || !strcmp(m, "2") ? DVVK_EL_BILINEAR
                     : !strcmp(m, "annexb") || !strcmp(m, "1") ? DVVK_EL_ANNEXB
                                                                : -1;
            if (scaler < 0) {
                fprintf(stderr, "--el-scaler: annexb or bilinear\n");
                return 2;
            }
        }
        else if (!strcmp(argv[i], "--overlay") && i + 1 < argc)
            overlay_path = argv[++i];
        else if (!strcmp(argv[i], "--mode") && i + 1 < argc)
            mode = argv[++i];
        else if (!strcmp(argv[i], "--white") && i + 1 < argc)
            white = atof(argv[++i]);
        else if (!strcmp(argv[i], "--dump") && i + 1 < argc)
            dump = argv[++i];
        else if (!strcmp(argv[i], "--dump-at") && i + 1 < argc) {
            for (char *t = strtok(argv[++i], ","); t && dumps < MAX_DUMPS; t = strtok(NULL, ","))
                dump_at[dumps++] = atoi(t);
        } else if (!strcmp(argv[i], "--metadata") && i + 1 < argc)
            metadata_prefix = argv[++i];
        else if (!strcmp(argv[i], "--metadata-frames") && i + 1 < argc)
            metadata_frames = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--cm4") && i + 1 < argc) {
            static const char *const modes[] = {"off", "no-l2", "always", "auto", "auto2"};
            const char *m = argv[++i];
            for (cm4 = 0; cm4 < 5 && strcmp(m, modes[cm4]); cm4++)
                ;
            if (cm4 == 5)
                return fprintf(stderr, "--cm4: off, no-l2, always, auto or auto2\n"), 2;
        } else if (!strcmp(argv[i], "--cm4-trigger") && i + 1 < argc) {
            static const char *const triggers[] = {"source", "1000", "2000", "4000", "10000"};
            const char *t = argv[++i];
            for (cm4_trigger = 0; cm4_trigger < 5 && strcmp(t, triggers[cm4_trigger]); cm4_trigger++)
                ;
            if (cm4_trigger == 5)
                return fprintf(stderr, "--cm4-trigger: source, 1000, 2000, 4000 or 10000\n"), 2;
        } else if (!strcmp(argv[i], "--cm4-headroom") && i + 1 < argc)
            cm4_headroom = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--tv-peak") && i + 1 < argc)
            tv_peak = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--output") && i + 1 < argc)
        {
            const char *m = argv[++i];
            output = !strcmp(m, "hdr10") ? DVVK_OUTPUT_HDR10 : !strcmp(m, "hdr10plus") ? DVVK_OUTPUT_HDR10PLUS
                     : !strcmp(m, "sdr") ? DVVK_OUTPUT_SDR : DVVK_OUTPUT_DV;
        }
        else if (!strcmp(argv[i], "--black") && i + 1 < argc)
            black = atof(argv[++i]);
        else if (!strcmp(argv[i], "--gamma22"))
            sdr_flags |= DVVK_SDR_GAMMA22;
        else if (!strcmp(argv[i], "--limited"))
            sdr_flags |= DVVK_SDR_LIMITED;
        else if (!strcmp(argv[i], "--no-dither"))
            sdr_flags |= DVVK_SDR_NO_DITHER;
        else if (!strcmp(argv[i], "--hdr10plus-v0"))
            hdr10plus_v0 = 1;
        else if (!strcmp(argv[i], "--no-l2"))
            no_l2 = 1;
        else if (!strcmp(argv[i], "--cb1"))
            cb1 = 1;
        else if (!strcmp(argv[i], "--desktop"))
            desktop = 1;
        else if (!strcmp(argv[i], "--flip"))
            flip = 1;
        else if (!strcmp(argv[i], "--fp16"))
            fp16 = 1;
        else if (argv[i][0] != '-')
            file = argv[i];
        else
            return fprintf(stderr, "unknown option %s\n", argv[i]), 2;
    }
    int use_overlay = strcmp(mode, "none") != 0;
    if (!file || (use_overlay && !overlay_path))
        return fprintf(stderr, "usage: dvvk-bench [options] FILE (see the source)\n"), 2;
    if (have_dest)
        dx &= ~1u, dy &= ~1u, dwid &= ~1u, dhei &= ~1u;

    const char *node = getenv("DVVK_NODE") ? getenv("DVVK_NODE") : "/dev/dri/renderD128";
    struct dv_decoder dec;
    if (dv_decoder_open(&dec, file, node, start) < 0)
        return fprintf(stderr, "can't decode %s\n", file), 1;
    int drm = open(node, O_RDWR | O_CLOEXEC);
    struct gbm_device *gbm = gbm_create_device(drm);
    struct bo out[SLOTS], ov[2] = {0};
    for (int i = 0; i < SLOTS; i++)
        if (make_bo(gbm, &out[i]))
            return fprintf(stderr, "gbm_bo_create failed\n"), 1;

    dvvk_engine *e = NULL;
    if (W == 3840 && H == 2160 ? dvvk_create(drm, dec.display, &e)
                               : dvvk_create_canvas(drm, dec.display, (uint32_t)W, (uint32_t)H, &e))
        return fprintf(stderr, "dvvk_create failed\n"), 1;
    if (output != DVVK_OUTPUT_DV) {
        dvvk_output_mode om = {.mode = output};
        if (output == DVVK_OUTPUT_SDR) {
            om.flags = sdr_flags;
            om.peak_nits = (float)white;
            om.min_nits = (float)black;
        }
        if (dvvk_set_output_mode(e, &om))
            return fprintf(stderr, "dvvk_set_output_mode failed\n"), 1;
    }
    for (int i = 0; i < SLOTS; i++)
        if (dvvk_set_output(e, (uint32_t)i, out[i].fd, out[i].stride))
            return fprintf(stderr, "dvvk_set_output failed\n"), 1;

    if (use_overlay) {
        uint8_t *a = malloc((size_t)W * H * 4), *b = malloc((size_t)W * H * 4);
        FILE *f = fopen(overlay_path, "rb");
        if (!f || fread(a, 1, (size_t)W * H * 4, f) != (size_t)W * H * 4)
            return fprintf(stderr, "can't read %s (%dx%d BGRA)\n", overlay_path, W, H), 1;
        fclose(f);
        if (have_dest)
            for (unsigned y = dy; y < dy + dhei && y < (unsigned)H; y++)
                memset(a + ((size_t)y * W + dx) * 4, 0, (size_t)dwid * 4);
        /* premultiplied: colour at most alpha */
        for (size_t i = 0; i < (size_t)W * H; i++)
            for (int c = 0; c < 3; c++)
                if (a[i * 4 + c] > a[i * 4 + 3])
                    a[i * 4 + c] = a[i * 4 + 3];
        memcpy(b, a, (size_t)W * H * 4);
        int rect = !strcmp(mode, "rect");
        const unsigned rect_x = (unsigned)W * 15 / 32, rect_y = (unsigned)H * 5 / 54;
        for (size_t i = 0; i < (size_t)W * H; i++) {
            unsigned x = (unsigned)(i % (size_t)W), y = (unsigned)(i / (size_t)W);
            /* (1800, 200 in a 3840x2160 canvas) */
            if (rect && !(x >= rect_x && x < rect_x + 256 && y >= rect_y && y < rect_y + 256))
                continue;
            uint8_t *p = b + i * 4;
            if (p[3] == 0)
                continue;
            for (int c = 0; c < 3; c++)  /* a one-code change, kept premultiplied */
                p[c] = p[c] > 0 ? p[c] - 1 : (p[c] < p[3] ? 1 : 0);
        }
        if (flip) {
            /* rows bottom first, as a GL framebuffer's texture */
            uint8_t *row = malloc((size_t)W * 4);
            for (uint8_t *p = a; p; p = p == a ? b : NULL)
                for (unsigned y = 0; y < (unsigned)H / 2; y++) {
                    memcpy(row, p + (size_t)y * W * 4, (size_t)W * 4);
                    memcpy(p + (size_t)y * W * 4, p + (size_t)(H - 1 - y) * W * 4, (size_t)W * 4);
                    memcpy(p + (size_t)(H - 1 - y) * W * 4, row, (size_t)W * 4);
                }
            free(row);
        }
        if (fp16)
            bo_format = GBM_FORMAT_ABGR16161616F;
        if (make_bo(gbm, &ov[0]) || make_bo(gbm, &ov[1]) || fill_bo(&ov[0], a) || fill_bo(&ov[1], b))
            return fprintf(stderr, "overlay buffers failed\n"), 1;
        free(a);
        free(b);
    }

    /* mpv-yblod's GUI colour: BT.709 -> BT.2020 -> the common LMS */
    static const double rgb[9] = {.6274, .3293, .0433, .0691, .9195, .0114, .0164, .0880, .8956};
    static const double lms[9] = {7222, 8771, 390, 2654, 12430, 1300, 0, 422, 15962};
    double rgb_to_lms[9] = {0};
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            for (int k = 0; k < 3; k++)
                rgb_to_lms[3 * i + j] += lms[3 * i + k] * rgb[3 * k + j] / 16384.0;

    struct dv_pair held[SLOTS];
    uint64_t tickets[SLOTS] = {0};
    int have[SLOTS] = {0};
    memset(held, 0, sizeof(held));
    double period = rate > 0 ? 1000.0 / rate : 0, t_next = now_ms();
    double submit_sum = 0, submit_max = 0, wait_sum = 0;
    int n = 0, refused = 0, flagged = 0, ov_before = 0;
    unsigned packet_id = 0;
    int cb1_sent = 0, cb1_refresh = 0;
    int64_t cb1_pts = 0;
    double t0 = now_ms();
    struct dv_pair p;
    while (n < frames && dv_decoder_next(&dec, &p) == 1) {
        if (!p.dovi) {
            dv_pair_free(&p);
            continue;
        }
        int slot = n % SLOTS;
        if (have[slot]) {
            double tw = now_ms();
            dvvk_wait(e, tickets[slot], UINT64_MAX);
            int done = 0;
            uint32_t fl = 0;
            dvvk_poll(e, tickets[slot], &done, &fl);
            if (fl)
                flagged++;
            wait_sum += now_ms() - tw;
            dv_pair_free(&held[slot]);
            have[slot] = 0;
        }
        unsigned w = (unsigned)p.bl->width, h = (unsigned)p.bl->height;
        unsigned x = dx, y = dy, dw = dwid, dh = dhei;
        if (!have_dest) {
            double scale = fmin((double)W / w, (double)H / h);
            int x0 = (int)lround((W - w * scale) / 2), y0 = (int)lround((H - h * scale) / 2);
            int x1 = (int)lround((W + w * scale) / 2), y1 = (int)lround((H + h * scale) / 2);
            x = (unsigned)x0 & ~1u, y = (unsigned)y0 & ~1u;
            dw = (unsigned)(x1 - (int)x) & ~1u, dh = (unsigned)(y1 - (int)y) & ~1u;
        }
        int nv12 = ((AVHWFramesContext *)p.bl->hw_frames_ctx->data)->sw_format == AV_PIX_FMT_NV12;
        int top_left = p.bl->chroma_location == AVCHROMA_LOC_TOPLEFT;
        if (metadata_prefix && n < metadata_frames) {
            char path[4096];
            snprintf(path, sizeof(path), "%s.%d.bin", metadata_prefix, n);
            FILE *mf = fopen(path, "wb");
            if (mf) {
                fwrite(p.dovi->data, 1, p.dovi->size, mf);
                fclose(mf);
            }
            snprintf(path, sizeof(path), "%s.txt", metadata_prefix);
            if ((mf = fopen(path, n ? "a" : "w"))) {
                fprintf(mf, "%d %u %u %d %d %d %zu\n", n, w, h, p.el != NULL, nv12, top_left, (size_t)p.dovi->size);
                fclose(mf);
            }
        }
        int resized = dw != w || dh != h;
        int siting = cb1_siting(p.bl->chroma_location, (const AVDOVIMetadata *)p.dovi->data);
        int contract = cb1 && !resized && siting >= 0;
        if (contract) {
            if (!cb1_sent)
                cb1_refresh = 1;
            else if (p.bl->pts != cb1_pts) {
                int64_t us = av_rescale_q(p.bl->pts - cb1_pts, dec.time_base, (AVRational){1, 1000000});
                cb1_refresh = p.bl->pts < cb1_pts || us > 100000;
            }
        }
        int changing = !strcmp(mode, "change") || !strcmp(mode, "rect");
        if (use_overlay && (changing || n == 0)) {
            int which = changing ? (n & 1) : 0;
            /* rect: say where it changed (KWin's damage); change: nothing said
             * (everywhere) */
            if (!strcmp(mode, "rect") && n > 0) {
                const uint32_t r[4] = {(uint32_t)W * 15 / 32, (uint32_t)H * 5 / 54, 256, 256};
                dvvk_set_overlay_damage(e, r, 1);
            }
            dvvk_dmabuf db = {.width = W, .height = H, .format = fp16 ? DRM_FORMAT_ABGR16161616F : DRM_FORMAT_ARGB8888, .modifier = DRM_FORMAT_MOD_LINEAR,
                              .num_planes = 1, .fd = {ov[which].fd, -1, -1, -1}, .stride = {ov[which].stride}};
            if (dvvk_set_overlay_ex(e, &db, (uint64_t)n + 1, flip ? DVVK_OVERLAY_FLIP_Y : 0))
                return fprintf(stderr, "overlay refused\n"), 1;
        }
        dvvk_frame f = {.plan = {.width = w, .height = h, .x = x, .y = y, .dw = dw == w && dh == h ? 0 : dw,
                                 .dh = dw == w && dh == h ? 0 : dh,
                                 .chroma_top_left = (uint32_t)(contract ? siting == 1 : top_left),
                                 .has_el = p.el != NULL, .nv12 = (uint32_t)nv12,
                                 .el_scaler = (uint32_t)(contract ? DVVK_EL_ANNEXB : scaler), .fel = (uint32_t)fel,
                                 .packet_id = packet_id, .refresh = (uint32_t)(contract ? cb1_refresh : n == 0),
                                 .cb1_contract = (uint32_t)contract, .overlay = (uint32_t)use_overlay,
                                 .overlay_visible_before = (uint32_t)ov_before, .pts = p.bl->pts, .white_nits = white,
                                 .dm_options = DVVK_DM_OPTIONS(cm4, cm4_trigger, cm4_headroom, no_l2, tv_peak)},
                        .bl_surface = p.bl_surface, .el_surface = p.el ? p.el_surface : 0xffffffffu,
                        .metadata = p.dovi->data, .metadata_size = p.dovi->size, .output = (uint32_t)slot,
                        .flags = (use_overlay ? DVVK_FRAME_AUTO_OVERLAY : 0) | (desktop ? DVVK_FRAME_DESKTOP : 0)};
        memcpy(f.plan.rgb_to_lms, rgb_to_lms, sizeof(rgb_to_lms));
        packet_id = (packet_id + 1) & 0xf;
        ov_before = use_overlay;
        if (period > 0)
            sleep_until(t_next);
        t_next += period;
        double ts = now_ms();
        uint64_t ticket = 0;
        int rv = dvvk_submit(e, &f, &ticket);
        if (contract) {
            cb1_sent = rv == 0;
            cb1_pts = p.bl->pts;
        }
        double sub = now_ms() - ts;
        submit_sum += sub;
        if (sub > submit_max)
            submit_max = sub;
        if (rv) {
            if (refused++ < 3)
                fprintf(stderr, "frame %d refused: %d\n", n, rv);
            dv_pair_free(&p);
            n++;
            continue;
        }
        if (cm4 || no_l2) {
            uint32_t st = dvvk_dm_status(e);
            if (st != last_dm_status)
                printf("dvvk-bench: picture %d: CM4 status %u, %u L2 removed\n", n, st & 255, st >> 8 & 255);
            last_dm_status = st;
        }
        tickets[slot] = ticket;
        held[slot] = p;
        have[slot] = 1;
        uint32_t hflags = (hdr10plus_v0 ? 0 : DVVK_HDR10PLUS_V1) | DVVK_HDR10PLUS_NO_DELAY;
        if (output == DVVK_OUTPUT_HDR10PLUS)
            print_hdr10plus(e, n, ticket, hflags, "late");
        for (int k = 0; dump && k < dumps; k++)
            if (n == dump_at[k]) {
                dvvk_wait(e, ticket, UINT64_MAX);
                if (output == DVVK_OUTPUT_HDR10PLUS)
                    print_hdr10plus(e, n, ticket, hflags, "own");
                char path[4096];
                if (dumps == 1)
                    snprintf(path, sizeof(path), "%s", dump);
                else
                    snprintf(path, sizeof(path), "%s.%d", dump, n);
                dump_bo(&out[slot], path);
                dumped++;
            }
        n++;
    }
    for (int s = 0; s < SLOTS; s++)
        if (have[s]) {
            dvvk_wait(e, tickets[s], UINT64_MAX);
            dv_pair_free(&held[s]);
        }
    double total = now_ms() - t0;
    printf("dvvk-bench: %d pictures in %.0f ms (%.2f fps), refused %d, flagged %d; submit avg %.2f max %.2f ms; "
           "slot waits %.1f ms total\n", n, total, n * 1000.0 / total, refused, flagged,
           n ? submit_sum / n : 0, submit_max, wait_sum);
    if (dump && n && !dumps)
        dump_bo(&out[(n - 1) % SLOTS], dump);
    else if (dump && dumped < dumps)
        fprintf(stderr, "dvvk-bench: %d of %d dumps written\n", dumped, dumps);
    if (output != DVVK_OUTPUT_DV) {
        dvvk_hdr_signal sig;
        if (!dvvk_output_signal(e, &sig))
            printf("dvvk-bench: %s signal: mode %u eotf %u max %u cd/m2 min %u (1e-4) cll %u fall %u "
                   "R %u,%u G %u,%u B %u,%u W %u,%u\n",
                   output == DVVK_OUTPUT_SDR ? "SDR" : "HDR10", sig.mode, sig.eotf, sig.max_luminance, sig.min_luminance, sig.max_cll, sig.max_fall,
                   sig.primaries[0][0], sig.primaries[0][1], sig.primaries[1][0], sig.primaries[1][1],
                   sig.primaries[2][0], sig.primaries[2][1], sig.white[0], sig.white[1]);
    }
    dvvk_destroy(e);
    dv_decoder_close(&dec);
    return 0;
}
