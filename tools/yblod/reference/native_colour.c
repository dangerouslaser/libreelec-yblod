#include "native_colour.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Compile without fast-math or FP contraction. This is double/libm arithmetic,
 * not bit-exact GPU emulation or a licensed-domain continuation rule.
 */
#define YB_COLOUR_MAGIC UINT32_C(0x59424331)

static const double M1 = 2610.0 / 16384.0, M2 = 2523.0 / 32.0;
static const double C1 = 3424.0 / 4096.0, C2 = 2413.0 / 128.0, C3 = 2392.0 / 128.0;

uint32_t yb_colour_abi_version(void) { return 1; }
uint64_t yb_sizeof_colour_parameters(void) { return sizeof(struct yb_colour_parameters); }
uint64_t yb_sizeof_colour_config(void) { return sizeof(struct yb_colour_config); }
uint64_t yb_sizeof_colour_result(void) { return sizeof(struct yb_colour_result); }

static int policy_valid(int32_t policy)
{
    return policy == YB_PQ_REJECT_OUTSIDE_UNIT ||
           policy == YB_PQ_EXTEND_POSITIVE_NEGATIVE_TO_ZERO;
}

static int finite_array(const double *array, unsigned count)
{
    for (unsigned index = 0; index < count; ++index)
        if (!isfinite(array[index]))
            return 0;
    return 1;
}

static int parameters_valid(const struct yb_colour_parameters *parameters)
{
    return policy_valid(parameters->pq_policy) && parameters->code_scale == 4096 &&
           finite_array(parameters->source_ycc, 9) && finite_array(parameters->source_offset, 3) &&
           finite_array(parameters->source_lms, 9) && finite_array(parameters->target_ycc, 9) &&
           finite_array(parameters->target_offset, 3) && finite_array(parameters->target_lms, 9);
}

static int matrix_inverse(const double input[9], double output[9])
{
    const double a = input[0], b = input[1], c = input[2];
    const double d = input[3], e = input[4], f = input[5];
    const double g = input[6], h = input[7], i = input[8];
    const double cofactors[] = {e*i-f*h, f*g-d*i, d*h-e*g,
                               c*h-b*i, a*i-c*g, b*g-a*h,
                               b*f-c*e, c*d-a*f, a*e-b*d};
    const double determinant = a*cofactors[0] + b*cofactors[1] + c*cofactors[2];
    if (!isfinite(determinant) || determinant == 0)
        return 0;
    for (unsigned row = 0; row < 3; ++row)
        for (unsigned column = 0; column < 3; ++column)
            output[3*row+column] = cofactors[3*column+row] / determinant;
    return finite_array(output, 9);
}

int yb_colour_init(const struct yb_colour_parameters *parameters,
                    struct yb_colour_config *config)
{
    if (!parameters || !config)
        return YB_COLOUR_INVALID_ARGUMENT;
    if (!parameters_valid(parameters))
        return YB_COLOUR_INVALID_CONFIG;
    struct yb_colour_config temporary = {0};
    temporary.parameters = *parameters;
    if (!matrix_inverse(parameters->target_ycc, temporary.target_ycc_inverse) ||
        !matrix_inverse(parameters->target_lms, temporary.target_lms_inverse))
        return YB_COLOUR_INVALID_CONFIG;
    temporary.initialized = YB_COLOUR_MAGIC;
    *config = temporary;
    return YB_COLOUR_OK;
}

int yb_colour_validate(const struct yb_colour_config *config)
{
    if (!config)
        return YB_COLOUR_INVALID_ARGUMENT;
    if (config->initialized != YB_COLOUR_MAGIC || !parameters_valid(&config->parameters) ||
        !finite_array(config->target_ycc_inverse, 9) || !finite_array(config->target_lms_inverse, 9))
        return YB_COLOUR_INVALID_CONFIG;
    return YB_COLOUR_OK;
}

static int pq_input(double value, int32_t policy, double *bounded)
{
    if (!policy_valid(policy) || !isfinite(value) ||
        (policy == YB_PQ_REJECT_OUTSIDE_UNIT && (value < 0 || value > 1)))
        return YB_COLOUR_DOMAIN_ERROR;
    *bounded = value < 0 ? 0 : value;
    return YB_COLOUR_OK;
}

int yb_pq_decode(double value, int32_t policy, double *output)
{
    if (!output)
        return YB_COLOUR_INVALID_ARGUMENT;
    double input;
    int status = pq_input(value, policy, &input);
    if (status != YB_COLOUR_OK)
        return status;
    const double p = pow(input, 1 / M2);
    const double denominator = C2 - C3 * p;
    if (denominator <= 0 || !isfinite(denominator))
        return YB_COLOUR_DOMAIN_ERROR;
    const double numerator = p - C1;
    const double decoded = pow((numerator < 0 ? 0 : numerator) / denominator, 1 / M1);
    if (!isfinite(decoded))
        return YB_COLOUR_DOMAIN_ERROR;
    *output = decoded;
    return YB_COLOUR_OK;
}

int yb_pq_encode(double value, int32_t policy, double *output)
{
    if (!output)
        return YB_COLOUR_INVALID_ARGUMENT;
    double input;
    int status = pq_input(value, policy, &input);
    if (status != YB_COLOUR_OK)
        return status;
    const double p = pow(input, M1);
    const double encoded = pow((C1 + C2 * p) / (1 + C3 * p), M2);
    if (!isfinite(encoded))
        return YB_COLOUR_DOMAIN_ERROR;
    *output = encoded;
    return YB_COLOUR_OK;
}

