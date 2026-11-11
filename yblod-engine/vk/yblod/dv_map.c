/* Output colour mapping, the CPU half (include/dvvk_map.h,
 * docs/hdr10-output.md): CroqueMr's CB1 "Dolby Vision to HDR10, Reference
 * Basic" (CB1/src/dvbridge_placebo.c dvbridge_hdr10_target and
 * dvbridge_render.c render_picture's session branch) with libplacebo's own
 * pl_shader_color_map_ex decisions and pl_tone_map_generate (the vendored
 * subset in yblod/placebo, CB1's patched libplacebo e2972fdd), so the tone
 * curve is the same numbers as CB1's.
 *
 * SDR output is the same recipe with another target (BT.709, BT.1886 or
 * gamma 2.2, the display's white): the curve now compresses, and
 * pl_shader_color_map_ex's gamut mapping (pl_gamut_map_perceptual from the
 * source's primaries, sampled from pl_gamut_map_generate's LUT as its shader
 * samples the 16-bit texture) and pl_shader_delinearize follow it. CB1 has
 * no SDR circuit: this one is YBLOD's.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include "dvvk_map.h"
#include <libavutil/dovi_meta.h>
#include <libplacebo/colorspace.h>
#include <libplacebo/gamut_mapping.h>
#include <libplacebo/tone_mapping.h>
#include "colorspace.h"   /* yblod/placebo: pl_signal_black */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static double q2d(AVRational r) { return r.den ? (double)r.num / r.den : 0.0; }

/* The one block of a level, NULL if none; *dup set when there are several. */
static const AVDOVIDmData *level(const AVDOVIMetadata *m, uint8_t lv, int *dup)
{
    const AVDOVIDmData *found = NULL;
    for (int i = 0; i < m->num_ext_blocks; i++) {
        const AVDOVIDmData *e = av_dovi_get_ext(m, i);
        if (e->level != lv)
            continue;
        if (found && dup)
            *dup = 1;
        if (!found)
            found = e;
    }
    return found;
}

/* CB1's dvbridge_map_color gates, on what the conversion reads. */
static int mappable(const AVDOVIMetadata *m)
{
    const AVDOVIColorMetadata *c = av_dovi_get_color(m);
    if (c->signal_eotf != 65535 || (c->signal_color_space != 0 && c->signal_color_space != 2) ||
        c->signal_eotf_param0 || c->signal_eotf_param1 || c->signal_eotf_param2 ||
        c->source_min_pq > c->source_max_pq || c->source_max_pq > 4095)
        return 0;
    for (int i = 0; i < 9; i++)
        if (!c->ycc_to_rgb_matrix[i].den || !c->rgb_to_lms_matrix[i].den)
            return 0;
    for (int i = 0; i < 3; i++)
        if (!c->ycc_to_rgb_offset[i].den)
            return 0;
    return 1;
}

static void rows(float out[12], const pl_matrix3x3 *m)
{
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++)
            out[4 * i + j] = m->m[i][j];
        out[4 * i + 3] = 0.0f;
    }
}

static uint64_t fnv1a(const void *p, size_t n)
{
    const unsigned char *b = p;
    uint64_t h = 1469598103934665603ull;
    for (size_t i = 0; i < n; i++)
        h = (h ^ b[i]) * 1099511628211ull;
    return h;
}

/* L9's source primaries (dovi_tool's preset table: 0 P3-D65, 1 BT.709, 2
 * BT.2020, ...): R, G, B, white (x, y). Unknown: P3-D65, the usual Dolby
 * Vision mastering display. */
