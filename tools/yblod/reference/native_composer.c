#include "native_composer.h"

/* GCC/Clang signed 128-bit arithmetic is required for the accepted MMR
 * coefficient envelope. No negative right shifts or signed-overflow tricks.
 */
#if !defined(__SIZEOF_INT128__) || __SIZEOF_INT128__ < 16
#error "native_composer requires compiler support for signed __int128"
#endif
typedef __int128 yb_wide;

uint32_t yb_abi_version(void) { return 1; }
uint64_t yb_sizeof_mapping_config(void) { return sizeof(struct yb_mapping_config); }
uint64_t yb_sizeof_nlq_config(void) { return sizeof(struct yb_nlq_config); }
uint64_t yb_sizeof_component_mapping(void) { return sizeof(struct yb_component_mapping); }
uint64_t yb_sizeof_segment(void) { return sizeof(struct yb_segment); }

static yb_wide floor_div_power2(yb_wide value, unsigned shift)
{
    /* Shift only nonnegative signed operands. For a negative value, the
     * complement identity preserves mathematical floor without division:
     * floor(v / 2^s) = -1 - floor((-(v + 1)) / 2^s).
     * v+1 also makes the negation safe at the signed-wide minimum.
     * Validated callers keep shift within 0..36.
     */
    return value >= 0 ? value >> shift : -1 - ((-(value + 1)) >> shift);
}

static yb_wide bounded(yb_wide value, yb_wide low, yb_wide high)
{
    return value < low ? low : value > high ? high : value;
}

static int depth_valid(int32_t depth)
{
    return depth == 8 || depth == 10;
}

static int segment_zero(const struct yb_segment *segment)
{
    if (segment->method || segment->order || segment->constant)
        return 0;
    for (unsigned row = 0; row < 3; ++row)
        for (unsigned term = 0; term < YB_MMR_TERMS; ++term)
            if (segment->coefficients[row][term])
                return 0;
    return 1;
}

int yb_validate_mapping(const struct yb_mapping_config *config)
{
    if (!config)
        return YB_INVALID_ARGUMENT;
    if (!depth_valid(config->bit_depth) || config->denominator < 13 ||
        config->denominator > 32)
        return YB_INVALID_CONFIG;
    const int32_t native_max = (1 << config->bit_depth) - 1;
    for (unsigned component = 0; component < YB_COMPONENTS; ++component) {
        const struct yb_component_mapping *mapping = &config->components[component];
        if (mapping->pivot_count < 2 || mapping->pivot_count > YB_MAX_PIVOTS)
            return YB_INVALID_CONFIG;
        for (int32_t index = 0; index < YB_MAX_PIVOTS; ++index) {
            const int32_t pivot = mapping->pivots[index];
            if (index >= mapping->pivot_count) {
                if (pivot)
                    return YB_INVALID_CONFIG;
            } else if (pivot < 0 || pivot > native_max ||
                       (index && pivot <= mapping->pivots[index - 1])) {
                return YB_INVALID_CONFIG;
            }
        }
        for (int32_t index = 0; index < YB_MAX_SEGMENTS; ++index) {
            const struct yb_segment *segment = &mapping->segments[index];
            if (index >= mapping->pivot_count - 1) {
                if (!segment_zero(segment))
                    return YB_INVALID_CONFIG;
                continue;
            }
            const int polynomial = segment->method == YB_POLYNOMIAL;
            if (polynomial ? (segment->order < 1 || segment->order > 2 || segment->constant) :
                             (segment->method != YB_MMR || component == 0 ||
                              segment->order < 1 || segment->order > 3))
                return YB_INVALID_CONFIG;
            const int64_t limit = (polynomial ? INT64_C(64) : INT64_C(65536)) *
                                  (INT64_C(1) << config->denominator);
            if (!polynomial && (segment->constant < -limit || segment->constant >= limit))
                return YB_INVALID_CONFIG;
            for (int32_t row = 0; row < 3; ++row) {
                for (int32_t term = 0; term < YB_MMR_TERMS; ++term) {
                    const int used = polynomial ? (row == 0 && term <= segment->order) :
                                                  row < segment->order;
                    const int64_t coefficient = segment->coefficients[row][term];
                    if (used ? (coefficient < -limit || coefficient >= limit) : coefficient != 0)
                        return YB_INVALID_CONFIG;
                }
            }
        }
    }
    return YB_OK;
}

