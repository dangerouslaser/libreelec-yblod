#ifndef YB_NATIVE_SAMPLING_PROBE_H
#define YB_NATIVE_SAMPLING_PROBE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Diagnostic operators only, not Annex B, GPU texture emulation or Dolby rules.
 * Input is one host-u16 colour plane from lossless Y416 unpacking. No alpha.
 * Borrowed CPU allocations must remain accessible, coherent, alive and stable.
 * Complete plane required: padding is not a new image edge/tile boundary.
 */
#define YB_SAMPLING_MAX_DIMENSION 8192U
#define YB_SAMPLING_MAX_QUERIES 65536U
typedef struct {
    const uint16_t *data;
    uint64_t samples, width, height, stride_samples;
} yb_sampling_plane;
typedef struct {
    uint32_t width, height;
    int64_t origin_x, origin_y, step_x, step_y;
    uint32_t coordinate_fractional_bits; /* 0..16, coordinate divisor=2^bits */
    uint32_t method; /* 1 integer-point (fractional coordinates fail); 2 bilinear */
    uint32_t edge; /* 1 replicate */
    uint32_t native_depth, fractional_bits; /* explicit route native10/Q6 only */
    uint32_t word_normalization_divisor; /* explicit diagnostic divisor, nonzero */
} yb_sampling_contract;
typedef struct { uint32_t x, y; } yb_sampling_query;
typedef struct {
    int64_t source_x_numerator, source_y_numerator;
    uint64_t coordinate_denominator;
    uint64_t raw_numerator, raw_denominator;
    uint64_t native_denominator, normalized_denominator;
} yb_sampling_result;
enum { YB_SAMPLING_OK=0, YB_SAMPLING_BAD_PLANE=1, YB_SAMPLING_BAD_CONTRACT=2,
       YB_SAMPLING_BAD_BATCH=3, YB_SAMPLING_ALIAS=4, YB_SAMPLING_BAD_COORDINATE=5 };
/* Exact batch_count==result_count,1..65536. Results rational, unreduced.
 * Native equivalent=raw_numerator/native_denominator; diagnostic normalized
 * value=raw_numerator/normalized_denominator. Neither implies actual texture
 * normalization. Raw overshoot/fractional words are preserved, never clipped.
 * All validation (including late queries and aliasing) precedes any write.
 * Output must not overlap source, descriptors or queries. No ownership/fence,
 * input quantizer, inverse-NLQ or final composition policy is selected.
 */
int yb_sampling_probe(const yb_sampling_plane *,const yb_sampling_contract *,
                      const yb_sampling_query *,uint64_t batch_count,
                      yb_sampling_result *,uint64_t result_count);
#ifdef __cplusplus
}
#endif
#endif
