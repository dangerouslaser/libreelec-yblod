/* sdr-oracle: SDR output's independent reference (SDR-OUTPUT-PLAN.md, 5: tier
 * 2). The same reconstructed picture the engine maps, rendered by libplacebo
 * itself: pl_render_image with a Dolby Vision colour representation (the
 * RPU's matrices, no reshaping: the picture is the Master Reference
 * reconstruction already) to a BT.709 target, with the colour mapping CB1's
 * Reference Basic pins (spline, perceptual gamut mapping, its constants and
 * LUT sizes) and the frame's L1. Nothing of yblod/dv_map.c or the engine's
 * shaders is in it: what it shares with them is libplacebo's recipe.
 *
 * Not built with the engine (it needs libplacebo with a GPU backend, EGL and
 * GLES): built against CB1's patched libplacebo e2972fdd and run on the build
 * host (docs/intel-dv/OUTPUT-MODES.md says how).
 *
 *   sdr-oracle [options] PARAMS DV.dump OUT.f32
 *     PARAMS     dvvk-map-test --oracle FILE's text: the frame's matrices,
 *                source luminance, L1, primaries and the display
 *     DV.dump    the picture as the Dolby Vision tunnel carries it
 *                (dvvk-bench --dump, output dv): 12-bit 4:2:2 Y'CbCr
 *     OUT.f32    the display's R'G'B', float, 12 bytes a pixel, rows top
 *                first, before any dither (dvvk-sdr-compare --oracle)
 *     --chroma F   where each pixel's chroma comes from. pair (default): the
 *                  engine's own choice, both pixels of a pair take the
 *                  pair's sample; libplacebo then scales nothing and the
 *                  comparison is of the colour mapping alone. linear: the
 *                  odd pixel takes the mean of its pair's sample and the
 *                  next pair's (4:2:2 is sited on the even pixel), computed
 *                  here in float. bilinear, default: the 4:2:2 planes given
 *                  to libplacebo as they are, upscaled by its bilinear
 *                  filter or by its own default: what a renderer that owns
 *                  the chroma would show.
 *     --size W,H   the dump's size (default 3840,2160)
 *     --node PATH  render node (default /dev/dri/renderD128)
 */
#define _GNU_SOURCE
#include <libplacebo/opengl.h>
#include <libplacebo/renderer.h>
#include <libplacebo/tone_mapping.h>
#include <libplacebo/gamut_mapping.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <gbm.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int W = 3840, H = 2160;

static double val[64][16];
static char key[64][32];
static int nkeys;

static const double *get(const char *k, int n)
{
    for (int i = 0; i < nkeys; i++)
        if (!strcmp(key[i], k))
            return val[i];
    fprintf(stderr, "PARAMS: no %s (%d values)\n", k, n);
    exit(1);
}

static void read_params(const char *path)
{
    FILE *f = fopen(path, "r");
    char line[1024];
    if (!f) {
        fprintf(stderr, "%s: can't read\n", path);
        exit(1);
    }
    while (nkeys < 64 && fgets(line, sizeof(line), f)) {
        char *save = NULL, *t = strtok_r(line, " \n", &save);
        if (!t || *t == '#')
            continue;
        snprintf(key[nkeys], sizeof(key[nkeys]), "%s", t);
        for (int n = 0; n < 16 && (t = strtok_r(NULL, " \n", &save)); n++)
            val[nkeys][n] = atof(t);
        nkeys++;
    }
    fclose(f);
}