static void l9_primaries(const AVDOVIMetadata *m, double out[8])
{
    static const double p3[8] = {0.680, 0.320, 0.265, 0.690, 0.150, 0.060, 0.3127, 0.3290};
    static const double bt709[8] = {0.640, 0.330, 0.300, 0.600, 0.150, 0.060, 0.3127, 0.3290};
    static const double bt2020[8] = {0.708, 0.292, 0.170, 0.797, 0.131, 0.046, 0.3127, 0.3290};
    const double *p = p3;
    double custom[8];
    const AVDOVIDmData *l9 = level(m, 9, NULL);
    if (l9) {
        if (l9->l9.source_primary_index == 1)
            p = bt709;
        else if (l9->l9.source_primary_index == 2)
            p = bt2020;
        else if (l9->l9.source_primary_index == 255) {
            const AVColorPrimariesDesc *d = &l9->l9.source_display_primaries;
            for (int i = 0; i < 3; i++) {
                custom[2 * i] = q2d(d->prim.r.x) * (i == 0) + q2d(d->prim.g.x) * (i == 1) + q2d(d->prim.b.x) * (i == 2);
                custom[2 * i + 1] = q2d(d->prim.r.y) * (i == 0) + q2d(d->prim.g.y) * (i == 1) + q2d(d->prim.b.y) * (i == 2);
            }
            custom[6] = q2d(d->wp.x);
            custom[7] = q2d(d->wp.y);
            p = custom;
        }
    }
    memcpy(out, p, 8 * sizeof(*out));
}

/* The same as CTA-861.3 units (0.00002). */
static void source_primaries(const AVDOVIMetadata *m, dvvk_hdr_signal *s)
{
    double p[8];
    l9_primaries(m, p);
    for (int i = 0; i < 3; i++)
        for (int k = 0; k < 2; k++)
            s->primaries[i][k] = (uint16_t)lround(fmin(fmax(p[2 * i + k], 0.0), 1.0) * 50000.0);
    s->white[0] = (uint16_t)lround(p[6] * 50000.0);
    s->white[1] = (uint16_t)lround(p[7] * 50000.0);
}

/* The display an SDR output is made for: white (0: libplacebo's and
 * BT.2408's SDR reference, 203 cd/m2), black (0: white / 1000, libplacebo's
 * SDR contrast). */
static int sdr_display(const dvvk_output_mode *mode, float *white, float *black)
{
    *white = mode->peak_nits > 0 ? mode->peak_nits : PL_COLOR_SDR_WHITE;
    *black = mode->min_nits > 0 ? mode->min_nits : *white / PL_COLOR_SDR_CONTRAST;
    return isfinite(*white) && isfinite(*black) && *white >= 40 && *white <= 1000 && *black < *white / 20 &&
           !(mode->flags & ~(DVVK_SDR_GAMMA22 | DVVK_SDR_LIMITED | DVVK_SDR_NO_DITHER));
}

