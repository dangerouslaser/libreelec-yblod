/* YBLOD 0.4.0: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/cb1_hdr10plus_analysis.h) at commit 9eb35aeb1146e9a6c3652b7a43225511887cdc17 (upstream/main, 2026-11-07).
 * Only the statistics and cb1_hdr10plus_describe*: the GLES analysis pass is replaced by the
 * Vulkan engine's (shaders/pack.comp, STATS), which fills the same statistics.
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef CB1_HDR10PLUS_ANALYSIS_H
#define CB1_HDR10PLUS_ANALYSIS_H
#include "cb1_hdr10plus.h"
#ifdef __cplusplus
extern "C" {
#endif

/* Linear-light nits. Histogram entries use the HDMI 16-nit quantization,
 * saturating at code 255. Every pixel in the selected rectangle is counted. */
struct cb1_hdr10plus_statistics {
    double maxscl[3], average_maxrgb;
    uint64_t count;
    uint32_t histogram[256];
};
/* Descriptive metadata only. No synthesized creative curve. */
bool cb1_hdr10plus_describe(AVDynamicHDRPlus *out,
    const struct cb1_hdr10plus_statistics *statistics, unsigned target_nits);
bool cb1_hdr10plus_describe_for_version(AVDynamicHDRPlus *out,
    const struct cb1_hdr10plus_statistics *statistics, unsigned target_nits,
    unsigned application_version);

#ifdef __cplusplus
}
#endif
#endif
