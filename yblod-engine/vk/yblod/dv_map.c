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
 * no SDR circuit: this one is YBLOD's. A plain HLG video is a source of it
 * too (DVVK_SDR_HLG): pl_shader_linearize's HLG in place of PQ's EOTF.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include "dvvk_map.h"
#include <libavutil/dovi_meta.h>
#include <libplacebo/colorspace.h>
#include <libplacebo/gamut_mapping.h>
#include <libplacebo/tone_mapping.h>
#include "colorspace.h"   /* yblod/placebo: pl_signal_black */
#include "cb1_expert_tone.h"   /* yblod/placebo: CB1's Expert tone LUT */
/* yblod-engine/src: CB1's Expert plan (build.rs has it on the path;
 * tools.sh, which builds dvvk-map-test, has only the source tree) */
#if __has_include("cb1_hdr10_expert.h")
#include "cb1_hdr10_expert.h"
#else
#include "../../src/cb1_hdr10_expert.h"
#endif
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
 * SDR contrast; with DVVK_SDR_BLACK as given, CB1's 0 to 5 cd/m2), gamma (0:
 * BT.1886; else a pure power). src/map.rs mode_supported says the same. */
static int sdr_display(const dvvk_output_mode *mode, float *white, float *black, float *gamma)
{
    const uint32_t f = mode->flags;
    const uint32_t g = mode->reserved[DVVK_SDR_GAMMA_WORD];
    *white = mode->peak_nits > 0 ? mode->peak_nits : PL_COLOR_SDR_WHITE;
    *black = f & DVVK_SDR_BLACK || mode->min_nits > 0 ? mode->min_nits : *white / PL_COLOR_SDR_CONTRAST;
    *gamma = f & DVVK_SDR_POWER ? g / 1000.0f : f & DVVK_SDR_GAMMA22 ? 2.2f : 0.0f;
    if (f & DVVK_SDR_POWER ? (f & DVVK_SDR_GAMMA22) || g < 1800 || g > 2800 : g != 0)
        return 0;
    for (int i = 1; i < 4; i++)
        if (mode->reserved[i])
            return 0;
    if (f & DVVK_SDR_BLACK ? !(*black >= 0 && *black <= 5 && *black < *white) : !(*black < *white / 20))
        return 0;
    return isfinite(*white) && isfinite(*black) && *white >= 20 && *white <= 1000 &&
           !(f & ~(DVVK_SDR_GAMMA22 | DVVK_SDR_LIMITED | DVVK_SDR_NO_DITHER | DVVK_SDR_HLG | DVVK_SDR_POWER |
                   DVVK_SDR_BLACK | DVVK_SDR_BT2020));
}

/* The display a display-targeted mode states, as CB1's policy (Kodi's
 * DVOutputSettings: tv, expert_black_nits, the LLDV EDID fields): 1 a
 * valid one, 0 not; -1 not such a mode. */
static int expert_policy(const dvvk_output_mode *mode, const dvvk_display_primaries *display,
                         struct dvbridge_policy *policy)
{
    const int lldv = mode->mode == DVVK_OUTPUT_LLDV;
    if (!lldv && !(mode->mode == DVVK_OUTPUT_HDR10 && (mode->flags & DVVK_HDR10_TARGET)))
        return -1;
    if (mode->flags & ~(lldv ? (uint32_t)DVVK_LLDV_10BIT : (uint32_t)DVVK_HDR10_TARGET))
        return 0;
    for (int i = 1; i < 4; i++)
        if (mode->reserved[i])
            return 0;
    uint32_t gamut = mode->reserved[DVVK_TARGET_GAMUT_WORD];
    if (gamut > DVVK_GAMUT_BT2020)
        return 0;
    /* CB1's defaults: P3-D65 for HDR10 Rendering Reference, BT.2020 for player-led (Kodi) */
    if (gamut == DVVK_GAMUT_DEFAULT)
        gamut = lldv ? DVVK_GAMUT_BT2020 : DVVK_GAMUT_P3D65;
    *policy = (struct dvbridge_policy) {
        .revision = 1,
        .mode = lldv ? DVBRIDGE_MODE_PLAYER_LED : DVBRIDGE_MODE_HDR10_EXPERT,
        .tv = {mode->peak_nits, DVBRIDGE_PANEL_UNSET,
               gamut == DVVK_GAMUT_BT709 ? DVBRIDGE_GAMUT_BT709 : gamut == DVVK_GAMUT_P3D65 ? DVBRIDGE_GAMUT_P3_D65
                                                                                         : DVBRIDGE_GAMUT_BT2020},
        .expert_black_nits = mode->min_nits,
    };
    if (lldv && display && display->edid_version) {
        for (int i = 0; i < 3; i++)
            if (display->reserved[i])
                return 0;
        policy->lldv_edid_version = display->edid_version;
        for (int i = 0; i < 6; i++)
            policy->lldv_primaries[i] = display->xy[i / 2][i % 2];
    }
    return dvbridge_policy_validate(policy) == DVBRIDGE_POLICY_VALID;
}

int dvvk_map_target_valid(const dvvk_output_mode *mode, const dvvk_display_primaries *display)
{
    struct dvbridge_policy policy;
    return mode ? expert_policy(mode, display, &policy) : -1;
}

/* CB1's dvbridge_creative_cm4_shader (dvbridge_render.c): its variables, as
 * it computes them; 0: the shader isn't added (identity), -1: it fails. */
