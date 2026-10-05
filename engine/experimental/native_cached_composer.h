#ifndef YB_NATIVE_CACHED_COMPOSER_H
#define YB_NATIVE_CACHED_COMPOSER_H
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
typedef struct yb_cached_plan yb_cached_plan;
typedef struct yb_cached_frame yb_cached_frame;
enum { YB_CACHE_NO_MEMORY=4 };
uint32_t yb_cached_abi_version(void);
uint64_t yb_cached_sizeof_plan(void);
/* Enabled requires exactly three NLQ configurations; disabled requires NULL.
 * Map and NLQ configurations are copied. All-polynomial components get exact
 * tables generated through unchanged reference scalar functions. Components
 * containing any MMR segment use the unchanged reference chunk kernel (its
 * mapping/NLQ/output work is not accelerated in this initial fallback).
 * Output pointer is unchanged on failure; destroy(NULL) is safe.
 */
int yb_cached_create(const struct yb_mapping_config *,
                     const struct yb_nlq_config *, int32_t enabled,
                     int32_t output_depth, yb_cached_plan **output);
void yb_cached_destroy(yb_cached_plan *);
/* 1 means full component polynomial lookup route, 0 means reference fallback;
 * invalid arguments return -1. This is not a fraction/whole-frame classifier.
 */
int yb_cached_component_route(const yb_cached_plan *,int32_t component);
/* Four stage outputs match yb_process_chunk exactly. Count 1..65536. All BL
 * arrays remain required/range checked; enabled EL required, disabled EL NULL.
 * Any failure leaves every output unchanged. Outputs must be mutually disjoint
 * and disjoint from the entire opaque plan and all input spans. Inputs must not
 * overlap the plan. No frame count/token or hardware readiness checks occur:
 * the surrounding integration adapter must preserve those separately.
 */
int yb_cached_process_chunk(const yb_cached_plan *,int32_t component,
    const uint16_t *y,const uint16_t *cb,const uint16_t *cr,const uint16_t *el,
    uint32_t count,uint16_t *mapped,int32_t *residual,int32_t *sum,
    uint16_t *reconstructed);
/* Frame wrapper starts a fresh session from a validated whole-code descriptor
 * and metadata; integration_init/finish remain the unchanged reference gates.
 * Output handle unchanged on failure. Single-thread-owned mutable frame state;
 * no concurrent dispatch/finish/destruction. All settings/tokens are copied.
 */
int yb_cached_frame_create(const yb_integration_descriptor *,
    const struct yb_mapping_config *,const struct yb_nlq_config *,
    yb_cached_frame **output);
void yb_cached_frame_destroy(yb_cached_frame *);
uint64_t yb_cached_sizeof_frame(void);
int yb_cached_frame_component_route(const yb_cached_frame *,int32_t component);
/* Returns integration statuses, including association/start/count/alias/state
 * failures. Only successful dispatch advances component counts. Whole-code
 * arithmetic only; raw diagnostic descriptors are rejected at creation.
 */
int yb_cached_frame_process(yb_cached_frame *,const uint8_t frame_id[32],
    int32_t component,uint64_t global_start,const uint16_t *y,const uint16_t *cb,
    const uint16_t *cr,const uint16_t *el,uint32_t count,uint16_t *mapped,
    int32_t *residual,int32_t *sum,uint16_t *reconstructed);
int yb_cached_frame_finish(yb_cached_frame *,yb_integration_completion *);
#ifdef __cplusplus
}
#endif
#endif