int yb_validate_nlq(const struct yb_nlq_config *config)
{
    if (!config)
        return YB_INVALID_ARGUMENT;
    if (!depth_valid(config->bit_depth) || config->denominator < config->bit_depth + 5 ||
        config->denominator > 32 || config->offset < 0 ||
        config->offset >= (1 << config->bit_depth))
        return YB_INVALID_CONFIG;
    const uint64_t limit = UINT64_C(1) << (config->denominator + 1);
    if (config->slope >= limit || config->threshold >= limit || config->maximum >= limit)
        return YB_INVALID_CONFIG;
    return YB_OK;
}

static void mmr_terms(const int64_t samples[YB_COMPONENTS], unsigned depth,
                      yb_wide terms[3][YB_MMR_TERMS])
{
    for (unsigned component = 0; component < YB_COMPONENTS; ++component) {
        const yb_wide code = samples[component];
        terms[0][component] = code * ((yb_wide)1 << (20 - depth));
        terms[1][component] = code * code * ((yb_wide)1 << (20 - 2 * depth));
    }
    const unsigned a[] = {0, 0, 1};
    const unsigned b[] = {1, 2, 2};
    for (unsigned pair = 0; pair < 3; ++pair)
        terms[0][3 + pair] = (yb_wide)samples[a[pair]] * samples[b[pair]] *
                             ((yb_wide)1 << (20 - 2 * depth));
    terms[0][6] = floor_div_power2(terms[0][3] * terms[0][2], 20);
    for (unsigned term = 3; term < YB_MMR_TERMS; ++term)
        terms[1][term] = floor_div_power2(terms[0][term] * terms[0][term], 20);
    for (unsigned term = 0; term < YB_MMR_TERMS; ++term)
        terms[2][term] = floor_div_power2(terms[0][term] * terms[1][term], 20);
}

static uint16_t map_validated(const struct yb_mapping_config *config, int32_t component,
                              const int64_t samples[YB_COMPONENTS])
{
    int64_t codes[YB_COMPONENTS];
    for (unsigned channel = 0; channel < YB_COMPONENTS; ++channel) {
        const struct yb_component_mapping *curve = &config->components[channel];
        codes[channel] = (int64_t)bounded(samples[channel], curve->pivots[0],
                                         curve->pivots[curve->pivot_count - 1]);
    }
    const struct yb_component_mapping *curve = &config->components[component];
    int32_t index = 0;
    while (index < curve->pivot_count - 2 && samples[component] >= curve->pivots[index + 1])
        ++index;
    const struct yb_segment *segment = &curve->segments[index];
    yb_wide total = 0;
    if (segment->method == YB_POLYNOMIAL) {
        yb_wide power = 1;
        for (int32_t degree = 0; degree <= segment->order; ++degree) {
            total += (yb_wide)segment->coefficients[0][degree] * power *
                     ((yb_wide)1 << (20 - config->bit_depth * degree));
            power *= codes[component];
        }
    } else {
        yb_wide terms[3][YB_MMR_TERMS];
        mmr_terms(codes, (unsigned)config->bit_depth, terms);
        total = (yb_wide)segment->constant * ((yb_wide)1 << 20);
        for (int32_t row = 0; row < segment->order; ++row)
            for (unsigned term = 0; term < YB_MMR_TERMS; ++term)
                total += (yb_wide)segment->coefficients[row][term] * terms[row][term];
    }
    return (uint16_t)bounded(floor_div_power2(total, (unsigned)config->denominator + 4), 0, 65535);
}

