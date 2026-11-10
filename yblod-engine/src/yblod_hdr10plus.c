/* YBLOD 0.4.0: HDR10+ for the Vulkan engine, on CroqueMr's CB1 HDR10+ code
 * (cb1_dv_hdr10plus.c, cb1_hdr10plus*.c, cb1_hdr10plus_dovi.c, ported
 * unchanged at the commit their headers name).
 *
 * - yb_hdr10plus_packet: Dolby Vision -> HDR10+. The engine's statistics
 *   record (shaders/pack.comp STATS) to CB1's cb1_hdr10plus_statistics, then
 *   cb1_dv_hdr10plus_metadata_for_version and cb1_hdr10plus_vsif: the
 *   31-byte HDR10+ InfoFrame (include/dv_engine_vk.h dvvk_hdr10plus_metadata).
 * - yb_hdr10plus_to_dovi: HDR10+ -> Dolby Vision. cb1_hdr10plus_dovi_describe
 *   as an AVDOVIMetadata the engine plays as Profile 8.1 (an identity
 *   composer, L1 and L6; include/dv_engine_vk.h dvvk_hdr10plus_to_dovi).
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */
#include "yblod_hdr10plus.h"
#include "cb1_dv_hdr10plus.h"
#include "cb1_hdr10plus_dovi.h"
#include <libavutil/dovi_meta.h>
#include <math.h>
#include <stddef.h>
#include <string.h>

static double pq_eotf_nits(double q)
{
    double x = pow(fmin(fmax(q, 0.0), 1.0), 32.0 / 2523);
    return 10000 * pow(fmax(0, x - 3424.0 / 4096) / (2413.0 / 128 - 2392.0 / 128 * x), 16384.0 / 2610);
}

static unsigned pq_code(double nits)
{
    double x = pow(fmin(fmax(nits / 10000, 0.0), 1.0), 2610.0 / 16384);
    long c = lround(4095 * pow((3424.0 / 4096 + 2413.0 / 128 * x) / (1 + 2392.0 / 128 * x), 2523.0 / 32));
    return c < 0 ? 0 : c > 4095 ? 4095 : (unsigned)c;
}

int yb_hdr10plus_statistics(const uint32_t words[YB_HDR10PLUS_STATS_WORDS], struct cb1_hdr10plus_statistics *out)
{
    struct cb1_hdr10plus_statistics s = {0};
    for (unsigned i = 0; i < 256; i++) {
        s.histogram[i] = words[i];
        s.count += words[i];
    }
    if (!s.count || s.count != words[261])
        return -1;
    double peak = 0;
    for (unsigned c = 0; c < 3; c++) {
        float q;
        memcpy(&q, &words[256 + c], sizeof(q));
        if (!isfinite(q) || q < 0 || q > 1)
            return -1;
        s.maxscl[c] = pq_eotf_nits(q);
        peak = fmax(peak, s.maxscl[c]);
    }
    uint64_t sum = (uint64_t)words[260] << 32 | words[259];
    /* per-pixel light rounded to 1/64 nit on the GPU: never above the peak */
    s.average_maxrgb = fmin((double)sum / 64.0 / (double)s.count, peak);
    *out = s;
    return 0;
}

