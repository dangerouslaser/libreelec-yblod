#ifndef YB_NATIVE_DECODER_FRAME_BRIDGE_H
#define YB_NATIVE_DECODER_FRAME_BRIDGE_H
#include "native_dovi_adapter.h"
#include "native_integration_probe.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Offline same-build blob boundary, not a portable serialization or parser.
 * Caller independently pins producer/source/library/blob identities. No JSON
 * mapping or NLQ configuration is accepted by this interface. */
uint32_t yb_decoder_frame_bridge_abi_version(void);
uint64_t yb_decoder_frame_bridge_sizeof_instructions(void);
int yb_decoder_frame_bridge_init(yb_integration_context *context,
    const yb_integration_descriptor *descriptor, const void *blob, size_t bytes);
#ifdef __cplusplus
}
#endif
#endif
