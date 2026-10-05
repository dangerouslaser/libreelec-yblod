#ifndef YB_NATIVE_Y416_H
#define YB_NATIVE_Y416_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* A borrowed, caller-owned coherent CPU byte surface, NOT a DMA-BUF/fence API.
 * Keep descriptor/input/output allocations alive and stable throughout the call.
 * LE U,Y,V,A 16bit words are the explicit supported packed layout. Q6/native10
 * is a DECLARED current Intel import-route convention, not universal Y416.
 * Colour words are returned unchanged; alpha has no Q6 interpretation here.
 * Required input footprint is (height-1)*stride + width*8, not stride*height.
 * Odd dimensions are allowed; this operation does not select a 420 grid.
 */
#define YB_Y416_LE_UYVA 1U
#define YB_Y416_MAX_DIMENSION 8192U
#define YB_Y416_MAX_SAMPLES 65536U

typedef struct {
    const uint8_t *data;
    uint64_t bytes;
    uint64_t width;
    uint64_t height;
    uint64_t stride;
    uint32_t layout;
    uint32_t storage_bits;
    uint32_t native_depth;
    uint32_t fractional_bits;
} yb_y416_surface;

enum {
    YB_Y416_OK = 0,
    YB_Y416_BAD_SURFACE = 1,
    YB_Y416_BAD_REGION = 2,
    YB_Y416_BAD_OUTPUT = 3,
    YB_Y416_ALIAS = 4
};

/* Exact output_samples == width*row_count; 1..65536 samples per output plane.
 * uint16 outputs must be aligned and disjoint from each other, descriptor, and
 * the entire declared source span (including padding). Byte input may be
 * unaligned. Every validation completes before any output write. All words,
 * including fractional low bits, overshoot and alpha, are copied losslessly.
 * Allocation accessibility/coherence cannot be proved from supplied addresses.
 * No normalization, truncation, clamp, rounding or chroma resampling occurs.
 */
int yb_y416_unpack_rows(const yb_y416_surface *surface,
                       uint64_t first_row, uint64_t row_count,
                       uint16_t *u, uint16_t *y, uint16_t *v, uint16_t *alpha,
                       uint64_t output_samples);
uint64_t yb_y416_sizeof_surface(void);
#ifdef __cplusplus
}
#endif
#endif
