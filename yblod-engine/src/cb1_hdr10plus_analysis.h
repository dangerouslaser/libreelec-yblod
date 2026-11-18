/* YBLOD 0.4.0: ported from CroqueMr's CB1 (github.com/CroqueMr/intel-dv-libreelec,
 * CB1/src/cb1_hdr10plus_analysis.h) at commit b5149a09d759ab2cc1dd8c0b6d156da67d70cae6 (upstream/main, 2026-11-18).
 * Only the statistics, the scene and cb1_hdr10plus_describe*: the GLES analysis pass is replaced by the
 * Vulkan engine's (shaders/pack.comp, STATS), which fills the same statistics.
 * CB1's notices follow and still apply. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef CB1_HDR10PLUS_ANALYSIS_H
#define CB1_HDR10PLUS_ANALYSIS_H
#include "dvbridge_policy.h"
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
    unsigned y99_nits;
    double y100_percent;
    bool luminance_valid;
};
struct cb1_hdr10plus_analysis;
/* YBLOD: a context for the scene functions alone, and the picture its next
 * cb1_hdr10plus_analysis_stage_scene is about (submit's identity in CB1). */
struct cb1_hdr10plus_analysis *cb1_hdr10plus_analysis_create_scene(void);
void cb1_hdr10plus_analysis_identify(struct cb1_hdr10plus_analysis *ctx, struct dvbridge_identity identity);
void cb1_hdr10plus_analysis_destroy(struct cb1_hdr10plus_analysis **ctx);
void cb1_hdr10plus_analysis_clear_scene(struct cb1_hdr10plus_analysis *ctx);
/* Accumulate on the pending scene snapshot and commit it with the picture. */
void cb1_hdr10plus_analysis_stage_scene(struct cb1_hdr10plus_analysis *ctx,
    struct cb1_hdr10plus_statistics *statistics, bool scene_refresh);
void cb1_hdr10plus_analysis_commit_scene(struct cb1_hdr10plus_analysis *ctx);
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
