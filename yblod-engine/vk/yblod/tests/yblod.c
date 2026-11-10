/* YBLOD's own HDR10+ glue (yblod-engine/src/yblod_hdr10plus.c): the engine's
 * statistics record to CB1's statistics, the packet from a record, and
 * HDR10+ -> Dolby Vision metadata (the plan is checked in src/hdr10plus.rs).
 * SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <libavutil/dovi_meta.h>
#include "yblod_hdr10plus.h"
#include "cb1_hdr10plus_dovi.h"

AVDOVIMetadata *av_dovi_metadata_alloc(size_t *size);
void av_free(void *p);

static uint32_t bits(float f)
{
    uint32_t b;
    memcpy(&b, &f, 4);
    return b;
}

/* PQ (0..1) of a luminance */
static float pq(double nits)
{
    double x = pow(nits / 10000, 2610.0 / 16384);
    return (float)pow((3424.0 / 4096 + 2413.0 / 128 * x) / (1 + 2392.0 / 128 * x), 2523.0 / 32);
}

static void record(uint32_t w[YB_HDR10PLUS_STATS_WORDS], const double maxscl[3], double average, uint32_t count,
                   const uint32_t *bins, const uint32_t *counts, unsigned n)
{
    memset(w, 0, YB_HDR10PLUS_STATS_WORDS * 4);
    for (unsigned i = 0; i < n; i++)
        w[bins[i]] = counts[i];
    for (unsigned c = 0; c < 3; c++)
        w[256 + c] = bits(pq(maxscl[c]));
    uint64_t sum = (uint64_t)llround(average * 64 * count);
    w[259] = (uint32_t)sum;
    w[260] = (uint32_t)(sum >> 32);
    w[261] = count;
}

static void statistics(void)
{
    uint32_t w[YB_HDR10PLUS_STATS_WORDS];
    const double maxscl[3] = {160, 800, 4000};
    const uint32_t bins[4] = {0, 10, 50, 250}, counts[4] = {512, 512, 512, 512};
    /* a sum over 2^32 (1/64 nits): the high word carries */
    record(w, maxscl, 1240, 2048, bins, counts, 4);
    assert(w[260] == 0);
    struct cb1_hdr10plus_statistics s;
    assert(!yb_hdr10plus_statistics(w, &s));
    assert(s.count == 2048 && s.histogram[10] == 512 && s.histogram[250] == 512);
    assert(fabs(s.average_maxrgb - 1240) < 1e-9);
    for (unsigned c = 0; c < 3; c++)
        assert(fabs(s.maxscl[c] - maxscl[c]) / maxscl[c] < 1e-5);
    const uint32_t big[1] = {255};
    const uint32_t many[1] = {4000000};
    const double peak[3] = {4000, 4000, 4000};
    record(w, peak, 4000, 4000000, big, many, 1);
    assert(w[260] != 0);
    assert(!yb_hdr10plus_statistics(w, &s) && fabs(s.average_maxrgb - 4000) < 1e-6);
    /* counted pixels must be the histogram's; none measured is no statistics */
    w[261]++;
    assert(yb_hdr10plus_statistics(w, &s));
    memset(w, 0, sizeof(w));
    assert(yb_hdr10plus_statistics(w, &s));
    /* an average above the peak (per-pixel rounding) is held at the peak */
    record(w, maxscl, 1240, 2048, bins, counts, 4);
    w[259] += 64 * 2048 * 3000u;
    assert(!yb_hdr10plus_statistics(w, &s) && s.average_maxrgb == s.maxscl[2]);
}

/* CB1's dv_hdr10plus test fixture's first case, through the engine's record:
 * the same packet as cb1_dv_hdr10plus_metadata + cb1_hdr10plus_vsif. */