static int matrix_multiply(const double matrix[9], const double input[3], double output[3])
{
    for (unsigned row = 0; row < 3; ++row) {
        double total = 0;
        for (unsigned column = 0; column < 3; ++column)
            total += matrix[3*row+column] * input[column];
        output[row] = total;
    }
    return finite_array(output, 3);
}

static int sample_validated(const struct yb_colour_config *config, const double codes[3],
                             struct yb_colour_result *output)
{
    const struct yb_colour_parameters *parameters = &config->parameters;
    struct yb_colour_result result = {0};
    double centered[3], linear[3], nonlinear[3];
    for (unsigned channel = 0; channel < 3; ++channel) {
        if (!isfinite(codes[channel]) || codes[channel] < 0 || codes[channel] > 4095)
            return YB_COLOUR_DOMAIN_ERROR;
        centered[channel] = codes[channel] / parameters->code_scale - parameters->source_offset[channel];
    }
    if (!finite_array(centered, 3) ||
        !matrix_multiply(parameters->source_ycc, centered, result.source_nonlinear))
        return YB_COLOUR_DOMAIN_ERROR;
    for (unsigned channel = 0; channel < 3; ++channel)
        if (yb_pq_decode(result.source_nonlinear[channel], parameters->pq_policy,
                          &linear[channel]) != YB_COLOUR_OK)
            return YB_COLOUR_DOMAIN_ERROR;
    if (!matrix_multiply(parameters->source_lms, linear, result.common_linear_lms) ||
        !matrix_multiply(config->target_lms_inverse, result.common_linear_lms, result.target_linear))
        return YB_COLOUR_DOMAIN_ERROR;
    for (unsigned channel = 0; channel < 3; ++channel)
        if (yb_pq_encode(result.target_linear[channel], parameters->pq_policy,
                          &nonlinear[channel]) != YB_COLOUR_OK)
            return YB_COLOUR_DOMAIN_ERROR;
    if (!matrix_multiply(config->target_ycc_inverse, nonlinear, result.transport_before_quantization))
        return YB_COLOUR_DOMAIN_ERROR;
    for (unsigned channel = 0; channel < 3; ++channel) {
        const double target = result.transport_before_quantization[channel] + parameters->target_offset[channel];
        const double unrounded = target * parameters->code_scale + 0.5;
        if (!isfinite(target) || !isfinite(unrounded))
            return YB_COLOUR_DOMAIN_ERROR;
        result.transport_before_quantization[channel] = target;
        const double rounded = floor(unrounded);
        result.codes[channel] = rounded < 0 ? 0 : rounded > 4095 ? 4095 : (uint16_t)rounded;
    }
    *output = result;
    return YB_COLOUR_OK;
}

int yb_colour_sample(const struct yb_colour_config *config,
                      const double codes[3], struct yb_colour_result *output)
{
    if (!codes || !output)
        return YB_COLOUR_INVALID_ARGUMENT;
    const int status = yb_colour_validate(config);
    return status == YB_COLOUR_OK ? sample_validated(config, codes, output) : status;
}

struct span { uintptr_t start, end; };
static int make_span(const void *pointer, uint64_t bytes, uintptr_t alignment, struct span *span)
{
    const uintptr_t start = (uintptr_t)pointer;
    if (!pointer || start % alignment || bytes > UINTPTR_MAX || start > UINTPTR_MAX - (uintptr_t)bytes)
        return 0;
    *span = (struct span){start, start + (uintptr_t)bytes};
    return 1;
}
static int overlaps(struct span a, struct span b) { return a.start < b.end && b.start < a.end; }

int yb_colour_process_chunk(const struct yb_colour_config *config,
                             const double *input, uint32_t count, uint32_t input_stride,
                             struct yb_colour_result *output, uint32_t output_stride)
{
    if (!count || count > 65536 || input_stride < 3 || input_stride > 65536 ||
        !output_stride || output_stride > 65536)
        return YB_COLOUR_INVALID_ARGUMENT;
    const uint64_t input_elements = (uint64_t)(count - 1) * input_stride + 3;
    const uint64_t output_elements = (uint64_t)(count - 1) * output_stride + 1;
    struct span input_span, output_span, config_span;
    if (!make_span(config, sizeof(*config), _Alignof(struct yb_colour_config), &config_span) ||
        !make_span(input, input_elements * sizeof(*input), _Alignof(double), &input_span) ||
        !make_span(output, output_elements * sizeof(*output), _Alignof(struct yb_colour_result), &output_span) ||
        overlaps(output_span, input_span) || overlaps(output_span, config_span))
        return YB_COLOUR_INVALID_ARGUMENT;
    const int status = yb_colour_validate(config);
    if (status != YB_COLOUR_OK)
        return status;
    struct yb_colour_result *temporary = malloc((size_t)count * sizeof(*temporary));
    if (!temporary)
        return YB_COLOUR_NO_MEMORY;
    for (uint32_t index = 0; index < count; ++index) {
        const int conversion = sample_validated(config, input + (size_t)index * input_stride, &temporary[index]);
        if (conversion != YB_COLOUR_OK) {
            free(temporary);
            return conversion;
        }
    }
    if (output_stride == 1)
        memcpy(output, temporary, (size_t)count * sizeof(*output));
    else
        for (uint32_t index = 0; index < count; ++index)
            output[(size_t)index * output_stride] = temporary[index];
    free(temporary);
    return YB_COLOUR_OK;
}