int yb_hdr10plus_packet(const void *metadata, size_t bytes, const uint32_t words[YB_HDR10PLUS_STATS_WORDS],
                        uint32_t flags, int overlay, dvvk_hdr10plus_metadata *out)
{
    if (!metadata || !words || !out)
        return -1;
    struct cb1_hdr10plus_statistics s;
    dvvk_hdr10plus_metadata r = {0};
    if (yb_hdr10plus_statistics(words, &s))
        return DVVK_HDR10PLUS_FALLBACK;   /* no film pixel measured */
    unsigned version = flags & DVVK_HDR10PLUS_V1 ? 1 : 0;
    AVDynamicHDRPlus m;
    struct cb1_dv_hdr10plus_report report;
    if (!cb1_dv_hdr10plus_metadata_for_version(&m, &report, metadata, bytes, &s, version))
        return DVVK_HDR10PLUS_FALLBACK;
    r.application_version = (uint8_t)version;
    r.coverage = report.coverage;
    r.reason = report.reason;
    memcpy(r.effective_l1, report.effective_l1, sizeof(r.effective_l1));
    r.l3_used = report.l3_used;
    r.maximum_curve_pq_error = report.maximum_curve_pq_error;
    r.maximum_color_pq_error = report.maximum_color_pq_error;
    r.average_maxrgb = s.average_maxrgb;
    memcpy(r.maxscl, s.maxscl, sizeof(r.maxscl));
    r.pixels = s.count;
    int status = cb1_hdr10plus_vsif(r.vsif, &m, overlay != 0, (flags & DVVK_HDR10PLUS_NO_DELAY) != 0) ==
                         CB1_HDR10PLUS_OK
                     ? 0
                     : DVVK_HDR10PLUS_FALLBACK;
    *out = r;
    return status;
}

/* av_dovi_metadata_alloc's layout (libavutil/dovi_meta.c), with the two
 * extension blocks this writes. */
typedef struct {
    AVDOVIMetadata metadata;
    AVDOVIRpuDataHeader header;
    AVDOVIDataMapping mapping;
    AVDOVIColorMetadata color;
    AVDOVIDmData ext[2];
} dovi_buffer;
_Static_assert(sizeof(dovi_buffer) <= DVVK_HDR10PLUS_DOVI_BYTES, "DVVK_HDR10PLUS_DOVI_BYTES");

