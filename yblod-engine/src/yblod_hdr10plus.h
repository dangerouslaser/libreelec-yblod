/* YBLOD 0.4.0: HDR10+ for the Vulkan engine (yblod_hdr10plus.c). The engine's
 * C API (vk/include/dv_engine_vk.h dvvk_hdr10plus_packet with dvvk_hdr10plus_metadata,
 * dvvk_hdr10plus_to_dovi, dvvk_hdr10_to_dovi) wraps these.
 * SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef YBLOD_HDR10PLUS_H
#define YBLOD_HDR10PLUS_H
#include <stddef.h>
#include <stdint.h>
#include "dv_engine_vk.h"
#include "cb1_hdr10plus_analysis.h"

/* The engine's statistics record (shaders/pack.comp STATS): histogram[256]
 * (16 nits a bin), each channel's maximum as PQ float bits [256..258], the
 * sum of maxRGB light in 1/64 nit [259] low, [260] high, the count [261]. */
#define YB_HDR10PLUS_STATS_WORDS 262
int yb_hdr10plus_statistics(const uint32_t words[YB_HDR10PLUS_STATS_WORDS], struct cb1_hdr10plus_statistics *out);
int yb_hdr10plus_packet(const void *metadata, size_t bytes, const uint32_t words[YB_HDR10PLUS_STATS_WORDS],
                        uint32_t flags, int overlay, dvvk_hdr10plus_metadata *out);
int yb_hdr10plus_to_dovi(const void *hdr10plus, size_t size, const dvvk_hdr10_static *hdr10, const void *previous,
                         void *out, size_t capacity, size_t *out_size, dvvk_hdr10plus_dovi_info *info);
int yb_hdr10_to_dovi(const dvvk_hdr10_static *hdr10, void *out, size_t capacity, size_t *out_size);
#endif