int yb_map_sample(const struct yb_mapping_config *config, int32_t component,
                  const int64_t samples[YB_COMPONENTS], uint16_t *output)
{
    if (!samples || !output)
        return YB_INVALID_ARGUMENT;
    const int status = yb_validate_mapping(config);
    if (status != YB_OK)
        return status;
    if (component < 0 || component >= YB_COMPONENTS)
        return YB_INVALID_SAMPLE;
    const int64_t native_max = (INT64_C(1) << config->bit_depth) - 1;
    for (unsigned channel = 0; channel < YB_COMPONENTS; ++channel)
        if (samples[channel] < 0 || samples[channel] > native_max)
            return YB_INVALID_SAMPLE;
    *output = map_validated(config, component, samples);
    return YB_OK;
}

static int64_t nlq_validated(const struct yb_nlq_config *config, int64_t sample)
{
    const int64_t distance = sample - config->offset;
    yb_wide result = 0;
    if (distance) {
        const int direction = distance > 0 ? 1 : -1;
        const yb_wide gain = (yb_wide)1 << (10 - config->bit_depth);
        const yb_wide accumulator = ((2 * (yb_wide)distance - direction) * config->slope +
                                     2 * (yb_wide)direction * config->threshold) * gain;
        const yb_wide limit = 2 * gain * config->maximum;
        result = floor_div_power2(bounded(accumulator, -limit, limit),
                                  (unsigned)(config->denominator - 5 - config->bit_depth));
    }
    return (int64_t)result;
}

int yb_nlq(const struct yb_nlq_config *config, int64_t sample, int64_t *output)
{
    if (!output)
        return YB_INVALID_ARGUMENT;
    const int status = yb_validate_nlq(config);
    if (status != YB_OK)
        return status;
    if (sample < 0 || sample >= (INT64_C(1) << config->bit_depth))
        return YB_INVALID_SAMPLE;
    *output = nlq_validated(config, sample);
    return YB_OK;
}

static uint16_t compose_validated(int64_t mapped, int64_t residual, int32_t output_depth)
{
    const unsigned shift = (unsigned)(16 - output_depth);
    const yb_wide total = (yb_wide)mapped + residual + ((yb_wide)1 << (shift - 1));
    return (uint16_t)bounded(floor_div_power2(total, shift), 0, (1 << output_depth) - 1);
}

int yb_compose_residual(int64_t mapped, int64_t residual, int32_t output_depth,
                        uint16_t *output)
{
    if (!output)
        return YB_INVALID_ARGUMENT;
    if (mapped < 0 || mapped > 65535 || (output_depth != 10 && output_depth != 12))
        return YB_INVALID_SAMPLE;
    *output = compose_validated(mapped, residual, output_depth);
    return YB_OK;
}

int yb_compose(const struct yb_nlq_config *config, int64_t mapped,
                int64_t sample, int32_t output_depth, uint16_t *output)
{
    if (!output)
        return YB_INVALID_ARGUMENT;
    if (mapped < 0 || mapped > 65535 || (output_depth != 10 && output_depth != 12))
        return YB_INVALID_SAMPLE;
    int64_t residual;
    const int status = yb_nlq(config, sample, &residual);
    return status == YB_OK ? yb_compose_residual(mapped, residual, output_depth, output) : status;
}

struct span { uintptr_t start, end; };

static int make_span(const void *pointer, uint64_t bytes, uintptr_t alignment,
                      struct span *span)
{
    const uintptr_t start = (uintptr_t)pointer;
    if (!pointer || start % alignment || bytes > UINTPTR_MAX ||
        start > UINTPTR_MAX - (uintptr_t)bytes)
        return 0;
    *span = (struct span){start, start + (uintptr_t)bytes};
    return 1;
}

static int overlaps(struct span a, struct span b)
{
    return a.start < b.end && b.start < a.end;
}