static void packet(void)
{
    size_t bytes;
    AVDOVIMetadata *m = av_dovi_metadata_alloc(&bytes);
    AVDOVIRpuDataHeader *h = av_dovi_get_header(m);
    h->disable_residual_flag = 1;
    h->bl_bit_depth = h->el_bit_depth = 10;
    AVDOVIColorMetadata *c = av_dovi_get_color(m);
    c->signal_eotf = 65535;
    c->source_max_pq = 4095;
    m->num_ext_blocks = 1;
    *av_dovi_get_ext(m, 0) = (AVDOVIDmData){.level = 1, .l1 = {0, 3076, 1700}};
    uint32_t w[YB_HDR10PLUS_STATS_WORDS];
    const double maxscl[3] = {992, 992, 992};
    const uint32_t bins[3] = {0, 10, 62}, counts[3] = {9500, 400, 100};
    record(w, maxscl, 100, 10000, bins, counts, 3);
    dvvk_hdr10plus_metadata p, q;
    memset(&p, 0xa5, sizeof(p));
    assert(yb_hdr10plus_packet(m, bytes, w, DVVK_HDR10PLUS_V1 | DVVK_HDR10PLUS_NO_DELAY, 0, &p) == 0);
    assert(p.coverage == 1 && p.reason == 0 && p.application_version == 1 && p.pixels == 10000);
    assert(p.vsif[0] == 0x81 && p.vsif[1] == 1 && p.vsif[2] == 27 && p.vsif[4] == 0x8b && p.vsif[5] == 0x84 &&
           p.vsif[6] == 0x90 && (p.vsif[7] >> 6) == 1 && p.vsif[30] == 0x40);
    unsigned sum = 0;
    for (unsigned i = 0; i < 31; i++)
        sum += p.vsif[i];
    assert(!(sum & 255));
    /* tone_mapping_flag set: a knee/anchor count in byte 18 */
    assert(p.vsif[18] >> 4);
    /* the overlay flag and version 0 */
    assert(yb_hdr10plus_packet(m, bytes, w, 0, 1, &q) == 0);
    assert((q.vsif[7] >> 6) == 0 && q.vsif[30] == 0x80 && q.application_version == 0);
    /* no L1: statistics only, still a packet */
    m->num_ext_blocks = 0;
    assert(yb_hdr10plus_packet(m, bytes, w, DVVK_HDR10PLUS_V1, 0, &q) == 0);
    assert(q.coverage == 0 && q.reason == 1 && !(q.vsif[18] >> 4));
    /* no pixels measured: HDR10 */
    memset(w, 0, sizeof(w));
    assert(yb_hdr10plus_packet(m, bytes, w, DVVK_HDR10PLUS_V1, 0, &q) == DVVK_HDR10PLUS_FALLBACK);
    av_free(m);
}

