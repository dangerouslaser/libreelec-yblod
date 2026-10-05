#ifndef YB_NATIVE_INTEGRATION_PROBE_H
#define YB_NATIVE_INTEGRATION_PROBE_H
#include "native_composer.h"
#include "native_sampling_probe.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Standalone diagnostic adapter. Borrowed CPU buffers, no device/fence ownership.
 * Context is single-thread-owned; do not edit it after initialization. Tokens
 * are caller assertions, not authentication. No colour/packing/HDMI completion.
 */
enum { YB_INPUT_WHOLE_CODES=1, YB_INPUT_RAW_DIAGNOSTIC=2 };
enum { YB_INTEGRATION_OK=0, YB_INTEGRATION_INVALID=1,
       YB_INTEGRATION_ASSOCIATION=2, YB_INTEGRATION_ROUTE=3,
       YB_INTEGRATION_FRACTIONAL_POLICY_REQUIRED=4,
       YB_INTEGRATION_COUNTS=5, YB_INTEGRATION_STAGE=6,
       YB_INTEGRATION_FINALIZED=7, YB_INTEGRATION_ALIAS=8 };
enum { YB_ARITHMETIC_FRAME_COMPLETE=1, YB_DIAGNOSTIC_SESSION_COMPLETE=2 };
typedef struct {
    uint32_t version, input_kind, width, height;
    int32_t output_depth, enhancement_enabled;
    uint8_t frame_id[32], provenance_id[32];
} yb_integration_descriptor;
typedef struct {
    uint32_t initialized, finalized;
    yb_integration_descriptor descriptor;
    struct yb_mapping_config mapping;
    struct yb_nlq_config nlq[3];
    yb_sampling_contract sampling;
    uint64_t consumed[3], diagnostic_queries;
} yb_integration_context;
typedef struct { uint32_t kind; uint64_t counts[3], diagnostic_queries; }
    yb_integration_completion;
uint32_t yb_integration_abi_version(void);
uint64_t yb_integration_sizeof_descriptor(void);
uint64_t yb_integration_sizeof_context(void);
uint64_t yb_integration_sizeof_completion(void);
uint64_t yb_integration_sizeof_sampling_contract(void);
/* Whole-code: map required; enabled requires exactly three NLQ configs, disabled
 * requires NULL. Raw: map/NLQ NULL, sampling required native10/Q6, integer output
 * settings zero. Complete plane is required by raw sampling, NOT a row tile.
 * init and failed dispatch/finalization leave destinations/context unchanged.
 * Chunk calls preserve earlier successful output if a later frame call fails.
 */
int yb_integration_init(yb_integration_context *,const yb_integration_descriptor *,
                        const struct yb_mapping_config *,
                        const struct yb_nlq_config *,const yb_sampling_contract *);
int yb_integration_integer(yb_integration_context *,const uint8_t frame_id[32],
                          int32_t component,uint64_t global_start,
                          const uint16_t *y,const uint16_t *cb,const uint16_t *cr,
                          const uint16_t *el,uint32_t count,uint16_t *mapped,
                          int32_t *residual,int32_t *sum,uint16_t *reconstructed);
int yb_integration_raw(yb_integration_context *,const uint8_t frame_id[32],
                      const yb_sampling_plane *,const yb_sampling_query *,
                      uint64_t count,yb_sampling_result *);
int yb_integration_finish(yb_integration_context *,yb_integration_completion *);
void yb_integration_reset(yb_integration_context *);
#ifdef __cplusplus
}
#endif
#endif