int dvvk_map_plan(const dvvk_output_mode *mode, const void *metadata, size_t metadata_size, dvvk_map *out)
{
    if (!mode || !metadata || !out || metadata_size < sizeof(AVDOVIMetadata) ||
        (uintptr_t)metadata % _Alignof(AVDOVIMetadata))
        return -1;
    const int sdr = mode->mode == DVVK_OUTPUT_SDR;
    if (mode->mode != DVVK_OUTPUT_HDR10 && mode->mode != DVVK_OUTPUT_HDR10PLUS && !sdr)
        return -1;
    const AVDOVIMetadata *m = metadata;
    if (!mappable(m))
        return -2;
    const AVDOVIColorMetadata *colour = av_dovi_get_color(m);
    int dup = 0;
    const AVDOVIDmData *l1 = level(m, 1, &dup), *l6 = level(m, 6, NULL);

    /* dvbridge_hdr10_target: the output's peak is L6's mastering maximum, else
     * the source's maximum (source_max_pq). */
    float peak = l6 && l6->l6.max_luminance > 0 && l6->l6.max_luminance <= 10000 ? l6->l6.max_luminance : 0;
    if (!peak && colour->source_max_pq > 0 && colour->source_max_pq <= 4095)
        peak = pl_hdr_rescale(PL_HDR_PQ, PL_HDR_NITS, colour->source_max_pq / 4095.0f);
    if (!isfinite(peak) || peak < 1 || peak > 10000)
        return -2;
    float white = 0, black = 0;
    if (sdr ? !sdr_display(mode, &white, &black) : mode->peak_nits > 0)
        return -1;   /* HDR10 for a target display: not yet */

    /* pl_map_avdovi_metadata, then render_picture's Basic branch */
    struct pl_color_space src = {
        .primaries = PL_COLOR_PRIM_BT_2020,
        .transfer = PL_COLOR_TRC_PQ,
        .hdr = {
            .min_luma = pl_hdr_rescale(PL_HDR_PQ, PL_HDR_NITS, colour->source_min_pq / 4095.0f),
            .max_luma = pl_hdr_rescale(PL_HDR_PQ, PL_HDR_NITS, colour->source_max_pq / 4095.0f),
        },
    };
    enum pl_hdr_metadata_type meta;
    if (l1 && l1->l1.min_pq <= l1->l1.avg_pq && l1->l1.avg_pq <= l1->l1.max_pq && l1->l1.max_pq <= 4095 &&
        l1->l1.max_pq) {
        src.hdr.max_pq_y = l1->l1.max_pq / 4095.0f;
        src.hdr.avg_pq_y = l1->l1.avg_pq / 4095.0f;
        meta = PL_HDR_METADATA_CIE_Y;
    } else {
        src.hdr.max_pq_y = src.hdr.avg_pq_y = 0;
        meta = PL_HDR_METADATA_HDR10;
    }
    struct pl_color_space dst = {
        .primaries = PL_COLOR_PRIM_BT_2020,
        .transfer = PL_COLOR_TRC_PQ,
        .hdr = {.min_luma = PL_COLOR_HDR_BLACK, .max_luma = peak},
    };
    if (sdr) {
        /* The gamut the content was made in is the mapper's input (CB1's
         * Expert circuit does the same with L9): BT.2020 as the container
         * would desaturate every title as if it filled it. */
        double prim[8];
        l9_primaries(m, prim);
        src.hdr.prim = (struct pl_raw_primaries) {
            .red = {prim[0], prim[1]}, .green = {prim[2], prim[3]}, .blue = {prim[4], prim[5]},
            .white = {prim[6], prim[7]},
        };
        if (!pl_primaries_valid(&src.hdr.prim))
            src.hdr.prim = *pl_raw_primaries_get(PL_COLOR_PRIM_DISPLAY_P3);
        dst = (struct pl_color_space) {
            .primaries = PL_COLOR_PRIM_BT_709,
            .transfer = mode->flags & DVVK_SDR_GAMMA22 ? PL_COLOR_TRC_GAMMA22 : PL_COLOR_TRC_BT_1886,
            .hdr = {.min_luma = black, .max_luma = white},
        };
    }

    /* pl_shader_color_map_ex with CB1's pinned Basic parameters */
    pl_color_space_infer_map(&src, &dst);
    struct pl_tone_map_params tone = {
        .function = &pl_tone_map_spline,
        .constants = {
            .knee_adaptation = 0.4f, .knee_minimum = 0.1f, .knee_maximum = 0.8f, .knee_default = 0.4f,
            .knee_offset = 1.0f, .slope_tuning = 1.5f, .slope_offset = 0.2f, .spline_contrast = 0.5f,
            .reinhard_contrast = 0.5f, .linear_knee = 0.3f, .exposure = 1.0f,
        },
        .input_scaling = PL_HDR_PQ,
        .output_scaling = PL_HDR_PQ,
        .lut_size = DVVK_MAP_LUT,
        .hdr = src.hdr,
    };
    pl_color_space_nominal_luma_ex(pl_nominal_luma_params(.color = &src, .metadata = meta, .scaling = PL_HDR_PQ,
                                                          .out_min = &tone.input_min, .out_max = &tone.input_max,
                                                          .out_avg = &tone.input_avg));
    pl_color_space_nominal_luma_ex(pl_nominal_luma_params(.color = &dst, .metadata = PL_HDR_METADATA_HDR10,
                                                          .scaling = PL_HDR_PQ, .out_min = &tone.output_min,
                                                          .out_max = &tone.output_max));
    pl_tone_map_params_infer(&tone);
    if (fabs(tone.input_max - tone.output_max) < 1e-6)
        tone.output_max = tone.input_max;
    if (fabs(tone.input_min - tone.output_min) < 1e-6)
        tone.output_min = tone.input_min;
    tone.input_min = pl_signal_black(tone.input_min, tone.input_scaling);
    tone.output_min = pl_signal_black(tone.output_min, tone.output_scaling);
    tone.input_max = fmaxf(tone.input_max, tone.output_max);   /* no inverse tone mapping */

    struct pl_gamut_map_params gamut = {
        .function = &pl_gamut_map_perceptual,
        .input_gamut = src.hdr.prim,
        .output_gamut = dst.hdr.prim,
    };
    if (sdr)
        pl_color_space_nominal_luma_ex(pl_nominal_luma_params(.color = &dst, .metadata = PL_HDR_METADATA_HDR10,
                                                              .scaling = PL_HDR_PQ, .out_min = &gamut.min_luma,
                                                              .out_max = &gamut.max_luma));
    gamut.min_luma = pl_signal_black(gamut.min_luma, PL_HDR_PQ);
    if (pl_primaries_compatible(&gamut.input_gamut, &gamut.output_gamut))
        gamut.output_gamut = pl_primaries_clip(&gamut.output_gamut, &gamut.input_gamut);
    const int need_gamut = !pl_gamut_map_params_noop(&gamut);
    if (need_gamut && !sdr)
        return -2;   /* Basic's source and output are both BT.2020: never */

    memset(out, 0, sizeof(*out));
    dvvk_map_gpu *g = &out->gpu;
    /* pl_color_repr_decode for Dolby Vision: the RPU matrix on the reshaped
     * signal (code / 4095), its offsets scaled by 2^16 / (2^16 - 1) (the
     * reshaped texture's 16 bits) and subtracted through the matrix. */
    const double scale = 65536.0 / 65535.0;
    for (int i = 0; i < 3; i++) {
        double c = 0;
        for (int j = 0; j < 3; j++) {
            double v = (float)q2d(colour->ycc_to_rgb_matrix[3 * i + j]);
            g->ycc[4 * i + j] = (float)v;
            c -= v * (float)q2d(colour->ycc_to_rgb_offset[j]) * scale;
        }
        g->ycc_offset[i] = (float)c;
    }
    pl_matrix3x3 dovi_lms2rgb = {{
        {3.06441879, -2.16597676, 0.10155818},
        {-0.65612108, 1.78554118, -0.12943749},
        {0.01736321, -0.04725154, 1.03004253},
    }};
    pl_matrix3x3 linear;
    for (int i = 0; i < 9; i++)
        (&linear.m[0][0])[i] = (float)q2d(colour->rgb_to_lms_matrix[i]);
    pl_matrix3x3_mul(&dovi_lms2rgb, &linear);
    rows(g->src_lms2rgb, &dovi_lms2rgb);
    pl_matrix3x3 rgb2lms = pl_ipt_rgb2lms(pl_raw_primaries_get(src.primaries));
    pl_matrix3x3 lms2rgb = pl_ipt_lms2rgb(pl_raw_primaries_get(dst.primaries));
    rows(g->rgb2lms, &rgb2lms);
    rows(g->lms2rgb, &lms2rgb);
    rows(g->lms2ipt, &pl_ipt_lms2ipt);
    rows(g->ipt2lms, &pl_ipt_ipt2lms);
    g->lut_n = 65;
    /* HDR10+ (CB1's DV -> HDR10+): the reconstruction in BT.2020 PQ without
     * tone mapping; the receiver applies the HDR10+ curve once. */
    if (mode->mode != DVVK_OUTPUT_HDR10PLUS && !pl_tone_map_params_noop(&tone)) {
        g->flags |= DVVK_MAP_TONE;
        if (meta == PL_HDR_METADATA_CIE_Y)
            g->flags |= DVVK_MAP_L1;
        g->tone_in[0] = tone.input_min;
        g->tone_in[1] = tone.input_max;
        g->tone_in[2] = 1.0f / (tone.input_max - tone.input_min);
        g->tone_out[0] = tone.output_min;
        g->tone_out[1] = tone.output_max;
        pl_tone_map_generate(g->tone_lut, &tone);
    }
    if (sdr) {
        g->flags |= DVVK_MAP_SDR;
        if (!(mode->flags & DVVK_SDR_NO_DITHER))
            g->flags |= DVVK_MAP_DITHER_ON;
        if (need_gamut) {
            g->flags |= DVVK_MAP_GAMUT;
            const float range = gamut.max_luma - gamut.min_luma;
            g->gamut_at[0] = 1.0f / range;
            g->gamut_at[1] = -gamut.min_luma / range;
            memcpy(out->gamut_prim[0], &gamut.input_gamut, sizeof(out->gamut_prim[0]));
            memcpy(out->gamut_prim[1], &gamut.output_gamut, sizeof(out->gamut_prim[1]));
            out->gamut_luma[0] = gamut.min_luma;
            out->gamut_luma[1] = gamut.max_luma;
            out->gamut_key = fnv1a(out->gamut_prim, sizeof(out->gamut_prim) + sizeof(out->gamut_luma));
            g->gamut_key[0] = (uint32_t)out->gamut_key;
            g->gamut_key[1] = (uint32_t)(out->gamut_key >> 32);
        }
        /* pl_shader_delinearize, on light where 1 is 10000 cd/m2 */
        float lo, hi;
        pl_color_space_nominal_luma_ex(pl_nominal_luma_params(.color = &dst, .metadata = PL_HDR_METADATA_HDR10,
                                                              .scaling = PL_HDR_NORM, .out_min = &lo, .out_max = &hi));
        lo = pl_signal_black(lo, PL_HDR_NORM) * (PL_COLOR_SDR_WHITE / 10000.0f);
        hi *= PL_COLOR_SDR_WHITE / 10000.0f;
        if (dst.transfer == PL_COLOR_TRC_BT_1886) {
            const float lb = powf(lo, 1 / 2.4f), lw = powf(hi, 1 / 2.4f);
            g->out_trc[0] = 1.0f / powf(lw - lb, 2.4f);
            g->out_trc[2] = 1 / 2.4f;
            g->out_trc[3] = lb / (lw - lb);
        } else {
            g->out_trc[0] = 1.0f / (hi - lo);
            g->out_trc[1] = -lo / (hi - lo);
            g->out_trc[2] = 1 / 2.2f;
        }
        g->out_code[0] = mode->flags & DVVK_SDR_LIMITED ? 219.0f : 255.0f;
        g->out_code[1] = mode->flags & DVVK_SDR_LIMITED ? 16.0f : 0.0f;
    }
    out->key = fnv1a(g, sizeof(*g));   /* black_in/out still 0: not in the key */

    dvvk_hdr_signal *s = &out->signal;
    s->mode = mode->mode;
    if (sdr) {
        /* an ordinary picture: no HDR signalling; what it was made for */
        static const uint16_t bt709[4][2] = {{32000, 16500}, {15000, 30000}, {7500, 3000}, {15635, 16450}};
        memcpy(s->primaries, bt709, sizeof(s->primaries));
        memcpy(s->white, bt709[3], sizeof(s->white));
        s->max_luminance = (uint16_t)lroundf(white);
        s->min_luminance = (uint16_t)lroundf(fminf(black * 10000.0f, 65535.0f));
        return 0;
    }
    s->eotf = 2;
    source_primaries(m, s);
    s->max_luminance = (uint16_t)ceilf(peak);
    /* CB1 (Kodi's HDR10 signal): min 0 */
    /* CB1: source MaxCLL/MaxFALL don't measure the converted output: 0 (unknown). */
    return 0;
}