static void to_dovi(void)
{
    AVDynamicHDRPlus s = {.itu_t_t35_country_code = 0xb5, .application_version = 1, .num_windows = 1,
                         .targeted_system_display_maximum_luminance = {1000, 1}};
    AVHDRPlusColorTransformParams *w = &s.params[0];
    const unsigned points[] = {1, 5, 10, 25, 50, 75, 90, 95, 99};
    const unsigned values[] = {10, 0, 255, 100, 500, 1000, 4000, 7000, 10000};
    w->num_distribution_maxrgb_percentiles = 9;
    for (unsigned i = 0; i < 9; i++)
        w->distribution_maxrgb[i] = (AVHDRPlusPercentile){points[i], {values[i], 100000}};
    for (unsigned i = 0; i < 3; i++)
        w->maxscl[i] = (AVRational){1, 10};
    w->average_maxrgb = (AVRational){1, 100};
    _Alignas(16) unsigned char buf[DVVK_HDR10PLUS_DOVI_BYTES];
    size_t size = 0;
    dvvk_hdr10plus_dovi_info info;
    const dvvk_hdr10_static st = {.max_luminance = 4000, .min_luminance = 0.005f, .max_cll = 1200, .max_fall = 300};
    AVDynamicHDRPlus before = s;
    /* CB1's HistogramPlus case: L1 max 3079, avg 1738 */
    assert(yb_hdr10plus_to_dovi(&s, sizeof(s), &st, NULL, buf, sizeof(buf), &size, &info) == 0);
    assert(!memcmp(&s, &before, sizeof(s)));
    assert(size > sizeof(AVDOVIMetadata) && size <= DVVK_HDR10PLUS_DOVI_BYTES);
    const AVDOVIMetadata *m = (const AVDOVIMetadata *)buf;
    assert(m->num_ext_blocks == 2 && m->ext_block_size == sizeof(AVDOVIDmData));
    const AVDOVIDmData *l1 = av_dovi_get_ext(m, 0), *l6 = av_dovi_get_ext(m, 1);
    assert(l1->level == 1 && l1->l1.min_pq == 0 && l1->l1.max_pq == 3079 && l1->l1.avg_pq == 1738);
    assert(l6->level == 6 && l6->l6.max_luminance == 4000 && l6->l6.min_luminance == 50 && l6->l6.max_cll == 1200 &&
           l6->l6.max_fall == 300);
    const AVDOVIColorMetadata *c = av_dovi_get_color(m);
    assert(c->source_max_pq == 3696 && c->source_min_pq == 62 && c->scene_refresh_flag == 1);
    assert(info.l1_max == 3079 && info.l1_avg == 1738 && info.source_fields == 6 && info.estimated_fields == 1 &&
           info.scene_refresh == 1 && !info.untranslated_curve);
    const AVDOVIRpuDataHeader *h = av_dovi_get_header(m);
    assert(h->vdr_rpu_profile == 1 && h->bl_bit_depth == 10 && h->vdr_bit_depth == 12 && h->disable_residual_flag);
    /* the same scene: no refresh */
    assert(yb_hdr10plus_to_dovi(&s, sizeof(s), &st, &before, buf, sizeof(buf), &size, &info) == 0);
    assert(info.scene_refresh == 0 && av_dovi_get_color(m)->scene_refresh_flag == 0);
    /* unknown static metadata: 0.005 .. 1000 cd/m2, no L6 values */
    assert(yb_hdr10plus_to_dovi(&s, sizeof(s), NULL, NULL, buf, sizeof(buf), &size, &info) == 0);
    assert(av_dovi_get_color(m)->source_max_pq == 3079 && av_dovi_get_ext(m, 1)->l6.max_luminance == 0);
    /* capacity, invalid and unsupported inputs */
    assert(yb_hdr10plus_to_dovi(&s, sizeof(s), &st, NULL, buf, 16, &size, &info) == -3 && size > 16);
    assert(yb_hdr10plus_to_dovi(&s, sizeof(s) - 1, &st, NULL, buf, sizeof(buf), &size, &info) == -1);
    assert(yb_hdr10plus_to_dovi(&s, sizeof(s), &st, NULL, buf + 1, sizeof(buf) - 1, &size, &info) == -1);
    s.num_windows = 2;
    assert(yb_hdr10plus_to_dovi(&s, sizeof(s), &st, NULL, buf, sizeof(buf), &size, &info) == -2);
    s.num_windows = 1;
    w->maxscl[0] = (AVRational){1, 3};   /* off the 0.00001 grid */
    assert(yb_hdr10plus_to_dovi(&s, sizeof(s), &st, NULL, buf, sizeof(buf), &size, &info) == -1);
}

int yb_test_yblod(void)
{
    statistics();
    packet();
    to_dovi();
    return 0;
}

/* An AVDynamicHDRPlus for src/hdr10plus.rs's planner test (CB1's
 * HistogramPlus case: L1 max 3079, avg 1738). Returns its size. */
size_t yb_test_hdr10plus_fixture(void *out, size_t capacity)
{
    if (capacity < sizeof(AVDynamicHDRPlus))
        return 0;
    AVDynamicHDRPlus s = {.itu_t_t35_country_code = 0xb5, .application_version = 1, .num_windows = 1,
                         .targeted_system_display_maximum_luminance = {1000, 1}};
    AVHDRPlusColorTransformParams *w = &s.params[0];
    const unsigned points[] = {1, 5, 10, 25, 50, 75, 90, 95, 99};
    const unsigned values[] = {10, 0, 255, 100, 500, 1000, 4000, 7000, 10000};
    w->num_distribution_maxrgb_percentiles = 9;
    for (unsigned i = 0; i < 9; i++)
        w->distribution_maxrgb[i] = (AVHDRPlusPercentile){points[i], {values[i], 100000}};
    for (unsigned i = 0; i < 3; i++)
        w->maxscl[i] = (AVRational){1, 10};
    w->average_maxrgb = (AVRational){1, 100};
    memcpy(out, &s, sizeof(s));
    return sizeof(s);
}