static int expert_cm4_plan(dvvk_map_gpu *g, const struct dvbridge_cm4_coefficients *c)
{
    if (!isfinite(c->peak_nits) || c->peak_nits <= 0 || c->peak_nits > 10000 || !(c->chroma_base > 0) ||
        !(c->saturation_gain > 0) || !(c->mid_exponent > 0))
        return -1;
    float sop[4] = {c->sop[0], c->sop[1], c->sop[2], c->peak_nits};
    float shape[4] = {c->mid_exponent, c->clip_strength, log2(c->chroma_base), log2(c->saturation_gain)};
    int secondary_active = 0;
    float luma[3], forward[9], inverse[9], residual[9], centres[6], gains[6], turns[6];
    float flags[4] = {c->sop[0] != 1 || c->sop[1] != 0 || c->sop[2] != 1, c->mid_exponent != 1, c->clip_strength != 0,
                      c->chroma_base != 1 || c->saturation_gain != 1};
    for (int i = 0; i < 3; i++) {
        luma[i] = c->luma[i];
        for (int j = 0; j < 3; j++) {
            forward[j * 3 + i] = c->rgb_to_lms[i * 3 + j];
            inverse[j * 3 + i] = c->lms_to_rgb[i * 3 + j];
            double v = 0;
            for (int k = 0; k < 3; k++)
                v += c->lms_to_rgb[i * 3 + k] * c->rgb_to_lms[k * 3 + j];
            residual[j * 3 + i] = v - (i == j);
        }
    }
    for (int i = 0; i < 6; i++) {
        if (!(c->secondary_gain[i] > 0))
            return -1;
        centres[i] = c->hue_centres[i];
        gains[i] = log(c->secondary_gain[i]);
        turns[i] = c->secondary_rotation[i];
        secondary_active |= c->secondary_gain[i] != 1 || turns[i] != 0;
        flags[3] = flags[3] || secondary_active;
    }
    const float *fields[] = {sop, shape, luma, forward, inverse, residual, centres, gains, turns};
    const unsigned counts[] = {4, 4, 3, 9, 9, 9, 6, 6, 6};
    for (unsigned i = 0; i < 9; i++)
        for (unsigned j = 0; j < counts[i]; j++)
            if (!isfinite(fields[i][j]))
                return -1;
    if (!flags[0] && !flags[1] && !flags[2] && !flags[3])
        return 0;
    /* Expert's plan is CB1's HDR10 Expert creative policy: the secondary
     * (six-vector) trims are neutral (dvbridge_creative_cm4_coefficients) */
    if (secondary_active)
        return -1;
    memcpy(g->ex_cm4_sop, sop, sizeof(sop));
    memcpy(g->ex_cm4_shape, shape, sizeof(shape));
    memcpy(g->ex_cm4_flags, flags, sizeof(flags));
    memcpy(g->ex_cm4_luma, luma, sizeof(luma));
    /* the GLSL's mat3 columns (forward[j*3+i] is column j) */
    for (int j = 0; j < 3; j++)
        for (int i = 0; i < 3; i++) {
            g->ex_cm4_rgb_lms[4 * j + i] = forward[j * 3 + i];
            g->ex_cm4_lms_rgb[4 * j + i] = inverse[j * 3 + i];
            g->ex_cm4_residual[4 * j + i] = residual[j * 3 + i];
        }
    for (int i = 0; i < 6; i++) {
        g->ex_cm4_centres[i] = centres[i];
        g->ex_cm4_gains[i] = gains[i];
        g->ex_cm4_turns[i] = turns[i];
    }
    return 1;
}

/* CroqueMr's CB1 Expert recipe for a stated display (dv_engine_vk.h
 * DVVK_HDR10_TARGET, DVVK_OUTPUT_LLDV): his plan (cb1_hdr10_expert.c,
 * vendored unchanged: the curve, L1/L6, the L2 shape, L8's CM4 controls),
 * then the decisions his renderer's shaders make with it, in order:
 * player_led_map (LLDV) or reference_output (HDR10), each with libplacebo's
 * pl_shader_color_map_ex for an explicit cb1_tone_map (patch 9918), the
 * EDID basis, CB1's CM4 shader, cb1_hdr10_expert_trim; then the output's
 * tail: dvbridge_pack_player_led_422's matrix and scale (LLDV), or the
 * BT.2020 PQ adapter and the Expert ceiling (HDR10). */