int main(int argc, char **argv)
{
    const char *node = "/dev/dri/renderD128", *chroma = "pair", *args[3];
    int nargs = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--chroma") && i + 1 < argc)
            chroma = argv[++i];
        else if (!strcmp(argv[i], "--node") && i + 1 < argc)
            node = argv[++i];
        else if (!strcmp(argv[i], "--size") && i + 1 < argc)
            sscanf(argv[++i], "%d,%d", &W, &H);
        else if (nargs < 3)
            args[nargs++] = argv[i];
    }
    if (nargs != 3)
        return fprintf(stderr, "usage: sdr-oracle [--chroma pair|linear|bilinear|default] PARAMS DV.dump OUT.f32\n"), 2;
    read_params(args[0]);

    /* the tunnel's bytes: 12-bit Y per pixel, Cb on even and Cr on odd pixels (co-sited with the even one) */
    FILE *in = fopen(args[1], "rb");
    if (!in)
        return fprintf(stderr, "%s: can't read\n", args[1]), 1;
    fseek(in, 0, SEEK_END);
    size_t size = (size_t)ftell(in), stride = size / H;
    fseek(in, 0, SEEK_SET);
    unsigned char *dump = malloc(size);
    if (!dump || stride < (size_t)W * 4 || fread(dump, 1, size, in) != size)
        return fprintf(stderr, "%s: not a %dx%d dump\n", args[1], W, H), 1;
    fclose(in);
    const int full = !strcmp(chroma, "pair") || !strcmp(chroma, "linear"), linear = !strcmp(chroma, "linear");
    const int cw = full ? W : W / 2;
    float *luma = malloc(sizeof(float) * (size_t)W * H), *cbcr = malloc(sizeof(float) * 2 * (size_t)cw * H);
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x += 2) {
            const unsigned char *p = dump + (size_t)y * stride + 4 * (size_t)x;
            /* the next pair's chroma (the last pair: its own) */
            const unsigned char *q = x + 2 < W ? p + 8 : p;
            float cb = ((p[2] << 4) | (p[0] >> 4)) / 4095.0f, cr = ((p[6] << 4) | (p[4] >> 4)) / 4095.0f;
            float cb1 = ((q[2] << 4) | (q[0] >> 4)) / 4095.0f, cr1 = ((q[6] << 4) | (q[4] >> 4)) / 4095.0f;
            luma[(size_t)y * W + x] = ((p[1] << 4) | (p[0] & 15)) / 4095.0f;
            luma[(size_t)y * W + x + 1] = ((p[5] << 4) | (p[4] & 15)) / 4095.0f;
            if (full) {
                float *c = cbcr + 2 * ((size_t)y * W + x);
                c[0] = cb;
                c[1] = cr;
                c[2] = linear ? 0.5f * (cb + cb1) : cb;
                c[3] = linear ? 0.5f * (cr + cr1) : cr;
            } else {
                cbcr[(size_t)y * W + x] = cb;
                cbcr[(size_t)y * W + x + 1] = cr;
            }
        }
    free(dump);

    int drm = open(node, O_RDWR | O_CLOEXEC);
    struct gbm_device *gbm = drm < 0 ? NULL : gbm_create_device(drm);
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_display = (void *)eglGetProcAddress("eglGetPlatformDisplayEXT");
    EGLDisplay dpy = gbm && get_display ? get_display(EGL_PLATFORM_GBM_KHR, gbm, NULL) : EGL_NO_DISPLAY;
    if (dpy == EGL_NO_DISPLAY || !eglInitialize(dpy, NULL, NULL) || !eglBindAPI(EGL_OPENGL_ES_API))
        return fprintf(stderr, "EGL init failed\n"), 1;
    const EGLint ctx_attr[] = {EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 2, EGL_NONE};
    EGLContext ctx = eglCreateContext(dpy, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, ctx_attr);
    if (!ctx || !eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx))
        return fprintf(stderr, "EGL context failed\n"), 1;
    pl_log log = pl_log_create(PL_API_VER, pl_log_params(.log_cb = pl_log_color, .log_level = PL_LOG_WARN));
    pl_opengl gl = pl_opengl_create(log, pl_opengl_params(
        .get_proc_addr = (pl_voidfunc_t (*)(const char *))eglGetProcAddress, .egl_display = dpy, .egl_context = ctx));
    if (!gl)
        return fprintf(stderr, "pl_opengl_create failed\n"), 1;
    pl_gpu gpu = gl->gpu;
    pl_fmt f1 = pl_find_named_fmt(gpu, "r32f"), f2 = pl_find_named_fmt(gpu, "rg32f"), f4 = pl_find_named_fmt(gpu, "rgba32f");
    if (!f1 || !f2 || !f4 || !(f4->caps & PL_FMT_CAP_RENDERABLE) || !(f2->caps & PL_FMT_CAP_LINEAR))
        return fprintf(stderr, "float formats missing (r32f %d rg32f %d rgba32f %d)\n", !!f1, !!f2, !!f4), 1;
    pl_tex ytex = pl_tex_create(gpu, pl_tex_params(.w = W, .h = H, .format = f1, .sampleable = true, .host_writable = true));
    pl_tex ctex = pl_tex_create(gpu, pl_tex_params(.w = cw, .h = H, .format = f2, .sampleable = true, .host_writable = true));
    pl_tex out = pl_tex_create(gpu, pl_tex_params(.w = W, .h = H, .format = f4, .renderable = true, .host_readable = true));
    if (!ytex || !ctex || !out)
        return fprintf(stderr, "textures failed\n"), 1;
    if (!pl_tex_upload(gpu, pl_tex_transfer_params(.tex = ytex, .ptr = luma)) ||
        !pl_tex_upload(gpu, pl_tex_transfer_params(.tex = ctex, .ptr = cbcr)))
        return fprintf(stderr, "upload failed\n"), 1;

    /* pl_map_avdovi_metadata's fields, without the reshaping */
    static struct pl_dovi_metadata dovi;
    const double *m = get("ycc_to_rgb", 9), *o = get("ycc_offset", 3), *l = get("rgb_to_lms", 9);
    for (int i = 0; i < 9; i++) {
        dovi.nonlinear.m[i / 3][i % 3] = (float)m[i];
        dovi.linear.m[i / 3][i % 3] = (float)l[i];
    }
    for (int i = 0; i < 3; i++)
        dovi.nonlinear_offset[i] = (float)o[i];
    const double *src = get("source_pq", 2), *l1 = get("l1", 2), *prim = get("primaries", 8), *display = get("display", 3);
    struct pl_color_space image_color = {
        .primaries = PL_COLOR_PRIM_BT_2020,
        .transfer = PL_COLOR_TRC_PQ,
        .hdr = {
            .min_luma = pl_hdr_rescale(PL_HDR_PQ, PL_HDR_NITS, (float)src[0] / 4095.0f),
            .max_luma = pl_hdr_rescale(PL_HDR_PQ, PL_HDR_NITS, (float)src[1] / 4095.0f),
            .max_pq_y = (float)l1[0] / 4095.0f,
            .avg_pq_y = (float)l1[1] / 4095.0f,
            .prim = {.red = {prim[0], prim[1]}, .green = {prim[2], prim[3]}, .blue = {prim[4], prim[5]},
                     .white = {prim[6], prim[7]}},
        },
    };
    float sx = 0, sy = 0;
    pl_chroma_location_offset(PL_CHROMA_LEFT, &sx, &sy);
    struct pl_frame image = {
        .num_planes = 2,
        .planes = {
            {.texture = ytex, .components = 1, .component_mapping = {PL_CHANNEL_Y}},
            /* 4:2:2: left sited, no vertical subsampling */
            {.texture = ctex, .components = 2, .component_mapping = {PL_CHANNEL_CB, PL_CHANNEL_CR},
             .shift_x = full ? 0 : sx},
        },
        /* the reshaped picture as CB1 holds it: a 16-bit texture of code / 4095 */
        .repr = {.sys = PL_COLOR_SYSTEM_DOLBYVISION, .levels = PL_COLOR_LEVELS_FULL,
                 .bits = {.sample_depth = 16, .color_depth = 16}, .dovi = &dovi},
        .color = image_color,
        .crop = {0, 0, W, H},
    };
    struct pl_frame target = {
        .num_planes = 1,
        .planes = {{.texture = out, .components = 4, .component_mapping = {0, 1, 2, 3}}},
        .repr = pl_color_repr_rgb,
        .color = {
            .primaries = PL_COLOR_PRIM_BT_709,
            .transfer = display[2] != 0 ? PL_COLOR_TRC_GAMMA22 : PL_COLOR_TRC_BT_1886,
            .hdr = {.min_luma = (float)display[1], .max_luma = (float)display[0]},
        },
        .crop = {0, 0, W, H},
    };
    /* CB1's pinned Basic policy (dvbridge_render.c render_picture) */
    struct pl_color_map_params color_map = {
        .gamut_mapping = &pl_gamut_map_perceptual,
        .tone_mapping_function = &pl_tone_map_spline,
        .gamut_constants = {
            .colorimetric_gamma = 1.80f, .softclip_knee = 0.70f, .softclip_desat = 0.35f,
            .perceptual_deadzone = 0.30f, .perceptual_strength = 0.80f,
        },
        .tone_constants = {
            .knee_adaptation = 0.4f, .knee_minimum = 0.1f, .knee_maximum = 0.8f, .knee_default = 0.4f,
            .knee_offset = 1.0f, .slope_tuning = 1.5f, .slope_offset = 0.2f, .spline_contrast = 0.5f,
            .reinhard_contrast = 0.5f, .linear_knee = 0.3f, .exposure = 1.0f,
        },
        .lut3d_size = {48, 32, 256}, .lut_size = 256,
        .contrast_smoothness = 3.5f,
        .inverse_tone_mapping = false,
        .metadata = l1[0] > 0 ? PL_HDR_METADATA_CIE_Y : PL_HDR_METADATA_HDR10,
    };
    if (!(l1[0] > 0))
        image.color.hdr.max_pq_y = image.color.hdr.avg_pq_y = 0;
    struct pl_render_params params = pl_render_default_params;
    params.color_map_params = &color_map;
    params.peak_detect_params = NULL;
    params.dither_params = NULL;
    params.sigmoid_params = NULL;
    params.frame_mixer = NULL;
    params.min_fbo_precision = 32;
    if (!strcmp(chroma, "bilinear"))
        params.plane_upscaler = &pl_filter_bilinear;
    pl_renderer rr = pl_renderer_create(log, gpu);
    if (!rr || !pl_render_image(rr, &image, &target, &params))
        return fprintf(stderr, "pl_render_image failed\n"), 1;
    if (pl_renderer_get_errors(rr).errors)
        return fprintf(stderr, "libplacebo fell back (renderer errors %#x): not the reference\n",
                       pl_renderer_get_errors(rr).errors), 1;
    float *rgba = malloc(sizeof(float) * 4 * (size_t)W * H);
    if (!rgba || !pl_tex_download(gpu, pl_tex_transfer_params(.tex = out, .ptr = rgba)))
        return fprintf(stderr, "download failed\n"), 1;
    FILE *of = fopen(args[2], "wb");
    if (!of)
        return fprintf(stderr, "%s: can't write\n", args[2]), 1;
    for (size_t i = 0; i < (size_t)W * H; i++)
        fwrite(rgba + 4 * i, sizeof(float), 3, of);
    fclose(of);
    printf("sdr-oracle: %s chroma, target %s %.4g..%.4g cd/m2, metadata %s -> %s\n", chroma,
           display[2] != 0 ? "gamma 2.2" : "BT.1886", display[1], display[0], l1[0] > 0 ? "L1" : "static", args[2]);
    pl_renderer_destroy(&rr);
    pl_tex_destroy(gpu, &ytex);
    pl_tex_destroy(gpu, &ctex);
    pl_tex_destroy(gpu, &out);
    pl_opengl_destroy(&gl);
    pl_log_destroy(&log);
    return 0;
}
