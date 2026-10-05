#include "native_annexb_probe.h"
#include <stddef.h>
#include <stdint.h>

typedef struct { uintptr_t first, end; } span;

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

static int overlaps(span a, span b)
{
    return a.first < b.end && b.first < a.end;
}

static uint64_t clamp_index(int64_t index, uint64_t size)
{
    if (index < 0)
        return 0U;
    return (uint64_t)index >= size ? size - 1U : (uint64_t)index;
}

static int64_t source(const yb_annexb_plane *plane, uint64_t x, int64_t y)
{
    uint64_t offset = clamp_index(y, plane->height) * plane->stride_samples + x;
    return (int64_t)plane->data[(size_t)offset];
}

static uint16_t round_bound(int64_t numerator, int64_t denominator)
{
    int64_t biased = numerator + denominator / 2;
    int64_t value = biased / denominator -
                    ((biased < 0 && biased % denominator != 0) ? 1 : 0);
    if (value < 0)
        return 0U;
    if (value > 65535)
        return UINT16_MAX;
    return (uint16_t)value;
}

static uint16_t vertical(const yb_annexb_plane *plane, uint32_t component,
                         uint64_t x, uint64_t y)
{
    int64_t row = (int64_t)(y / 2U);
    if (component == YB_ANNEXB_Y) {
        if (y % 2U == 0U)
            return round_bound(-3 * source(plane, x, row - 2) +
                               29 * source(plane, x, row - 1) +
                               111 * source(plane, x, row) -
                               9 * source(plane, x, row + 1), 128);
        return round_bound(-9 * source(plane, x, row - 1) +
                           111 * source(plane, x, row) +
                           29 * source(plane, x, row + 1) -
                           3 * source(plane, x, row + 2), 128);
    }
    if (y % 2U == 0U)
        return round_bound(64 * source(plane, x, row - 1) +
                           192 * source(plane, x, row), 256);
    return round_bound(192 * source(plane, x, row) +
                       64 * source(plane, x, row + 1), 256);
}

static uint16_t horizontal(const uint16_t *row, uint64_t width, uint64_t x)
{
    static const int64_t coefficients[8] = {22, 94, -524, 2456, 2456, -524, 94, 22};
    int64_t column = (int64_t)(x / 2U);
    int64_t numerator = 0;
    if (x % 2U == 0U)
        return row[(size_t)(x / 2U)];
    for (int64_t tap = 0; tap < 8; ++tap)
        numerator += coefficients[(size_t)tap] *
                     (int64_t)row[(size_t)clamp_index(column + tap - 3, width)];
    return round_bound(numerator, 4096);
}

