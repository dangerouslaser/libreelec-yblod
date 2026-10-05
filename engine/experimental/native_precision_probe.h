#ifndef YB_NATIVE_PRECISION_PROBE_H
#define YB_NATIVE_PRECISION_PROBE_H
#include "native_composer.h"
#ifdef __cplusplus
extern "C" {
#endif
/* DIAGNOSTIC ONLY. No selected/default production precision policy. */
enum yb_probe_quantization {
    YB_PROBE_FLOOR = 0, YB_PROBE_HALF_UP = 1, YB_PROBE_TIES_EVEN = 2
};
struct yb_probe_rational {
    int64_t uncapped_numerator;
    int64_t capped_numerator;
    uint64_t divisor;
    int64_t floored_residual;
};
/* Explicit native10 Q6 domain 0..65472; no endpoint expansion or clipping.
 * Config must be validated native10 metadata. Outputs unchanged on failure.
 * Buffers/config must be separate, valid, aligned and stable during each call.
 */
int yb_probe_quantized(const struct yb_nlq_config *, int64_t raw_word,
                       int32_t policy, int32_t *native_sample, int64_t *residual);
/* Literal rational pre-floor algebra, WITHOUT the shader's floating noise
 * guard. This is a hypothetical fractional extension, not Dolby conformance.
 */
int yb_probe_literal(const struct yb_nlq_config *, int64_t raw_word,
                     struct yb_probe_rational *result);
#ifdef __cplusplus
}
#endif
#endif
