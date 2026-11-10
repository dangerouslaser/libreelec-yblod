/* Output colour mapping, the CPU half (include/dvvk_map.h,
 * docs/hdr10-output.md): CroqueMr's CB1 "Dolby Vision to HDR10, Reference
 * Basic" (CB1/src/dvbridge_placebo.c dvbridge_hdr10_target and
 * dvbridge_render.c render_picture's session branch) with libplacebo's own
 * pl_shader_color_map_ex decisions and pl_tone_map_generate (the vendored
 * subset in yblod/placebo, CB1's patched libplacebo e2972fdd), so the tone
 * curve is the same numbers as CB1's.
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
 * BT.2020, ...), as CTA-861.3 units (0.00002). Unknown: P3-D65, the usual
 * Dolby Vision mastering display. */
static void source_primaries(const AVDOVIMetadata *m, dvvk_hdr_signal *s)
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
    for (int i = 0; i < 3; i++)
        for (int k = 0; k < 2; k++)
            s->primaries[i][k] = (uint16_t)lround(fmin(fmax(p[2 * i + k], 0.0), 1.0) * 50000.0);
    s->white[0] = (uint16_t)lround(p[6] * 50000.0);
    s->white[1] = (uint16_t)lround(p[7] * 50000.0);
}

int dvvk_map_plan(const dvvk_output_mode *mode, const void *metadata, size_t metadata_size, dvvk_map *out)
{
    if (!mode || !metadata || !out || metadata_size < sizeof(AVDOVIMetadata) ||
        (uintptr_t)metadata % _Alignof(AVDOVIMetadata))
        return -1;
    if (mode->mode != DVVK_OUTPUT_HDR10 && mode->mode != DVVK_OUTPUT_HDR10PLUS)
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
    if (mode->peak_nits > 0)
        return -1;   /* target-display modes: not yet */

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
    if (pl_primaries_compatible(&gamut.input_gamut, &gamut.output_gamut))
        gamut.output_gamut = pl_primaries_clip(&gamut.output_gamut, &gamut.input_gamut);
    if (!pl_gamut_map_params_noop(&gamut))
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
    if (mode->mode == DVVK_OUTPUT_HDR10 && !pl_tone_map_params_noop(&tone)) {
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
    out->key = fnv1a(g, sizeof(*g));   /* black_in/out still 0: not in the key */

    dvvk_hdr_signal *s = &out->signal;
    s->mode = mode->mode;
    s->eotf = 2;
    source_primaries(m, s);
    s->max_luminance = (uint16_t)ceilf(peak);
    /* CB1 (Kodi's HDR10 signal): min 0 */
    /* CB1: source MaxCLL/MaxFALL don't measure the converted output: 0 (unknown). */
    return 0;
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

uint32_t dvvk_map_rgb(const dvvk_map_gpu *p, const double nl[3], double rgb[3])
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
    if (p->flags & DVVK_MAP_TONE) {
        double lms[3], ipt[3];
        mul(p->rgb2lms, lin, lms);
        for (int i = 0; i < 3; i++)
            lms[i] = pq_oetf(lms[i]);
        mul(p->lms2ipt, lms, ipt);
        double i0 = ipt[0];
        regime |= (uint32_t)(i0 <= p->tone_in[0]) << 3 | (uint32_t)(i0 >= p->tone_in[1]) << 4;
        ipt[0] = tone_map(p, ipt[0]);
        double h0 = ((i0 - 6.0) * i0 + 9.0) * i0, h1 = ((ipt[0] - 6.0) * ipt[0] + 9.0) * ipt[0];
        double k = ipt[0] > 0.0 && h0 > 0.0 ? fmin(i0 / ipt[0], h1 / h0) : 0.0;
        regime |= (uint32_t)(ipt[0] > 0.0 && h0 > 0.0 && i0 / ipt[0] < h1 / h0) << 5 |
                  (uint32_t)!(ipt[0] > 0.0 && h0 > 0.0) << 6;
        ipt[1] *= k;
        ipt[2] *= k;
        mul(p->ipt2lms, ipt, lms);
        for (int i = 0; i < 3; i++) {
            regime |= (uint32_t)(lms[i] < 0.0) << (7 + i);
            lms[i] = pq_eotf(lms[i]);
        }
        mul(p->lms2rgb, lms, lin);
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

void dvvk_map_sample(const dvvk_map_gpu *p, const double codes[3], double out[3])
{
    double nl[3], rgb[3];
    dvvk_map_nonlinear(p, codes, nl);
    dvvk_map_rgb(p, nl, rgb);
    dvvk_map_ycc(rgb, out);
}

static uint32_t code(double v, double offset, double scale)
{
    return (uint32_t)fmin(fmax(floor(offset + scale * v + 0.5), 16.0), 4079.0);
}

void dvvk_map_set_black(dvvk_map_gpu *p, const uint32_t black[3])
{
    double c[3] = {black[0], black[1], black[2]}, o[3];
    dvvk_map_sample(p, c, o);
    for (int i = 0; i < 3; i++)
        p->black_in[i] = black[i];
    p->black_out[0] = code(o[0], 256.0, 3504.0);
    p->black_out[1] = code(o[1], 2048.0, 3584.0);
    p->black_out[2] = code(o[2], 2048.0, 3584.0);
}