/* tools/dither-table.c's output: libplacebo's 64 x 64 blue noise
 * (pl_generate_blue_noise, e2972fdd; pl_dither_default_params' matrix), the
 * ranks themselves. A table, not generated here: the generator's floating
 * point would make the pattern, and so the output's bytes, the C library's. */
static const uint16_t dither_rank[DVVK_MAP_DITHER * DVVK_MAP_DITHER] = {
#include "dither_blue64.h"
};

void dvvk_map_tables(const dvvk_map *map, uint32_t *tables)
{
    for (int i = 0; i < DVVK_MAP_DITHER * DVVK_MAP_DITHER; i++)
        tables[i] = dither_rank[i];
    if (!(map->gpu.flags & DVVK_MAP_GAMUT))
        return;
    struct pl_gamut_map_params gamut = {
        .function = &pl_gamut_map_perceptual,
        /* CB1's pinned Basic constants (libplacebo's defaults) */
        .constants = {
            .colorimetric_gamma = 1.80f, .softclip_knee = 0.70f, .softclip_desat = 0.35f,
            .perceptual_deadzone = 0.30f, .perceptual_strength = 0.80f,
        },
        .min_luma = map->gamut_luma[0],
        .max_luma = map->gamut_luma[1],
        .lut_size_I = DVVK_MAP_GAMUT_I,
        .lut_size_C = DVVK_MAP_GAMUT_C,
        .lut_size_h = DVVK_MAP_GAMUT_H,
        .lut_stride = 3,
    };
    memcpy(&gamut.input_gamut, map->gamut_prim[0], sizeof(gamut.input_gamut));
    memcpy(&gamut.output_gamut, map->gamut_prim[1], sizeof(gamut.output_gamut));
    const size_t nodes = (size_t)DVVK_MAP_GAMUT_I * DVVK_MAP_GAMUT_C * DVVK_MAP_GAMUT_H;
    float *lut = malloc(nodes * 3 * sizeof(float));
    uint32_t *o = tables + DVVK_MAP_GAMUT_AT;
    if (!lut) {
        /* no memory: the identity, a node at a time (colours outside the
         * display's gamut then clip) */
        gamut.function = &pl_gamut_map_clip;
        gamut.lut_size_I = gamut.lut_size_C = gamut.lut_size_h = 1;
    } else
        pl_gamut_map_generate(lut, &gamut);
    /* fill_gamut_lut: the 16-bit texels (alpha unused) */
    for (size_t i = 0; i < nodes; i++) {
        float node[3];
        if (!lut) {
            const float cx = (float)(i / DVVK_MAP_GAMUT_I % DVVK_MAP_GAMUT_C) / (DVVK_MAP_GAMUT_C - 1);
            const float hx = (float)(i / DVVK_MAP_GAMUT_I / DVVK_MAP_GAMUT_C) / (DVVK_MAP_GAMUT_H - 1);
            const float ix = (float)(i % DVVK_MAP_GAMUT_I) / (DVVK_MAP_GAMUT_I - 1);
            const float h = (float)(M_PI * (2.0 * hx - 1.0));
            node[0] = gamut.min_luma + (gamut.max_luma - gamut.min_luma) * ix;
            node[1] = 0.5f * cx * cosf(h);
            node[2] = 0.5f * cx * sinf(h);
        }
        const float *in = lut ? lut + 3 * i : node;
        uint32_t q[3];
        q[0] = (uint32_t)fminf(fmaxf(roundf(in[0] * UINT16_MAX), 0), UINT16_MAX);
        q[1] = (uint32_t)fminf(fmaxf(roundf(in[1] * UINT16_MAX + (UINT16_MAX >> 1)), 0), UINT16_MAX);
        q[2] = (uint32_t)fminf(fmaxf(roundf(in[2] * UINT16_MAX + (UINT16_MAX >> 1)), 0), UINT16_MAX);
        o[2 * i] = q[0] | q[1] << 16;
        o[2 * i + 1] = q[2];
    }
    free(lut);
}

