/*
 * This file is part of libplacebo.
 *
 * libplacebo is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * libplacebo is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with libplacebo. If not, see <http://www.gnu.org/licenses/>.
 */

/* YBLOD: the Dolby Vision metadata mapping of libplacebo's
 * src/include/libplacebo/utils/libav_internal.h at e2972fdd with CroqueMr's
 * CB1 patches (CB1's cb1_hdr10_expert.c and dvbridge_placebo.c call it):
 * pl_map_dovi_metadata, pl_map_avdovi_metadata and the NLQ helpers they
 * call, unchanged except that they are plain functions here (the rest of
 * libplacebo's libav glue is not part of the engine). */
#include <libplacebo/utils/libav.h>
#include <libavutil/rational.h>
#include <libavutil/version.h>

static bool pl_avdovi_nlq_is_trivial(const AVDOVIRpuDataHeader *header,
                                     const AVDOVINLQParams *nlq)
{
    return nlq->nlq_offset == 0 &&
           nlq->vdr_in_max == (1ULL << header->coef_log2_denom) &&
           nlq->linear_deadzone_slope == 0 &&
           nlq->linear_deadzone_threshold == 0;
}

static bool pl_avdovi_mapping_nlq_is_trivial(const AVDOVIRpuDataHeader *header,
                                             const AVDOVIDataMapping *mapping)
{
    return mapping->nlq_method_idc == AV_DOVI_NLQ_LINEAR_DZ &&
           pl_avdovi_nlq_is_trivial(header, &mapping->nlq[0]) &&
           pl_avdovi_nlq_is_trivial(header, &mapping->nlq[1]) &&
           pl_avdovi_nlq_is_trivial(header, &mapping->nlq[2]);
}

void pl_map_dovi_metadata(struct pl_dovi_metadata *out,
                          const AVDOVIMetadata *data)
{
    const AVDOVIRpuDataHeader *header;
    const AVDOVIDataMapping *mapping;
    const AVDOVIColorMetadata *color;
    if (!data)
        return;

    header = av_dovi_get_header(data);
    mapping = av_dovi_get_mapping(data);
    color = av_dovi_get_color(data);
    out->cb1_native_bounds = false;

    for (int i = 0; i < 3; i++)
        out->nonlinear_offset[i] = av_q2d(color->ycc_to_rgb_offset[i]);
    for (int i = 0; i < 9; i++) {
        float *nonlinear = &out->nonlinear.m[0][0];
        float *linear = &out->linear.m[0][0];
        nonlinear[i] = av_q2d(color->ycc_to_rgb_matrix[i]);
        linear[i] = av_q2d(color->rgb_to_lms_matrix[i]);
    }
    for (int c = 0; c < 3; c++) {
        const AVDOVIReshapingCurve *csrc = &mapping->curves[c];
        struct pl_reshape_data *cdst = &out->comp[c];
        cdst->num_pivots = csrc->num_pivots;
        for (int i = 0; i < csrc->num_pivots; i++) {
            const float scale = 1.0f / ((1 << header->bl_bit_depth) - 1);
            cdst->pivots[i] = scale * csrc->pivots[i];
        }
        for (int i = 0; i < csrc->num_pivots - 1; i++) {
            const float scale = 1.0f / (1 << header->coef_log2_denom);
            cdst->method[i] = csrc->mapping_idc[i];
            switch (csrc->mapping_idc[i]) {
            case AV_DOVI_MAPPING_POLYNOMIAL:
                for (int k = 0; k < 3; k++) {
                    cdst->poly_coeffs[i][k] = (k <= csrc->poly_order[i])
                        ? scale * csrc->poly_coef[i][k]
                        : 0.0f;
                }
                break;
            case AV_DOVI_MAPPING_MMR:
                cdst->mmr_order[i] = csrc->mmr_order[i];
                cdst->mmr_constant[i] = scale * csrc->mmr_constant[i];
                for (int j = 0; j < csrc->mmr_order[i]; j++) {
                    for (int k = 0; k < 7; k++)
                        cdst->mmr_coeffs[i][j][k] = scale * csrc->mmr_coef[i][j][k];
                }
                break;
            }
        }
    }

    // NLQ parameters for FEL composition. Populated whenever the bitstream
    // carries non-trivial LINEAR_DZ NLQ (i.e. residuals exist). Consumers
    // that have not bound an enhancement layer must not look at these fields.
    out->nlq_active = !header->disable_residual_flag &&
                      mapping->nlq_method_idc == AV_DOVI_NLQ_LINEAR_DZ &&
                      !pl_avdovi_mapping_nlq_is_trivial(header, mapping);
    if (out->nlq_active) {
        const float el_scale = 1.0f / ((1 << header->el_bit_depth) - 1);
        // Use double for `coef_scale_d` math to preserve numerical stability.
        const double coef_scale_d  = 1.0 / (1ULL << header->coef_log2_denom);
        // DV LINEAR_DZ dequantization: for residual code rr,
        //   r_norm = sign(rr) * ((|rr| - 0.5) * S_norm + T_norm)
        // where S_norm, T_norm are coef_log2_denom-normalized. To let the
        // shader operate on el_centered in [-1, 1] / (2^eld - 1) space, we
        // pre-fold (2^eld - 1) into slope and -0.5*S into threshold.
        const double slope_scale_d = ((1ULL << header->el_bit_depth) - 1)
                                   * coef_scale_d;
        for (int c = 0; c < 3; c++) {
            const AVDOVINLQParams *src = &mapping->nlq[c];
            struct pl_dovi_nlq_data *dst = &out->nlq[c];
            const double S = src->linear_deadzone_slope;
            const double T = src->linear_deadzone_threshold;
            dst->offset = el_scale * src->nlq_offset;
            dst->deadzone_slope = slope_scale_d * S;
            dst->deadzone_threshold = coef_scale_d * (T - 0.5 * S);
            out->cb1_nlq_max[c] = coef_scale_d * src->vdr_in_max;
        }
    }
}

