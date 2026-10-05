#include "native_y416.h"
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

static uint16_t load_le16(const uint8_t *source)
{
    return (uint16_t)((uint16_t)source[0] | (uint16_t)((uint16_t)source[1] << 8U));
}

uint64_t yb_y416_sizeof_surface(void)
{
    return (uint64_t)sizeof(yb_y416_surface);
}

int yb_y416_unpack_rows(const yb_y416_surface *surface,
                       uint64_t first_row, uint64_t row_count,
                       uint16_t *u, uint16_t *y, uint16_t *v, uint16_t *alpha,
                       uint64_t output_samples)
{
    span descriptor_span, source_span, outputs[4];
    uint16_t *planes[4] = {u, y, v, alpha};
    uint64_t row_bytes, footprint, expected;
    yb_y416_surface saved;
    if (surface == NULL || (uintptr_t)surface % _Alignof(yb_y416_surface) != 0U ||
        !make_span(surface, (uint64_t)sizeof(*surface), &descriptor_span))
        return YB_Y416_BAD_SURFACE;
    saved = *surface;
    if (saved.layout != YB_Y416_LE_UYVA || saved.storage_bits != 16U ||
        saved.native_depth != 10U || saved.fractional_bits != 6U ||
        saved.width == 0U || saved.width > YB_Y416_MAX_DIMENSION ||
        saved.height == 0U || saved.height > YB_Y416_MAX_DIMENSION)
        return YB_Y416_BAD_SURFACE;
    row_bytes = saved.width * 8U;
    if (saved.stride < row_bytes || saved.stride > (uint64_t)SIZE_MAX ||
        saved.bytes > (uint64_t)SIZE_MAX)
        return YB_Y416_BAD_SURFACE;
    if (saved.height > 1U && saved.stride > (UINT64_MAX - row_bytes) / (saved.height - 1U))
        return YB_Y416_BAD_SURFACE;
    footprint = (saved.height - 1U) * saved.stride + row_bytes;
    if (saved.bytes < footprint || !make_span(saved.data, saved.bytes, &source_span))
        return YB_Y416_BAD_SURFACE;
    if (row_count == 0U || first_row >= saved.height || row_count > saved.height - first_row ||
        row_count > YB_Y416_MAX_SAMPLES / saved.width)
        return YB_Y416_BAD_REGION;
    expected = row_count * saved.width;
    if (output_samples != expected)
        return YB_Y416_BAD_OUTPUT;
    for (size_t index = 0U; index < 4U; ++index) {
        if ((uintptr_t)planes[index] % _Alignof(uint16_t) != 0U ||
            !make_span(planes[index], expected * 2U, &outputs[index]))
            return YB_Y416_BAD_OUTPUT;
        if (overlaps(outputs[index], source_span) || overlaps(outputs[index], descriptor_span))
            return YB_Y416_ALIAS;
        for (size_t previous = 0U; previous < index; ++previous)
            if (overlaps(outputs[index], outputs[previous]))
                return YB_Y416_ALIAS;
    }
    for (uint64_t row = 0U; row < row_count; ++row) {
        const uint8_t *source = saved.data + (size_t)((first_row + row) * saved.stride);
        for (uint64_t column = 0U; column < saved.width; ++column) {
            uint64_t output = row * saved.width + column;
            for (size_t channel = 0U; channel < 4U; ++channel)
                planes[channel][(size_t)output] = load_le16(source + (size_t)(column * 8U) + channel * 2U);
        }
    }
    return YB_Y416_OK;
}