static double pq_eotf(double v)
{
    const double m1 = 2610.0 / 16384, m2 = 2523.0 / 32, c1 = 3424.0 / 4096, c2 = 2413.0 / 128, c3 = 2392.0 / 128;
    double p = pow(fmax(v, 0.0), 1.0 / m2);
    return pow(fmax(p - c1, 0.0) / (c2 - c3 * p), 1.0 / m1);
}

static double pq_oetf(double v)
{
    const double m1 = 2610.0 / 16384, m2 = 2523.0 / 32, c1 = 3424.0 / 4096, c2 = 2413.0 / 128, c3 = 2392.0 / 128;
    double p = pow(fmax(v, 0.0), m1);
    return pow((c1 + c2 * p) / (1.0 + c3 * p), m2);
}

static void mul(const float m[12], const double in[3], double out[3])
{
    for (int i = 0; i < 3; i++)
        out[i] = m[4 * i] * in[0] + m[4 * i + 1] * in[1] + m[4 * i + 2] * in[2];
}

static double tone_map(const dvvk_map_gpu *p, double x)
{
    double t = (x - p->tone_in[0]) * p->tone_in[2];
    t = fmin(fmax(t, 0.0), 1.0) * (DVVK_MAP_LUT - 1);
    int i = (int)floor(t);
    if (i >= DVVK_MAP_LUT - 1)
        return p->tone_lut[DVVK_MAP_LUT - 1];
    double f = t - i;
    return p->tone_lut[i] * (1.0 - f) + p->tone_lut[i + 1] * f;
}

