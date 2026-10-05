#include "native_dovi_adapter.h"
#include <libavutil/dovi_meta.h>
#include <limits.h>
#include <string.h>

typedef struct { size_t offset, length; } region;

static int address_valid(const void *pointer, size_t bytes, size_t alignment)
{
    return pointer != NULL && (uintptr_t)pointer % alignment == 0U &&
           bytes <= UINTPTR_MAX - (uintptr_t)pointer;
}

static int intersects(uintptr_t a, size_t a_bytes, uintptr_t b, size_t b_bytes)
{
    return a_bytes != 0U && b_bytes != 0U && a < b + b_bytes && b < a + a_bytes;
}

static int region_valid(region r, size_t bytes, uintptr_t base, size_t alignment)
{
    return r.offset >= sizeof(AVDOVIMetadata) && r.offset <= bytes &&
           r.length <= bytes-r.offset && (base+r.offset) % alignment == 0U;
}

static int layout_valid(const void *data, size_t bytes)
{
    const AVDOVIMetadata *metadata = data;
    region regions[4];
    size_t count;
    if (metadata->num_ext_blocks < 0 || metadata->num_ext_blocks > AV_DOVI_MAX_EXT_BLOCKS ||
        metadata->ext_block_size < sizeof(AVDOVIDmData) ||
        metadata->ext_block_size % _Alignof(AVDOVIDmData) != 0U) {
        return 0;
    }
    count = (size_t)metadata->num_ext_blocks;
    if (count != 0U && metadata->ext_block_size > SIZE_MAX/count) {
        return 0;
    }
    regions[0] = (region){metadata->header_offset, sizeof(AVDOVIRpuDataHeader)};
    regions[1] = (region){metadata->mapping_offset, sizeof(AVDOVIDataMapping)};
    regions[2] = (region){metadata->color_offset, sizeof(AVDOVIColorMetadata)};
    regions[3] = (region){metadata->ext_block_offset, count*metadata->ext_block_size};
    const size_t alignments[4] = {_Alignof(AVDOVIRpuDataHeader), _Alignof(AVDOVIDataMapping),
                                _Alignof(AVDOVIColorMetadata), _Alignof(AVDOVIDmData)};
    for (unsigned i=0; i<4U; ++i) {
        if (!region_valid(regions[i], bytes, (uintptr_t)data, alignments[i])) {
            return 0;
        }
        for (unsigned j=0; j<i; ++j) {
            if (intersects((uintptr_t)data+regions[i].offset, regions[i].length,
                           (uintptr_t)data+regions[j].offset, regions[j].length)) {
                return 0;
            }
        }
    }
    return 1;
}

uint32_t yb_dovi_adapter_abi_version(void) { return 1U; }
uint64_t yb_dovi_adapter_sizeof_instructions(void)
{
    return (uint64_t)sizeof(yb_dovi_integer_instructions);
}