int yb_annexb_probe(const yb_annexb_plane *plane, uint32_t component, uint32_t mode,
                   const yb_annexb_rect *region, const yb_annexb_output *output,
                   uint64_t requested_pixels, uint16_t *scratch,
                   uint64_t scratch_samples)
{
    span descriptors[3], source_span, output_span, scratch_span;
    yb_annexb_plane saved_plane;
    yb_annexb_rect saved_region;
    yb_annexb_output saved_output;
    uint64_t footprint, output_width, output_height;

    if (plane == NULL || (uintptr_t)plane % _Alignof(yb_annexb_plane) != 0U ||
        !make_span(plane, sizeof(*plane), &descriptors[0]))
        return YB_ANNEXB_BAD_PLANE;
    saved_plane = *plane;
    if (saved_plane.width == 0U || saved_plane.height == 0U ||
        saved_plane.width > 8192U || saved_plane.height > 8192U ||
        saved_plane.stride_samples < saved_plane.width ||
        saved_plane.stride_samples > (uint64_t)SIZE_MAX / 2U ||
        saved_plane.samples > (uint64_t)SIZE_MAX / 2U ||
        (uintptr_t)saved_plane.data % _Alignof(uint16_t) != 0U)
        return YB_ANNEXB_BAD_PLANE;
    if (saved_plane.height > 1U && saved_plane.stride_samples >
        (UINT64_MAX - saved_plane.width) / (saved_plane.height - 1U))
        return YB_ANNEXB_BAD_PLANE;
    footprint = (saved_plane.height - 1U) * saved_plane.stride_samples + saved_plane.width;
    if (saved_plane.samples < footprint ||
        !make_span(saved_plane.data, saved_plane.samples * 2U, &source_span))
        return YB_ANNEXB_BAD_PLANE;
    if (component > YB_ANNEXB_CR ||
        (mode != YB_ANNEXB_VERTICAL_ONLY && mode != YB_ANNEXB_TWO_PASS))
        return YB_ANNEXB_BAD_MODE;

    if (region == NULL || (uintptr_t)region % _Alignof(yb_annexb_rect) != 0U ||
        !make_span(region, sizeof(*region), &descriptors[1]))
        return YB_ANNEXB_BAD_REGION;
    saved_region = *region;
    output_width = saved_plane.width * (mode == YB_ANNEXB_TWO_PASS ? 2U : 1U);
    output_height = saved_plane.height * 2U;
    if (saved_region.width == 0U || saved_region.height == 0U ||
        saved_region.x >= output_width || saved_region.y >= output_height ||
        saved_region.width > output_width - saved_region.x ||
        saved_region.height > output_height - saved_region.y ||
        saved_region.height > 65536U / saved_region.width ||
        requested_pixels != saved_region.width * saved_region.height)
        return YB_ANNEXB_BAD_REGION;

    if (output == NULL || (uintptr_t)output % _Alignof(yb_annexb_output) != 0U ||
        !make_span(output, sizeof(*output), &descriptors[2]))
        return YB_ANNEXB_BAD_OUTPUT;
    saved_output = *output;
    if (saved_output.stride_samples < saved_region.width ||
        saved_output.stride_samples > (uint64_t)SIZE_MAX / 2U ||
        saved_output.samples > (uint64_t)SIZE_MAX / 2U ||
        (uintptr_t)saved_output.data % _Alignof(uint16_t) != 0U)
        return YB_ANNEXB_BAD_OUTPUT;
    if (saved_region.height > 1U && saved_output.stride_samples >
        (UINT64_MAX - saved_region.width) / (saved_region.height - 1U))
        return YB_ANNEXB_BAD_OUTPUT;
    footprint = (saved_region.height - 1U) * saved_output.stride_samples + saved_region.width;
    if (saved_output.samples < footprint ||
        !make_span(saved_output.data, saved_output.samples * 2U, &output_span))
        return YB_ANNEXB_BAD_OUTPUT;
    if (scratch_samples != saved_plane.width ||
        (uintptr_t)scratch % _Alignof(uint16_t) != 0U ||
        !make_span(scratch, scratch_samples * 2U, &scratch_span))
        return YB_ANNEXB_BAD_SCRATCH;
    if (overlaps(output_span, source_span) || overlaps(scratch_span, source_span) ||
        overlaps(output_span, scratch_span))
        return YB_ANNEXB_ALIAS;
    for (size_t index = 0U; index < 3U; ++index) {
        if (overlaps(output_span, descriptors[index]) ||
            overlaps(scratch_span, descriptors[index]))
            return YB_ANNEXB_ALIAS;
    }

    for (uint64_t row = 0U; row < saved_region.height; ++row) {
        for (uint64_t x = 0U; x < saved_plane.width; ++x)
            scratch[(size_t)x] = vertical(&saved_plane, component, x, saved_region.y + row);
        for (uint64_t x = 0U; x < saved_region.width; ++x) {
            uint64_t offset = row * saved_output.stride_samples + x;
            uint64_t global_x = saved_region.x + x;
            saved_output.data[(size_t)offset] = mode == YB_ANNEXB_TWO_PASS ?
                horizontal(scratch, saved_plane.width, global_x) : scratch[(size_t)global_x];
        }
    }
    return YB_ANNEXB_OK;
}
