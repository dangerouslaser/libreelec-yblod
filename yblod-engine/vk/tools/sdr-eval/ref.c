/* Reference HDR -> SDR mapping from the engine's vendored libplacebo subset
 * (yblod-engine/vk/yblod/placebo, CB1's patched libplacebo e2972fdd), following
 * yblod/dv_map.c's use of it (pl_shader_color_map_ex's decisions): IPT, the
 * tone LUT on I, the hull desaturation, then the gamut map to the target
 * primaries. Research harness only (SDR-OUTPUT-PLAN.md); not engine code.
 *
 * usage: ref SRC_PEAK DST_PEAK TONE GAMUT [MAX_PQ_Y AVG_PQ_Y] [SRC_TRC]
 *   stdin: lines of BT.2020 PQ R'G'B' (0..1)
 *   stdout: per line, linear BT.709 RGB in cd/m2 (unclipped by the display),
 *           then flags: bit0 any channel below the target black, bit1 above the peak
 *   stderr: the tone map's resolved parameters
 */
#include <libplacebo/colorspace.h>
#include <libplacebo/gamut_mapping.h>
#include <libplacebo/tone_mapping.h>
#include "colorspace.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LUT 256

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

static void mul(const pl_matrix3x3 *m, const double in[3], double out[3])
{
    for (int i = 0; i < 3; i++)
        out[i] = m->m[i][0] * in[0] + m->m[i][1] * in[1] + m->m[i][2] * in[2];
}

int main(int argc, char **argv)
{
    if (argc < 5)
        return 2;
    float src_peak = atof(argv[1]), dst_peak = atof(argv[2]);
    const struct pl_tone_map_function *tf = pl_find_tone_map_function(argv[3]);
    const struct pl_gamut_map_function *gf = pl_find_gamut_map_function(argv[4]);
    if (!tf || !gf)
        return 3;
    struct pl_color_space src = {
        .primaries = PL_COLOR_PRIM_BT_2020,
        .transfer = PL_COLOR_TRC_PQ,
        .hdr = {.min_luma = 0.005f, .max_luma = src_peak},
    };
    enum pl_hdr_metadata_type meta = PL_HDR_METADATA_HDR10;
    if (argc >= 7 && atof(argv[5]) > 0) {
        src.hdr.max_pq_y = atof(argv[5]);
        src.hdr.avg_pq_y = atof(argv[6]);
        meta = PL_HDR_METADATA_CIE_Y;
    }
    struct pl_color_space dst = {
        .primaries = PL_COLOR_PRIM_BT_709,
        .transfer = PL_COLOR_TRC_BT_1886,
        .hdr = {.max_luma = dst_peak},
    };
    pl_color_space_infer_map(&src, &dst);

    struct pl_tone_map_params tone = {
        .function = tf,
        .constants = {PL_TONE_MAP_CONSTANTS},
        .input_scaling = PL_HDR_PQ,
        .output_scaling = PL_HDR_PQ,
        .lut_size = LUT,
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
    tone.input_max = fmaxf(tone.input_max, tone.output_max);
    int need_tone = !pl_tone_map_params_noop(&tone);
    float lut[LUT];
    if (need_tone)
        pl_tone_map_generate(lut, &tone);

    struct pl_gamut_map_params gamut = {
        .function = gf,
        .constants = {PL_GAMUT_MAP_CONSTANTS},
        .input_gamut = src.hdr.prim,
        .output_gamut = dst.hdr.prim,
        .lut_stride = 3,
    };
    pl_color_space_nominal_luma_ex(pl_nominal_luma_params(.color = &dst, .metadata = PL_HDR_METADATA_HDR10,
                                                          .scaling = PL_HDR_PQ, .out_min = &gamut.min_luma,
                                                          .out_max = &gamut.max_luma));
    if (gf->bidirectional && pl_primaries_compatible(&gamut.input_gamut, &gamut.output_gamut))
        gamut.output_gamut = pl_primaries_clip(&gamut.output_gamut, &gamut.input_gamut);
    int need_gamut = !pl_gamut_map_params_noop(&gamut);

    fprintf(stderr,
            "src %.3f..%.1f nits  dst %.4f..%.1f nits  tone %s in %.5f..%.5f (avg %.5f) out %.5f..%.5f PQ  need_tone %d  gamut %s need %d\n",
            src.hdr.min_luma, src.hdr.max_luma, dst.hdr.min_luma, dst.hdr.max_luma, tf->name, tone.input_min,
            tone.input_max, tone.input_avg, tone.output_min, tone.output_max, need_tone, gf->name, need_gamut);

    pl_matrix3x3 rgb2lms = pl_ipt_rgb2lms(pl_raw_primaries_get(src.primaries));
    pl_matrix3x3 lms2rgb = pl_ipt_lms2rgb(pl_raw_primaries_get(dst.primaries));
    double r, g, b;
    while (scanf("%lf %lf %lf", &r, &g, &b) == 3) {
        double lin[3] = {pq_eotf(r), pq_eotf(g), pq_eotf(b)}, lms[3], ipt[3];
        mul(&rgb2lms, lin, lms);
        for (int i = 0; i < 3; i++)
            lms[i] = pq_oetf(lms[i]);
        mul(&pl_ipt_lms2ipt, lms, ipt);
        if (need_tone) {
            double i0 = ipt[0];
            double t = (i0 - tone.input_min) / (tone.input_max - tone.input_min);
            t = fmin(fmax(t, 0.0), 1.0) * (LUT - 1);
            int k = (int)floor(t);
            double i1 = k >= LUT - 1 ? lut[LUT - 1] : lut[k] * (1.0 - (t - k)) + lut[k + 1] * (t - k);
            double h0 = ((i0 - 6.0) * i0 + 9.0) * i0, h1 = ((i1 - 6.0) * i1 + 9.0) * i1;
            double s = i1 > 0.0 && h0 > 0.0 ? fmin(i0 / i1, h1 / h0) : 0.0;
            ipt[0] = i1;
            ipt[1] *= s;
            ipt[2] *= s;
        }
        if (need_gamut) {
            float x[3] = {ipt[0], ipt[1], ipt[2]};
            pl_gamut_map_sample(x, &gamut);
            for (int i = 0; i < 3; i++)
                ipt[i] = x[i];
        }
        mul(&pl_ipt_ipt2lms, ipt, lms);
        for (int i = 0; i < 3; i++)
            lms[i] = pq_eotf(lms[i]);
        mul(&lms2rgb, lms, lin);
        int flags = 0;
        for (int i = 0; i < 3; i++) {
            double nits = lin[i] * 10000.0;
            if (nits < dst.hdr.min_luma - 1e-4)
                flags |= 1;
            if (nits > dst.hdr.max_luma + 1e-3)
                flags |= 2;
            lin[i] = nits;
        }
        printf("%.9g %.9g %.9g %d\n", lin[0], lin[1], lin[2], flags);
    }
    return 0;
}