static int expert_plan(const dvvk_output_mode *mode, const dvvk_display_primaries *display, const AVDOVIMetadata *m,
                       size_t size, dvvk_map *out)
{
    struct dvbridge_policy policy;
    if (expert_policy(mode, display, &policy) != 1)
        return -1;
    const int lldv = mode->mode == DVVK_OUTPUT_LLDV;
    if (!mappable(m))
        return -2;
    struct cb1_hdr10_expert_plan plan;
    struct dvbridge_cm4_coefficients cm4 = {0};
    /* the engine pairs the EL itself (dvvk_plan): the plan's FEL gate passes */
    if (!(lldv ? cb1_player_led_prepare(&plan, &cm4, &policy, m, size, true)
               : cb1_hdr10_expert_prepare(&plan, &policy, m, size, true)))
        return -2;
    const struct pl_tone_map_params *tone = &plan.tone;
    /* pl_shader_color_map_ex's checks of an explicit curve (patch 9918) */
    int shaped = 0;
    for (int i = 0; i < 3; i++) {
        if (!isfinite(plan.tone_shape[i]) || fabsf(plan.tone_shape[i]) > 1)
            return -2;
        shaped |= plan.tone_shape[i] != 0;
    }
    if ((tone->function != &pl_tone_map_st2094_10 && tone->function != &pl_tone_map_clip) ||
        !isfinite(tone->input_min) || !isfinite(tone->input_max) || !isfinite(tone->input_avg) ||
        !isfinite(tone->output_min) || !isfinite(tone->output_max) || tone->input_min < 0 ||
        tone->input_min > tone->output_min || tone->input_max <= tone->input_min || tone->input_max > 1 ||
        tone->input_avg < 0 || tone->input_avg > tone->input_max || tone->output_min < 0 ||
        tone->output_min >= tone->output_max || tone->output_max > tone->input_max || tone->lut_size < 2 ||
        tone->lut_size > DVVK_MAP_EXPERT_LUT)   /* (and param 0: prepare's literal leaves it so) */
        return -2;

    /* pl_shader_color_map_ex: the explicit curve replaces the inferred one */
    struct pl_color_space src = plan.source.color, dst = plan.target;
    pl_color_space_infer_map(&src, &dst);
    struct pl_gamut_map_params gamut = {
        .function = &pl_gamut_map_perceptual,
        .input_gamut = src.hdr.prim,
        .output_gamut = dst.hdr.prim,
    };
    pl_color_space_nominal_luma_ex(pl_nominal_luma_params(.color = &dst, .metadata = PL_HDR_METADATA_HDR10,
                                                          .scaling = PL_HDR_PQ, .out_min = &gamut.min_luma,
                                                          .out_max = &gamut.max_luma));
    gamut.min_luma = pl_signal_black(gamut.min_luma, PL_HDR_PQ);
    /* gamut_expansion off (both of CB1's mappers), and perceptual is bidirectional */
    if (pl_primaries_compatible(&gamut.input_gamut, &gamut.output_gamut))
        gamut.output_gamut = pl_primaries_clip(&gamut.output_gamut, &gamut.input_gamut);
    const int need_tone = !pl_tone_map_params_noop(tone) || tone->input_min > 0 || shaped;
    const int need_gamut = !pl_gamut_map_params_noop(&gamut);

    memset(out, 0, sizeof(*out));
    dvvk_map_gpu *g = &out->gpu;
    const AVDOVIColorMetadata *colour = av_dovi_get_color(m);
    /* The decode. LLDV: CB1's player-led texture holds the Master
     * Reference codes as code / 4095 times 1 - 2^-12 (code / 4096), the RPU
     * matrix on them less its offsets as given (player_led_map's
     * normalize). HDR10: the HDR10 output's (dvvk_map_plan's) decode. */
    const double offset_scale = lldv ? 1.0 : 65536.0 / 65535.0, code_scale = lldv ? 4095.0 / 4096.0 : 1.0;
    for (int i = 0; i < 3; i++) {
        double c = 0;
        for (int j = 0; j < 3; j++) {
            double v = (float)q2d(colour->ycc_to_rgb_matrix[3 * i + j]);
            g->ycc[4 * i + j] = (float)(v * code_scale);
            c -= v * (float)q2d(colour->ycc_to_rgb_offset[j]) * offset_scale;
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
    g->flags = DVVK_MAP_EXPERT | (lldv ? DVVK_MAP_LLDV : 0u);
    g->lut_n = 65;
    if (need_tone) {
        g->flags |= DVVK_MAP_TONE;
        g->ex_flags |= DVVK_EX_TONE;
        g->tone_in[0] = tone->input_min;
        g->tone_in[1] = tone->input_max;
        g->tone_in[2] = 1.0f / (tone->input_max - tone->input_min);
        g->tone_out[0] = tone->output_min;
        g->tone_out[1] = tone->output_max;
        g->ex_lut_n = (uint32_t)tone->lut_size;
        pl_cb1_expert_tone_generate(g->ex_tone_lut, tone, plan.tone_shape);
    }
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
    if (!need_tone && !need_gamut) {
        /* the fast path: a conversion between primaries, if any */
        pl_matrix3x3 fast = pl_matrix3x3_identity;
        if (src.primaries != dst.primaries) {
            fast = lms2rgb;
            pl_matrix3x3_mul(&fast, &rgb2lms);
        }
        g->ex_flags |= DVVK_EX_FAST;
        rows(g->ex_fast, &fast);
    }
    /* signal black: exact zero with a zero black (player_led_map's
     * preserve_black, reference_output's keep_black); a positive CM4 offset
     * lifts it after the map (lift_black) */
    if (!tone->output_min)
        g->ex_flags |= DVVK_EX_KEEP_BLACK;
    if (lldv && plan.creative.backend == DVBRIDGE_CREATIVE_CM4 && cm4.sop[1] > 0)
        g->ex_flags |= DVVK_EX_LIFT_BLACK;
    const int edid = lldv && plan.creative.policy.lldv_edid_version;
    const struct pl_raw_primaries *basis = pl_raw_primaries_get(plan.target.primaries);
    const struct pl_raw_primaries *target = &plan.target.hdr.prim;
    if (edid) {
        g->ex_flags |= DVVK_EX_EDID;
        const pl_matrix3x3 b = pl_get_color_mapping_matrix(basis, target, PL_INTENT_RELATIVE_COLORIMETRIC);
        rows(g->ex_basis, &b);
    }
    if (lldv && plan.creative.backend == DVBRIDGE_CREATIVE_CM4) {
        const int r = expert_cm4_plan(g, &cm4);
        if (r < 0)
            return -2;
        if (r) {
            g->ex_flags |= DVVK_EX_CM4;
            if (edid) {
                const struct pl_raw_primaries *trim = &plan.creative.cm4_output.primaries;
                const pl_matrix3x3 to = pl_get_color_mapping_matrix(target, trim, PL_INTENT_RELATIVE_COLORIMETRIC);
                const pl_matrix3x3 from = pl_get_color_mapping_matrix(trim, target, PL_INTENT_RELATIVE_COLORIMETRIC);
                g->ex_flags |= DVVK_EX_CM4_TRIM;
                rows(g->ex_to_trim, &to);
                rows(g->ex_from_trim, &from);
            }
        }
    }
    /* cb1_hdr10_expert_trim: the chroma and saturation (codes 3, 4), and the
     * output volume */
    g->ex_chroma[0] = (float)(plan.creative.codes[3] / 4096 - .5);
    g->ex_chroma[1] = (float)(plan.creative.codes[4] / 4096 - .5);
    if (plan.creative.codes[4] != 2048)
        g->ex_flags |= DVVK_EX_CHROMA;
    {
        const struct pl_raw_primaries trim_display =
            plan.creative.policy.lldv_edid_version ? cb1_display_primaries(&plan.creative.policy)
                                                   : *pl_raw_primaries_get(plan.target.primaries);
        const pl_matrix3x3 xyz = pl_get_rgb2xyz_matrix(&trim_display);
        for (int i = 0; i < 3; i++)
            g->ex_luma[i] = xyz.m[1][i];
        float cap = plan.creative.policy.tv.peak_nits / 203;
        if ((double)cap * 203 > plan.creative.policy.tv.peak_nits)
            cap = nextafterf(cap, 0);
        g->ex_chroma[2] = cap;
    }
    if (lldv) {
        /* player_led_map's player_led_relative, then the pack's lldv_matrix
         * and lldv_scale (dvbridge_pack_player_led_422) */
        g->ex_scale[0] = PL_COLOR_SDR_WHITE / policy.tv.peak_nits;
        g->ex_scale[1] = policy.tv.peak_nits / PL_COLOR_SDR_WHITE;
        const struct pl_raw_primaries prim = cb1_display_primaries(&policy);
        const pl_matrix3x3 to2020 = !policy.lldv_edid_version && policy.tv.gamut == DVBRIDGE_GAMUT_BT2020
                                        ? pl_matrix3x3_identity
                                        : pl_get_color_mapping_matrix(&prim, pl_raw_primaries_get(PL_COLOR_PRIM_BT_2020),
                                                                      PL_INTENT_RELATIVE_COLORIMETRIC);
        rows(g->ex_out, &to2020);
        pl_matrix3x3 back = to2020;
        pl_matrix3x3_invert(&back);
        rows(g->ex_out_inv, &back);
        /* player_led_gui: BT.709 to the display, 203 cd/m2 white */
        const pl_matrix3x3 gui = pl_get_color_mapping_matrix(pl_raw_primaries_get(PL_COLOR_PRIM_BT_709), &prim,
                                                             PL_INTENT_RELATIVE_COLORIMETRIC);
        rows(g->ex_gui, &gui);
        g->ex_bits = mode->flags & DVVK_LLDV_10BIT ? 10 : 12;
    } else {
        /* reference_output's composed matrix (xyz2rgb(BT.2020) * rgb2xyz of
         * the target's primaries), then the Expert ceiling (no output grid:
         * the carrier's Y'CbCr, not R'G'B', is quantised) */
        pl_matrix3x3 to2020 = pl_get_xyz2rgb_matrix(pl_raw_primaries_get(PL_COLOR_PRIM_BT_2020));
        const pl_matrix3x3 xyz = pl_get_rgb2xyz_matrix(pl_raw_primaries_get(plan.target.primaries));
        pl_matrix3x3_mul(&to2020, &xyz);
        rows(g->ex_out, &to2020);
        g->ex_scale[2] = cb1_hdr10_expert_ceiling(&policy);
    }
    out->key = fnv1a(g, sizeof(*g));

    dvvk_hdr_signal *s = &out->signal;
    s->mode = mode->mode;
    s->eotf = 2;
    /* the virtual target's (LLDV: the display's) primaries and luminance */
    const struct pl_raw_primaries prim = cb1_display_primaries(&policy);
    const struct pl_cie_xy *xy[4] = {&prim.red, &prim.green, &prim.blue, &prim.white};
    for (int i = 0; i < 3; i++) {
        s->primaries[i][0] = (uint16_t)lround(fmin(fmax(xy[i]->x, 0.0), 1.0) * 50000.0);
        s->primaries[i][1] = (uint16_t)lround(fmin(fmax(xy[i]->y, 0.0), 1.0) * 50000.0);
    }
    s->white[0] = (uint16_t)lround(xy[3]->x * 50000.0);
    s->white[1] = (uint16_t)lround(xy[3]->y * 50000.0);
    s->max_luminance = (uint16_t)plan.signal.max_luminance;
    s->min_luminance = (uint16_t)plan.signal.min_luminance;
    if (lldv)
        s->reserved[DVVK_SIGNAL_BITS_WORD] = g->ex_bits;
    return 0;
}

int dvvk_map_plan(const dvvk_output_mode *mode, const void *metadata, size_t metadata_size, dvvk_map *out)
{
    return dvvk_map_plan_display(mode, NULL, metadata, metadata_size, out);
}

int dvvk_map_plan_display(const dvvk_output_mode *mode, const dvvk_display_primaries *display, const void *metadata,
                          size_t metadata_size, dvvk_map *out)
{
    if (!mode || !metadata || !out || metadata_size < sizeof(AVDOVIMetadata) ||
        (uintptr_t)metadata % _Alignof(AVDOVIMetadata))
        return -1;
    if (mode->mode == DVVK_OUTPUT_LLDV || (mode->mode == DVVK_OUTPUT_HDR10 && mode->flags))
        return expert_plan(mode, display, metadata, metadata_size, out);
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
    float white = 0, black = 0, gamma = 0;
    if (sdr ? !sdr_display(mode, &white, &black, &gamma) : mode->peak_nits > 0)
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
    /* A plain HLG video (dvvk_hdr10_to_dovi's metadata): no mastering display
     * and no L1; libplacebo's HLG is BT.2100's 1000 cd/m2 display. */
    const int hlg = sdr && (mode->flags & DVVK_SDR_HLG);
    if (hlg)
        src = (struct pl_color_space) {.primaries = PL_COLOR_PRIM_BT_2020, .transfer = PL_COLOR_TRC_HLG};
    enum pl_hdr_metadata_type meta;
    if (!hlg && l1 && l1->l1.min_pq <= l1->l1.avg_pq && l1->l1.avg_pq <= l1->l1.max_pq && l1->l1.max_pq <= 4095 &&
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
        /* CB1's sdr_container: a pure power is GAMMA22 or GAMMA24 (another
         * exponent only changes the delinearisation below), and a true zero
         * black is PL_COLOR_HDR_BLACK (libplacebo's 0 is "unknown") */
        dst = (struct pl_color_space) {
            .primaries = mode->flags & DVVK_SDR_BT2020 ? PL_COLOR_PRIM_BT_2020 : PL_COLOR_PRIM_BT_709,
            .transfer = !gamma ? PL_COLOR_TRC_BT_1886 : gamma == 2.2f ? PL_COLOR_TRC_GAMMA22 : PL_COLOR_TRC_GAMMA24,
            .hdr = {.min_luma = fmaxf(black, PL_COLOR_HDR_BLACK), .max_luma = white},
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
    if (hlg) {
        /* pl_shader_linearize's HLG, on light where 1 is 10000 cd/m2 */
        float lo, hi;
        pl_color_space_nominal_luma_ex(pl_nominal_luma_params(.color = &src, .metadata = PL_HDR_METADATA_HDR10,
                                                              .scaling = PL_HDR_NORM, .out_min = &lo, .out_max = &hi));
        const float y = 1.2f * powf(1.111f, log2f(hi / (PL_COLOR_HLG_PEAK / PL_COLOR_SDR_WHITE)));
        const pl_matrix3x3 xyz = pl_get_rgb2xyz_matrix(pl_raw_primaries_get(src.primaries));
        g->flags |= DVVK_MAP_HLG;
        g->src_trc[0] = sqrtf(3 * powf(lo / hi, 1 / y));
        g->src_trc[1] = y - 1;
        g->src_trc[2] = hi * (PL_COLOR_SDR_WHITE / 10000.0f);
        for (int i = 0; i < 3; i++)
            g->src_luma[i] = xyz.m[1][i];
    }
    if (sdr) {
        g->flags |= DVVK_MAP_SDR;
        if (!(mode->flags & DVVK_SDR_NO_DITHER))
            g->flags |= DVVK_MAP_DITHER_ON;
        if (mode->flags & DVVK_SDR_BT2020)
            g->flags |= DVVK_MAP_BT2020;
        /* The 3D LUT's box (dvvk_map.h). Luma ends where a grey reaches the
         * curve's input peak and a thirty-second (PQ) more: the scene has
         * little above it, and a narrower box is a finer LUT. Without the
         * curve, and for HLG (its signal ends at 1), the whole range. HLG's
         * chroma is the wider too: its curve is nearer a square root than
         * PQ's logarithm, and a colour's channels lie further apart. */
        g->lut_n = DVVK_MAP_SDR_NC;
        g->lut_ny = DVVK_MAP_SDR_NY;
        g->lut_box[0] = 4095.0f;
        g->lut_box[1] = g->flags & DVVK_MAP_HLG ? DVVK_MAP_SDR_CHROMA_HLG : DVVK_MAP_SDR_CHROMA;
        if ((g->flags & DVVK_MAP_TONE) && !(g->flags & DVVK_MAP_HLG)) {
            float top = 0.0f;
            for (int i = 0; i < 3; i++) {
                const float grey = (g->ycc[4 * i + 1] + g->ycc[4 * i + 2]) * (2048.0f / 4095.0f) + g->ycc_offset[i];
                if (g->ycc[4 * i] > 0.0f)
                    top = fmaxf(top, (g->tone_in[1] + 1.0f / 32 - grey) / g->ycc[4 * i] * 4095.0f);
            }
            if (top > 0.0f)
                g->lut_box[0] = fminf(ceilf(top), 4095.0f);
        }
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
            /* a pure power (CB1's custom gamma: GAMMA24's curve, then the
             * signal to the power 2.4 / gamma, which is this) */
            g->out_trc[0] = 1.0f / (hi - lo);
            g->out_trc[1] = -lo / (hi - lo);
            g->out_trc[2] = 1 / gamma;
        }
        /* CB1's targets above a true zero black: a pure power's slope at
         * the black has no bound, and there the sampler's 8-bit weights put
         * samples two codes from the exact map (gamma 1.8, 5 of 20 cd/m2;
         * with a zero black they stay within one, 1 to 2 ms cheaper at
         * 3840x2160). The earlier targets keep the sampler, and their bytes. */
        if ((mode->flags & (DVVK_SDR_POWER | DVVK_SDR_BLACK | DVVK_SDR_BT2020)) && lo > 0)
            g->flags |= DVVK_MAP_GAMUT_EXACT;
        g->out_code[0] = mode->flags & DVVK_SDR_LIMITED ? 219.0f : 255.0f;
        g->out_code[1] = mode->flags & DVVK_SDR_LIMITED ? 16.0f : 0.0f;
    }
    /* black_in/out still 0: not in the key; nor the Expert fields (all 0
     * here), so that these keys are what they were before them */
    out->key = fnv1a(g, offsetof(dvvk_map_gpu, ex_flags));

    dvvk_hdr_signal *s = &out->signal;
    s->mode = mode->mode;
    if (sdr) {
        /* an ordinary picture: no HDR signalling; what it was made for */
        static const uint16_t bt709[4][2] = {{32000, 16500}, {15000, 30000}, {7500, 3000}, {15635, 16450}};
        static const uint16_t bt2020[4][2] = {{35400, 14600}, {8500, 39850}, {6550, 2300}, {15635, 16450}};
        const uint16_t(*prim)[2] = mode->flags & DVVK_SDR_BT2020 ? bt2020 : bt709;
        memcpy(s->primaries, prim, sizeof(s->primaries));
        memcpy(s->white, prim[3], sizeof(s->white));
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

/* Expert's tone LUT as pl_shader_color_map_ex samples it (SH_LUT_LINEAR:
 * texel centres at the domain's ends) */
static double expert_tone(const dvvk_map_gpu *p, double x)
{
    const int n = (int)p->ex_lut_n;
    double t = fmin(fmax((x - p->tone_in[0]) * p->tone_in[2], 0.0), 1.0) * (n - 1);
    int i = (int)floor(t);
    if (i >= n - 1)
        return p->ex_tone_lut[n - 1];
    double f = t - i;
    return p->ex_tone_lut[i] * (1.0 - f) + p->ex_tone_lut[i + 1] * f;
}

/* CB1's CM4.0 shader (dvbridge_creative_cm4_shader) on c (1 = 203 cd/m2):
 * its CPU twin, CB1's dvbridge_creative_cm4_apply (vendored), on the
 * shader's coefficients; the shader evaluates the same arithmetic in its
 * difference form for a float's precision. */
static void expert_cm4(const dvvk_map_gpu *p, double c[3])
{
    struct dvbridge_cm4_coefficients k = {
        .peak_nits = p->ex_cm4_sop[3],
        .sop = {p->ex_cm4_sop[0], p->ex_cm4_sop[1], p->ex_cm4_sop[2]},
        .chroma_base = exp2(p->ex_cm4_shape[2]),
        .saturation_gain = exp2(p->ex_cm4_shape[3]),
        .mid_exponent = p->ex_cm4_shape[0],
        .clip_strength = p->ex_cm4_shape[1],
        .luma = {p->ex_cm4_luma[0], p->ex_cm4_luma[1], p->ex_cm4_luma[2]},
    };
    /* the flags the shader tests, as the parameters cm4_apply tests */
    if (p->ex_cm4_flags[0] == 0)
        k.sop[0] = 1, k.sop[1] = 0, k.sop[2] = 1;
    if (p->ex_cm4_flags[1] == 0)
        k.mid_exponent = 1;
    if (p->ex_cm4_flags[2] == 0)
        k.clip_strength = 0;
    if (p->ex_cm4_flags[3] == 0)
        k.chroma_base = k.saturation_gain = 1;
    for (int i = 0; i < 6; i++)
        k.secondary_gain[i] = exp(p->ex_cm4_gains[i]);
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++) {
            /* the coefficients' rows from the shader's columns */
            k.rgb_to_lms[i * 3 + j] = p->ex_cm4_rgb_lms[4 * j + i];
            k.lms_to_rgb[i * 3 + j] = p->ex_cm4_lms_rgb[4 * j + i];
        }
    double in[3] = {c[0] * 203.0, c[1] * 203.0, c[2] * 203.0}, o[3];
    if (dvbridge_creative_cm4_apply(&k, in, o))
        for (int i = 0; i < 3; i++)
            c[i] = o[i] / 203.0;
}

/* Expert, from the nonlinear source to the display's linear light (1 = 203
 * cd/m2, the display's primaries), before the output's tail. *black: the
 * sample was signal black (all channels' light 0). */
static void expert_display(const dvvk_map_gpu *p, const uint32_t *tables, const double nl[3], double c[3], int *black)
{
    const uint32_t f = p->ex_flags;
    double n[3], lin[3];
    /* pl_shader_decode_color_ex's cb1_dovi_linear: PQ, Dolby's LMS to
     * BT.2020, negative light 0, then libplacebo's 203-relative light */
    for (int i = 0; i < 3; i++)
        n[i] = pq_eotf(nl[i]);
    mul(p->src_lms2rgb, n, lin);
    for (int i = 0; i < 3; i++)
        lin[i] = fmax(lin[i], 0.0) * (10000.0 / 203.0);
    *black = lin[0] <= 0.0 && lin[1] <= 0.0 && lin[2] <= 0.0;
    if (*black && (f & DVVK_EX_KEEP_BLACK) && !(f & DVVK_EX_LIFT_BLACK)) {
        c[0] = c[1] = c[2] = 0.0;
        return;
    }
    /* pl_shader_color_map_ex with the explicit curve */
    if (f & DVVK_EX_FAST)
        mul(p->ex_fast, lin, c);
    else {
        double lms[3], ipt[3];
        mul(p->rgb2lms, lin, lms);
        for (int i = 0; i < 3; i++)
            lms[i] = pq_oetf(lms[i] * (203.0 / 10000.0));
        mul(p->lms2ipt, lms, ipt);
        if (f & DVVK_EX_TONE) {
            const double i0 = ipt[0];
            ipt[0] = expert_tone(p, i0);
            const double h0 = ((i0 - 6.0) * i0 + 9.0) * i0, h1 = ((ipt[0] - 6.0) * ipt[0] + 9.0) * ipt[0];
            const double k = ipt[0] > 0.0 && h0 > 0.0 ? fmin(i0 / ipt[0], h1 / h0) : 0.0;
            ipt[1] *= k;
            ipt[2] *= k;
        }
        if (p->flags & DVVK_MAP_GAMUT)
            gamut_map(p, tables, ipt);
        mul(p->ipt2lms, ipt, lms);
        for (int i = 0; i < 3; i++)
            lms[i] = pq_eotf(lms[i]) * (10000.0 / 203.0);
        mul(p->lms2rgb, lms, c);
    }
    /* player_led_map: signal black restored before the creative grading */
    if (*black && (f & DVVK_EX_LIFT_BLACK))
        c[0] = c[1] = c[2] = 0.0;
    if (f & DVVK_EX_EDID) {
        double b[3];
        mul(p->ex_basis, c, b);
        memcpy(c, b, sizeof(b));
    }
    if (f & DVVK_EX_CM4) {
        double t[3];
        if (f & DVVK_EX_CM4_TRIM) {
            mul(p->ex_to_trim, c, t);
            memcpy(c, t, sizeof(t));
        }
        expert_cm4(p, c);
        if (f & DVVK_EX_CM4_TRIM) {
            mul(p->ex_from_trim, c, t);
            memcpy(c, t, sizeof(t));
        }
    }
    /* cb1_hdr10_expert_trim */
    const double cap = p->ex_chroma[2];
    for (int i = 0; i < 3; i++)
        c[i] = fmin(fmax(c[i], 0.0), cap);
    if (f & DVVK_EX_CHROMA) {
        const double y = p->ex_luma[0] * c[0] + p->ex_luma[1] * c[1] + p->ex_luma[2] * c[2];
        if (y > 0.0)
            for (int i = 0; i < 3; i++)
                if (c[i] > 0.0)
                    c[i] *= pow((1.0 + p->ex_chroma[0]) * c[i] / y, p->ex_chroma[1]);
        for (int i = 0; i < 3; i++)
            c[i] = fmin(fmax(c[i], 0.0), cap);
    }
}

void dvvk_map_expert_display(const dvvk_map_gpu *p, const uint32_t *tables, const double nl[3], double v[3])
{
    int black;
    expert_display(p, tables, nl, v, &black);
    if (p->flags & DVVK_MAP_LLDV)
        for (int i = 0; i < 3; i++)
            v[i] *= p->ex_scale[0];
}

void dvvk_map_lldv_encode(const dvvk_map_gpu *p, const double v[3], double pq[3])
{
    double t[3];
    mul(p->ex_out, v, t);
    for (int i = 0; i < 3; i++)
        pq[i] = pq_oetf(fmin(fmax(t[i], 0.0), 1.0) * p->ex_scale[1] * (203.0 / 10000.0));
}

/* the engine's degamma LUT (cb1_overlay.c dvvk_cb1_luts: 256 half floats of
 * the sRGB EOTF) sampled linearly at the code's normalised coordinate, as
 * player_led_gui's textureLod(ll_gui_degamma, vec2(ui.r, .5)) */
static double half_float(float x)
{
    if (!(x > 0.0f))
        return 0.0;
    int e;
    frexp(x, &e);   /* x in [2^(e-1), 2^e) */
    /* 11 significant bits (subnormals below 2^-14: a fixed 2^-24 step), to nearest even */
    const double q = e - 1 >= -14 ? ldexp(1.0, e - 11) : ldexp(1.0, -24);
    double r = x / q, fl = floor(r), d = r - fl;
    if (d > 0.5 || (d == 0.5 && fmod(fl, 2.0) != 0.0))
        fl += 1.0;
    return fl * q;
}

double dvvk_map_lldv_degamma(double code)
{
    static double lut[256];
    static int ready;
    if (!ready) {
        for (int i = 0; i < 256; i++) {
            float v = (float)i / 255;
            lut[i] = half_float(v <= 0.04045f ? v / 12.92f : powf((v + 0.055f) / 1.055f, 2.4f));
        }
        ready = 1;
    }
    double t = code / 255.0 * 256.0 - 0.5;
    int i = (int)floor(t);
    double f = t - i;
    if (i < 0)
        return lut[0];
    if (i >= 255)
        return lut[255];
    return lut[i] * (1.0 - f) + lut[i + 1] * f;
}

void dvvk_map_lldv_gui(const dvvk_map_gpu *p, const uint8_t rgba[4], double v[3])
{
    if (!rgba[3])
        return;
    /* the texel as player_led_gui reads it (its colour as stored, alpha the mix) */
    double rgb[3], d[3];
    rgb[0] = dvvk_map_lldv_degamma(rgba[0]);
    rgb[1] = rgb[2] = rgb[0];
    if (rgba[0] != rgba[1] || rgba[0] != rgba[2]) {
        rgb[1] = dvvk_map_lldv_degamma(rgba[1]);
        rgb[2] = dvvk_map_lldv_degamma(rgba[2]);
    }
    mul(p->ex_gui, rgb, d);
    const double a = rgba[3] / 255.0;
    for (int i = 0; i < 3; i++) {
        const double g = fmin(fmax(d[i] * p->ex_scale[0], 0.0), 1.0);
        v[i] = fmin(fmax(v[i], 0.0), 1.0) * (1.0 - a) + g * a;
    }
}

/* Expert: the 3D LUT's function, the output's BT.2020 PQ R'G'B' (LLDV's
 * before the overlay); HDR10's tail is reference_output's */
static uint32_t expert_rgb(const dvvk_map_gpu *p, const uint32_t *tables, const double nl[3], double rgb[3])
{
    double c[3];
    int black;
    expert_display(p, tables, nl, c, &black);
    if (p->flags & DVVK_MAP_LLDV) {
        for (int i = 0; i < 3; i++)
            c[i] *= p->ex_scale[0];
        dvvk_map_lldv_encode(p, c, rgb);
        return (uint32_t)black;
    }
    double t[3];
    mul(p->ex_out, c, t);
    for (int i = 0; i < 3; i++) {
        rgb[i] = t[i] <= 0.0 ? 0.0 : pq_oetf(fmin(fmax(t[i] * (203.0 / 10000.0), 0.0), 1.0));
        if (black && (p->ex_flags & DVVK_EX_KEEP_BLACK))
            rgb[i] = 0.0;
        rgb[i] = fmin(rgb[i], p->ex_scale[2]);
    }
    return (uint32_t)black;
}

uint32_t dvvk_map_rgb(const dvvk_map_gpu *p, const uint32_t *tables, const double nl[3], double rgb[3])
{
    double n[3], lin[3];
    uint32_t regime = 0;
    if (p->flags & DVVK_MAP_EXPERT)
        return expert_rgb(p, tables, nl, rgb);
    if (p->flags & DVVK_MAP_HLG) {
        /* pl_shader_linearize: HLG's inverse OETF (the scene's light over 12),
         * then its OOTF */
        double y = 0;
        for (int i = 0; i < 3; i++) {
            double x = (1.0 - p->src_trc[0]) * nl[i] + p->src_trc[0];
            n[i] = (x > 0.5 ? exp((x - 0.55991073) / 0.17883277) + 0.28466892 : 4.0 * x * x) / 12.0;
            y += p->src_luma[i] * n[i];
        }
        y = p->src_trc[2] * pow(fmax(y, 0.0), p->src_trc[1]);
        for (int i = 0; i < 3; i++)
            n[i] *= y;
    } else
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
    /* An HLG signal goes on above its nominal white (codes up to 1019 of 10
     * bits), and so do the R'G'B' of its Y'CbCr: pl_shader_linearize takes
     * them as they are (it clamps at 0 only). */
    /* SDR output of a PQ source: its R'G'B' too, where the codes have them
     * above 1 (a reshaped Profile 8.4 picture's edge had 1.12, which
     * libplacebo shows as the blue it is and a clamp as a paler one), up to
     * 1.5: PQ's inverse has a pole near 2. HDR10 output keeps CB1's range. */
    /* LLDV: CB1's player-led decode clamps at 0 only (pl_shader_decode_color's
     * PQ EOTF of max(v, 0)) */
    const double top = p->flags & (DVVK_MAP_HLG | DVVK_MAP_LLDV) ? INFINITY : p->flags & DVVK_MAP_SDR ? 1.5 : 1.0;
    for (int i = 0; i < 3; i++)
        nl[i] = fmin(fmax(nl[i] + p->ycc_offset[i], 0.0), top);
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

void dvvk_map_layer_bt2020(const dvvk_map_gpu *p, double v[3])
{
    /* pl_get_color_mapping_matrix(BT.709, BT.2020, relative colorimetric);
     * its rows sum to 1, so the display's black and white scaling cancel */
    static const double m[3][3] = {{0.6274038959, 0.3292830384, 0.0433130657},
                                   {0.0690972894, 0.9195403951, 0.0113623156},
                                   {0.0163914389, 0.0880133079, 0.8955952532}};
    double lin[3];
    for (int i = 0; i < 3; i++)
        lin[i] = pow(v[i] + p->out_trc[3], 1.0 / p->out_trc[2]);
    for (int i = 0; i < 3; i++)
        v[i] = fmin(fmax(pow(m[i][0] * lin[0] + m[i][1] * lin[1] + m[i][2] * lin[2], p->out_trc[2]) - p->out_trc[3],
                         0.0),
                    1.0);
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
    if (p->flags & DVVK_MAP_LLDV) {
        /* LLDV: the unrounded codes (as float bits): the pack filters a
         * pair's chroma before it rounds */
        const float c[3] = {256.0 + 3504.0 * o[0], 2048.0 + 3584.0 * o[1], 2048.0 + 3584.0 * o[2]};
        memcpy(p->black_out, c, sizeof(c));
        return;
    }
    p->black_out[0] = code(o[0], 256.0, 3504.0);
    p->black_out[1] = code(o[1], 2048.0, 3584.0);
    p->black_out[2] = code(o[2], 2048.0, 3584.0);
}
