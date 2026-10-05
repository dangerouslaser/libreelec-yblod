#include "native_sampling_probe.h"
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uintptr_t first;
    uintptr_t end;
} span;

static int make_span(const void *pointer, uint64_t bytes, span *result)
{
    uintptr_t first = (uintptr_t)pointer;
    if (pointer == NULL || bytes == 0U || bytes > (uint64_t)UINTPTR_MAX ||
        (uintptr_t)bytes > UINTPTR_MAX - first)
        return 0;
    result->first = first;
    result->end = first + (uintptr_t)bytes;
    return 1;
}

static int overlap(span a, span b)
{
    return a.first < b.end && b.first < a.end;
}

static int64_t floor_div(int64_t value, int64_t denominator)
{
    return value / denominator - ((value < 0 && value % denominator != 0) ? 1 : 0);
}

static uint64_t clamp_index(int64_t index, uint64_t size)
{
    if (index < 0)
        return 0U;
    return (uint64_t)index >= size ? size - 1U : (uint64_t)index;
}

static uint64_t at(const yb_sampling_plane *plane, int64_t x, int64_t y)
{
    uint64_t offset = clamp_index(y, plane->height) * plane->stride_samples +
                      clamp_index(x, plane->width);
    return plane->data[(size_t)offset];
}

int yb_sampling_probe(const yb_sampling_plane *plane,
                      const yb_sampling_contract *contract,
                      const yb_sampling_query *queries, uint64_t count,
                      yb_sampling_result *results, uint64_t result_count)
{
    span plane_span, contract_span, query_span, source_span, result_span;
    yb_sampling_plane saved_plane;
    yb_sampling_contract saved_contract;
    uint64_t footprint, denominator, raw_denominator;
    int64_t coordinate_bound;

    if (plane == NULL || (uintptr_t)plane % _Alignof(yb_sampling_plane) != 0U ||
        !make_span(plane, sizeof(*plane), &plane_span))
        return YB_SAMPLING_BAD_PLANE;
    saved_plane = *plane;
    if (saved_plane.width == 0U || saved_plane.height == 0U ||
        saved_plane.width > 8192U || saved_plane.height > 8192U ||
        saved_plane.stride_samples < saved_plane.width ||
        saved_plane.stride_samples > (uint64_t)SIZE_MAX / 2U ||
        saved_plane.samples > (uint64_t)SIZE_MAX / 2U ||
        saved_plane.samples > UINT64_MAX / 2U ||
        (uintptr_t)saved_plane.data % _Alignof(uint16_t) != 0U)
        return YB_SAMPLING_BAD_PLANE;
    if (saved_plane.height > 1U &&
        saved_plane.stride_samples >
            (UINT64_MAX - saved_plane.width) / (saved_plane.height - 1U))
        return YB_SAMPLING_BAD_PLANE;
    footprint = (saved_plane.height - 1U) * saved_plane.stride_samples + saved_plane.width;
    if (saved_plane.samples < footprint ||
        !make_span(saved_plane.data, saved_plane.samples * 2U, &source_span))
        return YB_SAMPLING_BAD_PLANE;

    if (contract == NULL ||
        (uintptr_t)contract % _Alignof(yb_sampling_contract) != 0U ||
        !make_span(contract, sizeof(*contract), &contract_span))
        return YB_SAMPLING_BAD_CONTRACT;
    saved_contract = *contract;
    if (saved_contract.width != saved_plane.width ||
        saved_contract.height != saved_plane.height ||
        saved_contract.coordinate_fractional_bits > 16U ||
        (saved_contract.method != 1U && saved_contract.method != 2U) ||
        saved_contract.edge != 1U || saved_contract.native_depth != 10U ||
        saved_contract.fractional_bits != 6U ||
        saved_contract.word_normalization_divisor == 0U)
        return YB_SAMPLING_BAD_CONTRACT;
    denominator = UINT64_C(1) << saved_contract.coordinate_fractional_bits;
    coordinate_bound = (int64_t)(8192U * denominator);
    if (saved_contract.origin_x < -coordinate_bound ||
        saved_contract.origin_x > coordinate_bound ||
        saved_contract.origin_y < -coordinate_bound ||
        saved_contract.origin_y > coordinate_bound ||
        saved_contract.step_x < -coordinate_bound ||
        saved_contract.step_x > coordinate_bound ||
        saved_contract.step_y < -coordinate_bound ||
        saved_contract.step_y > coordinate_bound)
        return YB_SAMPLING_BAD_CONTRACT;

    if (count == 0U || count > 65536U || result_count != count ||
        (uintptr_t)queries % _Alignof(yb_sampling_query) != 0U ||
        (uintptr_t)results % _Alignof(yb_sampling_result) != 0U ||
        !make_span(queries, count * sizeof(*queries), &query_span) ||
        !make_span(results, count * sizeof(*results), &result_span))
        return YB_SAMPLING_BAD_BATCH;
    if (overlap(result_span, plane_span) || overlap(result_span, contract_span) ||
        overlap(result_span, query_span) || overlap(result_span, source_span))
        return YB_SAMPLING_ALIAS;

    for (uint64_t index = 0U; index < count; ++index) {
        int64_t x, y;
        if (queries[index].x >= 8192U || queries[index].y >= 8192U)
            return YB_SAMPLING_BAD_COORDINATE;
        x = saved_contract.origin_x + saved_contract.step_x * (int64_t)queries[index].x;
        y = saved_contract.origin_y + saved_contract.step_y * (int64_t)queries[index].y;
        if (saved_contract.method == 1U &&
            (x % (int64_t)denominator != 0 || y % (int64_t)denominator != 0))
            return YB_SAMPLING_BAD_COORDINATE;
    }

    raw_denominator = saved_contract.method == 1U ? 1U : denominator * denominator;
    for (uint64_t index = 0U; index < count; ++index) {
        int64_t x = saved_contract.origin_x + saved_contract.step_x * (int64_t)queries[index].x;
        int64_t y = saved_contract.origin_y + saved_contract.step_y * (int64_t)queries[index].y;
        int64_t ix = floor_div(x, (int64_t)denominator);
        int64_t iy = floor_div(y, (int64_t)denominator);
        uint64_t raw;
        if (saved_contract.method == 1U) {
            raw = at(&saved_plane, ix, iy);
        } else {
            uint64_t tx = (uint64_t)(x - ix * (int64_t)denominator);
            uint64_t ty = (uint64_t)(y - iy * (int64_t)denominator);
            raw = (denominator - ty) *
                      ((denominator - tx) * at(&saved_plane, ix, iy) +
                       tx * at(&saved_plane, ix + 1, iy)) +
                  ty * ((denominator - tx) * at(&saved_plane, ix, iy + 1) +
                        tx * at(&saved_plane, ix + 1, iy + 1));
        }
        results[index].source_x_numerator = x;
        results[index].source_y_numerator = y;
        results[index].coordinate_denominator = denominator;
        results[index].raw_numerator = raw;
        results[index].raw_denominator = raw_denominator;
        results[index].native_denominator = raw_denominator * 64U;
        results[index].normalized_denominator =
            raw_denominator * saved_contract.word_normalization_divisor;
    }
    return YB_SAMPLING_OK;
}
