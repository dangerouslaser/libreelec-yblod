#ifndef YB_NATIVE_MMR_COMPOSER_H
#define YB_NATIVE_MMR_COMPOSER_H
#include "native_composer.h"
#include "native_integration_probe.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Experimental exact whole-code backend. Opaque, heap-owned immutable plan;
 * not a fractional quantizer, frame-association API or replacement oracle.
 * Live plan must come from create; no concurrent destruction during queries
 * or processing. Borrowed buffers remain accessible and stable during calls.
 */
typedef struct yb_mmr_plan yb_mmr_plan;
typedef struct yb_mmr_frame yb_mmr_frame;
enum { YB_MMR_NO_MEMORY=4 };
uint32_t yb_mmr_abi_version(void);
uint64_t yb_mmr_sizeof_plan(void);
/* Enabled requires exactly three NLQ configurations; disabled requires NULL.
 * Map and NLQ configurations are copied. All-polynomial components get exact
 * tables generated through unchanged reference scalar functions. Components
 * containing MMR use exact Q20 terms, sparse coefficient lists and a proved
 * 64-bit accumulator where safe; otherwise signed 128-bit accumulation.
 * Rounding and clipping match the unchanged reference. No fractional input.
 * Output pointer is unchanged on failure; destroy(NULL) is safe.
 */
int yb_mmr_create(const struct yb_mapping_config *,
                     const struct yb_nlq_config *, int32_t enabled,
                     int32_t output_depth, yb_mmr_plan **output);
void yb_mmr_destroy(yb_mmr_plan *);
/* 1 means full component polynomial lookup route, 0 means prepared MMR route;
 * invalid arguments return -1. This is not a fraction/whole-frame classifier.
 */
int yb_mmr_component_route(const yb_mmr_plan *,int32_t component);
/* Four stage outputs match yb_process_chunk exactly. Count 1..65536. All BL
 * arrays remain required/range checked; enabled EL required, disabled EL NULL.
 * Any failure leaves every output unchanged. Outputs must be mutually disjoint
 * and disjoint from the entire opaque plan and all input spans. Inputs must not
 * overlap the plan. No frame count/token or hardware readiness checks occur:
 * the surrounding integration adapter must preserve those separately.
 */
int yb_mmr_process_chunk(const yb_mmr_plan *,int32_t component,
    const uint16_t *y,const uint16_t *cb,const uint16_t *cr,const uint16_t *el,
    uint32_t count,uint16_t *mapped,int32_t *residual,int32_t *sum,
    uint16_t *reconstructed);
/* Frame wrapper starts a fresh session from a validated whole-code descriptor
 * and metadata; integration_init/finish remain the unchanged reference gates.
 * Output handle unchanged on failure. Single-thread-owned mutable frame state;
 * no concurrent dispatch/finish/destruction. All settings/tokens are copied.
 */
int yb_mmr_frame_create(const yb_integration_descriptor *,
    const struct yb_mapping_config *,const struct yb_nlq_config *,
    yb_mmr_frame **output);
void yb_mmr_frame_destroy(yb_mmr_frame *);
uint64_t yb_mmr_sizeof_frame(void);
int yb_mmr_frame_component_route(const yb_mmr_frame *,int32_t component);
/* Returns integration statuses, including association/start/count/alias/state
 * failures. Only successful dispatch advances component counts. Whole-code
 * arithmetic only; raw diagnostic descriptors are rejected at creation.
 */
int yb_mmr_frame_process(yb_mmr_frame *,const uint8_t frame_id[32],
    int32_t component,uint64_t global_start,const uint16_t *y,const uint16_t *cb,
    const uint16_t *cr,const uint16_t *el,uint32_t count,uint16_t *mapped,
    int32_t *residual,int32_t *sum,uint16_t *reconstructed);
int yb_mmr_frame_finish(yb_mmr_frame *,yb_integration_completion *);
/* Returns 64/128 for an MMR segment, 0 for polynomial, -1 for invalid args.
 * Width is chosen from conservative metadata bounds, never from pixel values. */
int yb_mmr_segment_bits(const yb_mmr_plan *,int32_t component,int32_t segment);
int yb_mmr_frame_segment_bits(const yb_mmr_frame *,int32_t component,int32_t segment);
#ifdef __cplusplus
}
#endif
#endif

