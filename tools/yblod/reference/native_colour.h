#ifndef YBLOD_NATIVE_COLOUR_H
#define YBLOD_NATIVE_COLOUR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum yb_colour_status {
    YB_COLOUR_OK = 0,
    YB_COLOUR_INVALID_ARGUMENT = 1,
    YB_COLOUR_INVALID_CONFIG = 2,
    YB_COLOUR_DOMAIN_ERROR = 3,
    YB_COLOUR_NO_MEMORY = 4
};

enum yb_pq_policy {
    YB_PQ_REJECT_OUTSIDE_UNIT = 0,
    YB_PQ_EXTEND_POSITIVE_NEGATIVE_TO_ZERO = 1
};

/* Matrices are row-major. No metadata parser, target defaults or display
 * adaptation is supplied. Callers marshal validated finite numeric metadata.
 */
struct yb_colour_parameters {
    double source_ycc[9];
    double source_offset[3];
    double source_lms[9];
    double target_ycc[9];
    double target_offset[3];
    double target_lms[9];
    int32_t pq_policy;
    int32_t code_scale;
};

/* Initialize through yb_colour_init; do not edit the compiled configuration. */
struct yb_colour_config {
    struct yb_colour_parameters parameters;
    double target_ycc_inverse[9];
    double target_lms_inverse[9];
    uint32_t initialized;
};

struct yb_colour_result {
    double source_nonlinear[3];
    double common_linear_lms[3];
    double target_linear[3];
    double transport_before_quantization[3];
    uint16_t codes[3];
};

uint32_t yb_colour_abi_version(void);
uint64_t yb_sizeof_colour_parameters(void);
uint64_t yb_sizeof_colour_config(void);
uint64_t yb_sizeof_colour_result(void);
int yb_colour_init(const struct yb_colour_parameters *parameters,
                    struct yb_colour_config *config);
int yb_colour_validate(const struct yb_colour_config *config);
int yb_pq_decode(double value, int32_t policy, double *output);
int yb_pq_encode(double value, int32_t policy, double *output);
int yb_colour_sample(const struct yb_colour_config *config,
                      const double codes[3], struct yb_colour_result *output);

/* Count 1..65536. Input stride is in doubles (3..65536); output stride is in
 * result structures (1..65536). Inputs may contain fractional components from
 * separately declared chroma expansion, but must remain finite in0..4095.
 * All-or-nothing destination writes: a bounded temporary result array is used
 * so even a late matrix/PQ-domain failure leaves every output unchanged.
 * Reject output overlap with config/inputs. Alignment/range overflow checked;
 * real allocation sizes and stable input ownership remain caller obligations.
 */
int yb_colour_process_chunk(const struct yb_colour_config *config,
                             const double *input, uint32_t count,
                             uint32_t input_stride,
                             struct yb_colour_result *output,
                             uint32_t output_stride);

#ifdef __cplusplus
}
#endif
#endif
