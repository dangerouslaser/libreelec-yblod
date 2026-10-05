#ifndef YB_NATIVE_ANNEXB_PROBE_H
#define YB_NATIVE_ANNEXB_PROBE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Informative CCM Annex B EL arithmetic diagnostic only; no production policy.
 * One borrowed complete host-u16 component plane, stable/coherent throughout
 * this call. No DMA/fence ownership, physical registration or native-depth clamp.
 */
typedef struct {
    const uint16_t *data;
    uint64_t samples, width, height, stride_samples;
} yb_annexb_plane;
typedef struct { uint64_t x, y, width, height; } yb_annexb_rect;
typedef struct {
    uint16_t *data;
    uint64_t samples, stride_samples;
} yb_annexb_output;
enum { YB_ANNEXB_Y=0, YB_ANNEXB_CB=1, YB_ANNEXB_CR=2 };
enum { YB_ANNEXB_VERTICAL_ONLY=1, YB_ANNEXB_TWO_PASS=2 };
enum { YB_ANNEXB_OK=0, YB_ANNEXB_BAD_PLANE=1, YB_ANNEXB_BAD_MODE=2,
       YB_ANNEXB_BAD_REGION=3, YB_ANNEXB_BAD_OUTPUT=4,
       YB_ANNEXB_BAD_SCRATCH=5, YB_ANNEXB_ALIAS=6 };
/* Vertical-only output domain is native width by 2*native height; two-pass is
 * 2*native width by 2*native height. Rect is GLOBAL in the chosen domain;
 * a partial rectangle is never a new image edge. Input dimensions 1..8192.
 * requested_pixels must equal rect.width*rect.height,1..65536; storage extent
 * is distinct: (rect.height-1)*output.stride_samples+rect.width. Last-row pitch
 * padding not required. Scratch is exactly native width u16 samples.
 * Output and scratch must be disjoint from each other, full declared input
 * storage, and all three descriptors. Every check precedes ANY output/scratch
 * write; invalid calls leave both unchanged. Valid calls preserve output pitch
 * padding. All arithmetic uses exact per-pass floor-round and unsigned16 clip.
 * No allocation, fractional transport quantizer, QSV replacement or GPU job.
 */
int yb_annexb_probe(const yb_annexb_plane *, uint32_t component, uint32_t mode,
                   const yb_annexb_rect *, const yb_annexb_output *,
                   uint64_t requested_pixels, uint16_t *scratch,
                   uint64_t scratch_samples);
#ifdef __cplusplus
}
#endif
#endif