int yb_dovi_to_integer_configs(const void *data, size_t bytes,
                               yb_dovi_integer_instructions *output)
{
    yb_dovi_integer_instructions candidate;
    if (bytes < sizeof(AVDOVIMetadata) || bytes > 1024U*1024U ||
        !address_valid(data, bytes, _Alignof(AVDOVIMetadata)) ||
        !address_valid(output, sizeof(*output), _Alignof(yb_dovi_integer_instructions))) {
        return YB_DOVI_ADAPTER_ARGUMENT;
    }
    if (intersects((uintptr_t)data, bytes, (uintptr_t)output, sizeof(*output))) {
        return YB_DOVI_ADAPTER_ALIAS;
    }
    if (!layout_valid(data, bytes)) {
        return YB_DOVI_ADAPTER_LAYOUT;
    }
    const AVDOVIMetadata *metadata = data;
    const AVDOVIRpuDataHeader *header = av_dovi_get_header(metadata);
    const AVDOVIDataMapping *mapping = av_dovi_get_mapping(metadata);
    if (header->rpu_type != 2U || header->rpu_format != 18U ||
        header->coef_data_type != 0U || header->vdr_rpu_normalized_idc != 1U ||
        header->ext_mapping_idc_0_4 != 0U || header->ext_mapping_idc_5_7 != 0U ||
        (header->bl_bit_depth != 8U && header->bl_bit_depth != 10U) ||
        (header->el_bit_depth != 8U && header->el_bit_depth != 10U) ||
        (header->vdr_bit_depth != 10U && header->vdr_bit_depth != 12U) ||
        header->coef_log2_denom < 13U || header->coef_log2_denom > 32U ||
        (header->disable_residual_flag == 0U && header->coef_log2_denom < header->el_bit_depth+5U) ||
        header->disable_residual_flag > 1U || header->bl_video_full_range_flag > 1U ||
        header->spatial_resampling_filter_flag > 1U || header->el_spatial_resampling_filter_flag > 1U ||
        header->chroma_resampling_explicit_filter_flag > 1U ||
        header->vdr_rpu_profile > 15U || header->vdr_rpu_level > 15U) {
        return YB_DOVI_ADAPTER_UNSUPPORTED_HEADER;
    }
    if (header->chroma_resampling_explicit_filter_flag != 0U) {
        return YB_DOVI_ADAPTER_UNSUPPORTED_PREPARATION;
    }
    if (mapping->mapping_color_space != 0U || mapping->mapping_chroma_format_idc != 0U ||
        mapping->num_x_partitions != 1U || mapping->num_y_partitions != 1U) {
        return YB_DOVI_ADAPTER_UNSUPPORTED_MAPPING;
    }
    memset(&candidate, 0, sizeof(candidate));
    candidate.version = 1U;
    candidate.residual_enabled = header->disable_residual_flag == 0U ? 1 : 0;
    candidate.output_depth = header->vdr_bit_depth;
    candidate.spatial_resampling_filter_flag = header->spatial_resampling_filter_flag;
    candidate.el_spatial_resampling_filter_flag = header->el_spatial_resampling_filter_flag;
    candidate.chroma_resampling_explicit_filter_flag = header->chroma_resampling_explicit_filter_flag;
    candidate.bl_video_full_range_flag = header->bl_video_full_range_flag;
    candidate.source_rpu_profile = header->vdr_rpu_profile;
    candidate.source_rpu_level = header->vdr_rpu_level;
    candidate.mapping.bit_depth = header->bl_bit_depth;
    candidate.mapping.denominator = header->coef_log2_denom;
    for (unsigned component=0; component<3U; ++component) {
        const AVDOVIReshapingCurve *source = &mapping->curves[component];
        struct yb_component_mapping *target = &candidate.mapping.components[component];
        if (source->num_pivots < 2U || source->num_pivots > AV_DOVI_MAX_PIECES+1U ||
            source->num_pivots > YB_MAX_PIVOTS) {
            return YB_DOVI_ADAPTER_UNSUPPORTED_MAPPING;
        }
        target->pivot_count = source->num_pivots;
        for (unsigned i=0; i<source->num_pivots; ++i) {
            target->pivots[i] = source->pivots[i];
        }
        for (unsigned i=0; i+1U<source->num_pivots; ++i) {
            struct yb_segment *segment = &target->segments[i];
            if (source->mapping_idc[i] == AV_DOVI_MAPPING_POLYNOMIAL) {
                if (source->poly_order[i] < 1U || source->poly_order[i] > 2U) {
                    return YB_DOVI_ADAPTER_UNSUPPORTED_MAPPING;
                }
                segment->method = YB_POLYNOMIAL;
                segment->order = source->poly_order[i];
                for (unsigned k=0; k<=source->poly_order[i]; ++k) {
                    segment->coefficients[0][k] = source->poly_coef[i][k];
                }
            } else if (source->mapping_idc[i] == AV_DOVI_MAPPING_MMR && component != 0U) {
                if (source->mmr_order[i] < 1U || source->mmr_order[i] > 3U) {
                    return YB_DOVI_ADAPTER_UNSUPPORTED_MAPPING;
                }
                segment->method = YB_MMR;
                segment->order = source->mmr_order[i];
                segment->constant = source->mmr_constant[i];
                for (unsigned order=0; order<source->mmr_order[i]; ++order) {
                    for (unsigned term=0; term<7U; ++term) {
                        segment->coefficients[order][term] = source->mmr_coef[i][order][term];
                    }
                }
            } else {
                return YB_DOVI_ADAPTER_UNSUPPORTED_MAPPING;
            }
        }
    }
    if (yb_validate_mapping(&candidate.mapping) != YB_OK) {
        return YB_DOVI_ADAPTER_UNSUPPORTED_MAPPING;
    }
    if (candidate.residual_enabled) {
        if (mapping->nlq_method_idc != AV_DOVI_NLQ_LINEAR_DZ || mapping->nlq_pivots[0] != 0U ||
            mapping->nlq_pivots[1] != (1U<<header->el_bit_depth)-1U) {
            return YB_DOVI_ADAPTER_UNSUPPORTED_NLQ;
        }
        for (unsigned component=0; component<3U; ++component) {
            const AVDOVINLQParams *source = &mapping->nlq[component];
            struct yb_nlq_config *target = &candidate.nlq[component];
            target->bit_depth = header->el_bit_depth;
            target->denominator = header->coef_log2_denom;
            target->offset = source->nlq_offset;
            target->slope = source->linear_deadzone_slope;
            target->threshold = source->linear_deadzone_threshold;
            target->maximum = source->vdr_in_max;
            if (yb_validate_nlq(target) != YB_OK) {
                return YB_DOVI_ADAPTER_UNSUPPORTED_NLQ;
            }
        }
    }
    memcpy(output, &candidate, sizeof(candidate));
    return YB_DOVI_ADAPTER_OK;
}