int yb_process_chunk(const struct yb_mapping_config *map,
                     const struct yb_nlq_config *nlq, int32_t component,
                     const uint16_t *y, const uint16_t *cb, const uint16_t *cr,
                     const uint16_t *el, uint32_t count, int32_t enabled,
                     int32_t output_depth, uint16_t *mapped, int32_t *residual,
                     int32_t *sum, uint16_t *reconstructed)
{
    if (!count || count > 65536 || (enabled != 0 && enabled != 1) ||
        (!enabled && (nlq || el)))
        return YB_INVALID_ARGUMENT;
    if (component < 0 || component >= YB_COMPONENTS ||
        (output_depth != 10 && output_depth != 12))
        return YB_INVALID_SAMPLE;
    struct span inputs[6], outputs[4];
    if (!make_span(map, sizeof(*map), _Alignof(struct yb_mapping_config), &inputs[0]) ||
        !make_span(y, (uint64_t)count * sizeof(*y), _Alignof(uint16_t), &inputs[1]) ||
        !make_span(cb, (uint64_t)count * sizeof(*cb), _Alignof(uint16_t), &inputs[2]) ||
        !make_span(cr, (uint64_t)count * sizeof(*cr), _Alignof(uint16_t), &inputs[3]) ||
        !make_span(mapped, (uint64_t)count * sizeof(*mapped), _Alignof(uint16_t), &outputs[0]) ||
        !make_span(residual, (uint64_t)count * sizeof(*residual), _Alignof(int32_t), &outputs[1]) ||
        !make_span(sum, (uint64_t)count * sizeof(*sum), _Alignof(int32_t), &outputs[2]) ||
        !make_span(reconstructed, (uint64_t)count * sizeof(*reconstructed), _Alignof(uint16_t), &outputs[3]))
        return YB_INVALID_ARGUMENT;
    unsigned input_count = 4;
    if (enabled) {
        if (!make_span(nlq, sizeof(*nlq), _Alignof(struct yb_nlq_config), &inputs[4]) ||
            !make_span(el, (uint64_t)count * sizeof(*el), _Alignof(uint16_t), &inputs[5]))
            return YB_INVALID_ARGUMENT;
        input_count = 6;
    }
    for (unsigned output = 0; output < 4; ++output) {
        for (unsigned other = 0; other < output; ++other)
            if (overlaps(outputs[output], outputs[other]))
                return YB_INVALID_ARGUMENT;
        for (unsigned input = 0; input < input_count; ++input)
            if (overlaps(outputs[output], inputs[input]))
                return YB_INVALID_ARGUMENT;
    }
    int status = yb_validate_mapping(map);
    if (status != YB_OK)
        return status;
    if (enabled) {
        status = yb_validate_nlq(nlq);
        if (status != YB_OK)
            return status;
        if (map->denominator != nlq->denominator)
            return YB_INVALID_CONFIG;
    }
    const uint16_t base_max = (uint16_t)((1 << map->bit_depth) - 1);
    const uint16_t enhancement_max = (uint16_t)(enabled ? (1 << nlq->bit_depth) - 1 : 0);
    for (uint32_t index = 0; index < count; ++index)
        if (y[index] > base_max || cb[index] > base_max || cr[index] > base_max ||
            (enabled && el[index] > enhancement_max))
            return YB_INVALID_SAMPLE;
    /* No fallible operation after this point, absent concurrent caller mutation
     * or invalid buffer ownership. Correction is in [-2^17, 2^17-1], so
     * signed correction and unrounded sum fit the declared int32 outputs.
     */
    for (uint32_t index = 0; index < count; ++index) {
        const int64_t samples[] = {y[index], cb[index], cr[index]};
        const uint16_t base = map_validated(map, component, samples);
        const int64_t correction = enabled ? nlq_validated(nlq, el[index]) : 0;
        mapped[index] = base;
        residual[index] = (int32_t)correction;
        sum[index] = (int32_t)(base + correction);
        reconstructed[index] = compose_validated(base, correction, output_depth);
    }
    return YB_OK;
}