/* pl_shader_color_map_ex's gamut LUT lookup: the 16-bit texture sampled
 * linearly at I, 2 C, h / 2 pi + 0.5 (texel centres at the ends of each
 * axis), its P and T stored with an offset of 32767 and read with 32768. A
 * neutral colour has no hue: any (0). */
static void gamut_map(const dvvk_map_gpu *p, const uint32_t *tables, double ipt[3])
{
    static const int n[3] = {DVVK_MAP_GAMUT_I, DVVK_MAP_GAMUT_C, DVVK_MAP_GAMUT_H};
    double h = ipt[1] == 0.0 && ipt[2] == 0.0 ? 0.0 : atan2(ipt[2], ipt[1]);
    double idx[3] = {p->gamut_at[0] * ipt[0] + p->gamut_at[1], 2.0 * sqrt(ipt[1] * ipt[1] + ipt[2] * ipt[2]),
                     h * (0.5 / M_PI) + 0.5};
    int i0[3];
    double f[3], v[3] = {0, 0, 0};
    for (int k = 0; k < 3; k++) {
        double t = fmin(fmax(idx[k], 0.0), 1.0) * (n[k] - 1);
        i0[k] = (int)fmin(floor(t), n[k] - 2);
        f[k] = t - i0[k];
    }
    const uint32_t *lut = tables + DVVK_MAP_GAMUT_AT;
    for (int c = 0; c < 8; c++) {
        int di = c & 1, dc = c >> 1 & 1, dh = c >> 2;
        double w = (di ? f[0] : 1.0 - f[0]) * (dc ? f[1] : 1.0 - f[1]) * (dh ? f[2] : 1.0 - f[2]);
        const uint32_t *q = lut + 2 * (((size_t)(i0[2] + dh) * n[1] + i0[1] + dc) * n[0] + i0[0] + di);
        v[0] += w * (q[0] & 0xffff);
        v[1] += w * (q[0] >> 16);
        v[2] += w * (q[1] & 0xffff);
    }
    ipt[0] = v[0] / 65535.0;
    ipt[1] = (v[1] - 32768.0) / 65535.0;
    ipt[2] = (v[2] - 32768.0) / 65535.0;
}

