#ifndef YB_NATIVE_SCALED_SURFACE_H
#define YB_NATIVE_SCALED_SURFACE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Borrowed coherent CPU-readable P010 allocation. Caller owns synchronization,
 * lifetime and immutability throughout each call. No device/fence ownership.
 * Tokens assert association; they do not authenticate it. Offsets/strides are
 * bytes; little-endian interleaved UV is Cb then Cr. Raw words preserve ALL
 * sixteen bits. Exact whole-code conversion is per selected chunk only, not
 * certification of a complete frame or fractional resampling policy.
 */
enum { YB_SURFACE_NATIVE10_Q6=1, YB_SURFACE_RAW_WORDS=1,
       YB_SURFACE_EXACT_WHOLE_CODES=2 };
enum { YB_SURFACE_OK=0, YB_SURFACE_INVALID=1, YB_SURFACE_ASSOCIATION=2,
       YB_SURFACE_ALIAS=3, YB_SURFACE_FRACTIONAL=4 };
typedef struct {
    uint32_t version, format, width, height;
    /* Must be 1: caller asserts mapping/readback is coherent and ready. This
     * flag does not wait for hardware or prove synchronization. */
    uint32_t coherent_ready;
    const uint8_t *allocation;
    uint64_t allocation_bytes, y_offset, uv_offset, y_stride, uv_stride;
    uint8_t frame_id[32], provenance_id[32];
} yb_scaled_surface;
uint32_t yb_scaled_surface_abi_version(void);
uint64_t yb_scaled_surface_sizeof_descriptor(void);
/* Components 0/1/2 mean Y/Cb/Cr; start counts active samples, skipping padding.
 * Count is 1..65536. Destination has count host-endian uint16_t entries.
 * Any failure leaves output unchanged. All input memory must be accessible;
 * declared lengths cannot prove actual allocation ownership. Output must not
 * overlap allocation, descriptor or expected tokens; token/descriptor alias is
 * also rejected. Complete planes must be present, disjoint and even-aligned.
 */
int yb_scaled_surface_extract(const yb_scaled_surface *,
    const uint8_t frame_id[32], const uint8_t provenance_id[32],
    uint32_t component, uint64_t start, uint32_t count, uint32_t mode,
    uint16_t *output);
#ifdef __cplusplus
}
#endif
#endif