void pl_map_avdovi_metadata(struct pl_color_space *color,
                            struct pl_color_repr *repr,
                            struct pl_dovi_metadata *dovi,
                            const AVDOVIMetadata *metadata)
{
    const AVDOVIColorMetadata *dovi_color;
#if LIBAVUTIL_VERSION_INT >= AV_VERSION_INT(59, 12, 100)
    const AVDOVIDmData *dovi_ext;
#endif
    if (!color || !repr || !dovi)
        return;

    dovi_color = av_dovi_get_color(metadata);
    pl_map_dovi_metadata(dovi, metadata);

    repr->dovi = dovi;
    repr->sys = PL_COLOR_SYSTEM_DOLBYVISION;
    color->primaries = PL_COLOR_PRIM_BT_2020;
    color->transfer = PL_COLOR_TRC_PQ;
    color->hdr.min_luma =
        pl_hdr_rescale(PL_HDR_PQ, PL_HDR_NITS, dovi_color->source_min_pq / 4095.0f);
    color->hdr.max_luma =
        pl_hdr_rescale(PL_HDR_PQ, PL_HDR_NITS, dovi_color->source_max_pq / 4095.0f);

#if LIBAVUTIL_VERSION_INT >= AV_VERSION_INT(59, 12, 100)
    if ((dovi_ext = av_dovi_find_level(metadata, 1))) {
        color->hdr.max_pq_y = dovi_ext->l1.max_pq / 4095.0f;
        color->hdr.avg_pq_y = dovi_ext->l1.avg_pq / 4095.0f;
    }
#endif
}

/* YBLOD: libavutil's av_dovi_find_level (the first extension block of a
 * level), which the vendored CB1 code calls: the engine doesn't link
 * libavutil, and this symbol stays hidden like the rest of yblod/placebo. */
AVDOVIDmData *av_dovi_find_level(const AVDOVIMetadata *data, uint8_t level)
{
    for (int i = 0; i < data->num_ext_blocks; i++) {
        AVDOVIDmData *ext = av_dovi_get_ext(data, i);
        if (ext->level == level)
            return ext;
    }
    return NULL;
}