uint32_t dvvk_map_rgb(const dvvk_map_gpu *p, const uint32_t *tables, const double nl[3], double rgb[3])
{
    double n[3], lin[3];
    uint32_t regime = 0;
    for (int i = 0; i < 3; i++)
        n[i] = pq_eotf(nl[i]);
    mul(p->src_lms2rgb, n, lin);
    /* pl_shader_decode_color's PQ OETF, then the renderer's linearisation:
     * negative light is gone after the first */
    for (int i = 0; i < 3; i++) {
        regime |= (uint32_t)(lin[i] < 0.0) << i;
        lin[i] = fmax(lin[i], 0.0);
    }
    /* SDR: always through IPT, where the gamut is mapped (and the output's
     * primaries are another LMS to RGB) */
    if (p->flags & (DVVK_MAP_TONE | DVVK_MAP_SDR)) {
        double lms[3], ipt[3];
        mul(p->rgb2lms, lin, lms);
        for (int i = 0; i < 3; i++)
            lms[i] = pq_oetf(lms[i]);
        mul(p->lms2ipt, lms, ipt);
        if (p->flags & DVVK_MAP_TONE) {
            double i0 = ipt[0];
            regime |= (uint32_t)(i0 <= p->tone_in[0]) << 3 | (uint32_t)(i0 >= p->tone_in[1]) << 4;
            ipt[0] = tone_map(p, ipt[0]);
            double h0 = ((i0 - 6.0) * i0 + 9.0) * i0, h1 = ((ipt[0] - 6.0) * ipt[0] + 9.0) * ipt[0];
            double k = ipt[0] > 0.0 && h0 > 0.0 ? fmin(i0 / ipt[0], h1 / h0) : 0.0;
            regime |= (uint32_t)(ipt[0] > 0.0 && h0 > 0.0 && i0 / ipt[0] < h1 / h0) << 5 |
                      (uint32_t)!(ipt[0] > 0.0 && h0 > 0.0) << 6;
            ipt[1] *= k;
            ipt[2] *= k;
        }
        if (p->flags & DVVK_MAP_GAMUT)
            gamut_map(p, tables, ipt);
        mul(p->ipt2lms, ipt, lms);
        for (int i = 0; i < 3; i++) {
            regime |= (uint32_t)(lms[i] < 0.0) << (7 + i);
            lms[i] = pq_eotf(lms[i]);
        }
        mul(p->lms2rgb, lms, lin);
    }
    if (p->flags & DVVK_MAP_SDR) {
        /* pl_shader_delinearize; a display has no codes outside 0..1 */
        for (int i = 0; i < 3; i++) {
            double v = pow(fmax(p->out_trc[0] * lin[i] + p->out_trc[1], 0.0), p->out_trc[2]) - p->out_trc[3];
            regime |= (uint32_t)(v < 0.0) << (10 + i) | (uint32_t)(v > 1.0) << (13 + i);
            rgb[i] = fmin(fmax(v, 0.0), 1.0);
        }
        return regime;
    }
    for (int i = 0; i < 3; i++) {
        regime |= (uint32_t)(lin[i] < 0.0) << (10 + i);
        rgb[i] = pq_oetf(lin[i]);
    }
    return regime;
}