int yb_hdr10plus_to_dovi(const void *hdr10plus, size_t size, const dvvk_hdr10_static *hdr10, const void *previous,
                         void *out, size_t capacity, size_t *out_size, dvvk_hdr10plus_dovi_info *info)
{
    if (!hdr10plus || size < sizeof(AVDynamicHDRPlus) || !out_size || (!out && capacity) ||
        (uintptr_t)out % _Alignof(dovi_buffer))
        return -1;
    const AVDynamicHDRPlus *source = hdr10plus;
    struct cb1_hdr10plus_dovi_result result;
    switch (cb1_hdr10plus_dovi_describe(&result, source, NULL)) {
    case CB1_HDR10PLUS_DOVI_OK:
        break;
    case CB1_HDR10PLUS_DOVI_UNSUPPORTED:
        return -2;
    default:
        return -1;
    }
    *out_size = sizeof(dovi_buffer);
    if (capacity < sizeof(dovi_buffer))
        return -3;
    /* the mastering display (unknown: 0.005 .. 1000 cd/m2) */
    double master_max = 1000, master_min = 0.005;
    uint16_t l6_max = 0, l6_min = 0, cll = 0, fall = 0;
    if (hdr10) {
        if (isfinite(hdr10->max_luminance) && hdr10->max_luminance >= 1 && hdr10->max_luminance <= 10000) {
            master_max = hdr10->max_luminance;
            l6_max = (uint16_t)lround(master_max);
        }
        if (isfinite(hdr10->min_luminance) && hdr10->min_luminance > 0 && hdr10->min_luminance < master_max &&
            hdr10->min_luminance <= 6.5535) {
            master_min = hdr10->min_luminance;
            l6_min = (uint16_t)lround(master_min * 10000);
        }
        cll = hdr10->max_cll;
        fall = hdr10->max_fall;
    }
    unsigned min_pq = pq_code(master_min), max_pq = pq_code(master_max);
    if (min_pq >= max_pq)
        min_pq = 0;

    dovi_buffer *b = out;
    memset(b, 0, sizeof(*b));
    b->metadata.header_offset = offsetof(dovi_buffer, header);
    b->metadata.mapping_offset = offsetof(dovi_buffer, mapping);
    b->metadata.color_offset = offsetof(dovi_buffer, color);
    b->metadata.ext_block_offset = offsetof(dovi_buffer, ext);
    b->metadata.ext_block_size = sizeof(AVDOVIDmData);
    b->metadata.num_ext_blocks = 2;

    /* Profile 8.1's RPU header: BL 10-bit limited range, VDR 12-bit, no EL */
    AVDOVIRpuDataHeader *h = &b->header;
    h->rpu_type = 2;
    h->rpu_format = 18;
    h->vdr_rpu_profile = 1;
    h->coef_log2_denom = 23;
    h->vdr_rpu_normalized_idc = 1;
    h->bl_bit_depth = 10;
    h->el_bit_depth = 10;
    h->vdr_bit_depth = 12;
    h->disable_residual_flag = 1;

    /* the identity composer: each component y = x over 0..1023 */
    AVDOVIDataMapping *map = &b->mapping;
    for (unsigned c = 0; c < 3; c++) {
        AVDOVIReshapingCurve *curve = &map->curves[c];
        curve->num_pivots = 2;
        curve->pivots[0] = 0;
        curve->pivots[1] = 1023;
        curve->mapping_idc[0] = AV_DOVI_MAPPING_POLYNOMIAL;
        curve->poly_order[0] = 1;
        curve->poly_coef[0][0] = 0;
        curve->poly_coef[0][1] = (int64_t)1 << 23;
    }
    map->nlq_method_idc = AV_DOVI_NLQ_NONE;
    map->num_x_partitions = map->num_y_partitions = 1;

    /* Profile 8.1's colour: BT.2020 limited-range Y'CbCr -> PQ R'G'B',
     * BT.2020 -> LMS (dovi_tool's defaults, CB1's dvbridge_output_*) */
    static const int ycc[9] = {9574, 0, 13802, 9574, -1540, -5348, 9574, 17610, 0};
    static const int lms[9] = {7222, 8771, 390, 2654, 12430, 1300, 0, 422, 15962};
    AVDOVIColorMetadata *col = &b->color;
    col->dm_metadata_id = 0;
    col->scene_refresh_flag = !previous || !cb1_hdr10plus_dovi_same_scene(previous, source);
    for (unsigned i = 0; i < 9; i++) {
        col->ycc_to_rgb_matrix[i] = (AVRational){ycc[i], 8192};
        col->rgb_to_lms_matrix[i] = (AVRational){lms[i], 16384};
    }
    col->ycc_to_rgb_offset[0] = (AVRational){16777216, 1 << 28};
    col->ycc_to_rgb_offset[1] = col->ycc_to_rgb_offset[2] = (AVRational){134217728, 1 << 28};
    col->signal_eotf = 65535;
    col->signal_bit_depth = 12;
    col->signal_color_space = 0;
    col->signal_chroma_format = 0;
    col->signal_full_range_flag = 1;
    col->source_min_pq = (uint16_t)min_pq;
    col->source_max_pq = (uint16_t)max_pq;
    col->source_diagonal = 42;

    const struct cb1_l1l3 *l = &result.metadata;
    b->ext[0].level = 1;
    b->ext[0].l1.min_pq = l->l1_min;
    b->ext[0].l1.max_pq = l->l1_max;
    b->ext[0].l1.avg_pq = l->l1_avg;
    b->ext[1].level = 6;
    b->ext[1].l6.max_luminance = l6_max;
    b->ext[1].l6.min_luminance = l6_min;
    b->ext[1].l6.max_cll = cll;
    b->ext[1].l6.max_fall = fall;

    if (info) {
        *info = (dvvk_hdr10plus_dovi_info){
            .l1_min = l->l1_min, .l1_max = l->l1_max, .l1_avg = l->l1_avg,
            .source_min_pq = (uint16_t)min_pq, .source_max_pq = (uint16_t)max_pq,
            .source_fields = (uint8_t)result.source_fields, .estimated_fields = (uint8_t)result.estimated_fields,
            .untranslated_curve = result.untranslated_curve, .untranslated_saturation = result.untranslated_saturation,
            .scene_refresh = col->scene_refresh_flag,
        };
    }
    return 0;
}