void dvvk_map_nonlinear(const dvvk_map_gpu *p, const double codes[3], double nl[3])
{
    double v[3];
    for (int i = 0; i < 3; i++)
        v[i] = codes[i] / 4095.0;
    mul(p->ycc, v, nl);
    for (int i = 0; i < 3; i++)
        nl[i] = fmin(fmax(nl[i] + p->ycc_offset[i], 0.0), 1.0);
}

void dvvk_map_ycc(const double rgb[3], double out[3])
{
    /* BT.2020 non-constant luminance Y'CbCr of the PQ R'G'B' */
    double y = 0.2627 * rgb[0] + 0.6780 * rgb[1] + 0.0593 * rgb[2];
    out[0] = y;
    out[1] = (rgb[2] - y) / 1.8814;
    out[2] = (rgb[0] - y) / 1.4746;
}

void dvvk_map_sample(const dvvk_map_gpu *p, const uint32_t *tables, const double codes[3], double out[3])
{
    double nl[3], rgb[3];
    dvvk_map_nonlinear(p, codes, nl);
    dvvk_map_rgb(p, tables, nl, rgb);
    if (p->flags & DVVK_MAP_SDR)
        memcpy(out, rgb, sizeof(rgb));
    else
        dvvk_map_ycc(rgb, out);
}

uint32_t dvvk_map_sdr_code(const dvvk_map_gpu *p, const uint32_t *tables, double v, uint32_t x, uint32_t y)
{
    /* pl_shader_dither's blue noise: floor(code + bias), bias the pattern's
     * rank / its size (0 .. 1); rounding is the bias one half */
    double bias = 0.5;
    if (p->flags & DVVK_MAP_DITHER_ON)
        bias = tables[(y % DVVK_MAP_DITHER) * DVVK_MAP_DITHER + x % DVVK_MAP_DITHER] /
               (double)(DVVK_MAP_DITHER * DVVK_MAP_DITHER);
    return (uint32_t)floor(p->out_code[0] * fmin(fmax(v, 0.0), 1.0) + bias) + (uint32_t)p->out_code[1];
}

static uint32_t code(double v, double offset, double scale)
{
    return (uint32_t)fmin(fmax(floor(offset + scale * v + 0.5), 16.0), 4079.0);
}

void dvvk_map_set_black(dvvk_map_gpu *p, const uint32_t *tables, const uint32_t black[3])
{
    double c[3] = {black[0], black[1], black[2]}, o[3];
    dvvk_map_sample(p, tables, c, o);
    for (int i = 0; i < 3; i++)
        p->black_in[i] = black[i];
    if (p->flags & DVVK_MAP_SDR) {
        for (int i = 0; i < 3; i++)
            p->black_out[i] = (uint32_t)floor(p->out_code[0] * o[i] + 0.5) + (uint32_t)p->out_code[1];
        return;
    }
    p->black_out[0] = code(o[0], 256.0, 3504.0);
    p->black_out[1] = code(o[1], 2048.0, 3584.0);
    p->black_out[2] = code(o[2], 2048.0, 3584.0);
}
