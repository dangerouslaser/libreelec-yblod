#include "native_integration_probe.h"
#include <stddef.h>
#include <string.h>

#define YB_CONTEXT_MAGIC UINT32_C(0x59424931)

uint32_t yb_integration_abi_version(void) { return 1; }
uint64_t yb_integration_sizeof_descriptor(void)
{
    return sizeof(yb_integration_descriptor);
}
uint64_t yb_integration_sizeof_context(void)
{
    return sizeof(yb_integration_context);
}
uint64_t yb_integration_sizeof_completion(void)
{
    return sizeof(yb_integration_completion);
}
uint64_t yb_integration_sizeof_sampling_contract(void)
{
    return sizeof(yb_sampling_contract);
}

static int span_valid(const void *pointer,uint64_t bytes)
{
    return pointer != NULL && bytes <= UINTPTR_MAX-(uintptr_t)pointer;
}

static int aligned(const void *pointer,size_t alignment)
{
    return pointer != NULL && (uintptr_t)pointer % alignment == 0;
}

static int overlap(const void *a,uint64_t a_bytes,const void *b,uint64_t b_bytes)
{
    uintptr_t aa=(uintptr_t)a, bb=(uintptr_t)b;
    if (a == NULL || b == NULL || a_bytes > UINTPTR_MAX-aa ||
        b_bytes > UINTPTR_MAX-bb) {
        return 1;
    }
    return aa < bb+b_bytes && bb < aa+a_bytes;
}

static int ready(const yb_integration_context *context)
{
    if (!aligned(context,_Alignof(yb_integration_context)) ||
        !span_valid(context,sizeof(*context)) ||
        context->initialized != YB_CONTEXT_MAGIC) {
        return YB_INTEGRATION_INVALID;
    }
    return context->finalized ? YB_INTEGRATION_FINALIZED : YB_INTEGRATION_OK;
}

static int association(const yb_integration_context *context,const uint8_t *id)
{
    return span_valid(id,32) && memcmp(context->descriptor.frame_id,id,32) == 0;
}

int yb_integration_init(yb_integration_context *context,
                        const yb_integration_descriptor *descriptor,
                        const struct yb_mapping_config *map,
                        const struct yb_nlq_config *nlq,
                        const yb_sampling_contract *sampling)
{
    yb_integration_context candidate;
    uint32_t i;
    if (!aligned(context,_Alignof(yb_integration_context)) ||
        !aligned(descriptor,_Alignof(yb_integration_descriptor)) ||
        overlap(context,sizeof(*context),descriptor,sizeof(*descriptor)) ||
        descriptor->version != 1 || descriptor->width == 0 ||
        descriptor->height == 0 || descriptor->width > 8192 ||
        descriptor->height > 8192) {
        return YB_INTEGRATION_INVALID;
    }
    memset(&candidate,0,sizeof(candidate));
    candidate.descriptor=*descriptor;
    if (descriptor->input_kind == YB_INPUT_WHOLE_CODES) {
        if ((descriptor->width % 2) != 0 || (descriptor->height % 2) != 0 ||
            (descriptor->output_depth != 10 && descriptor->output_depth != 12) ||
            (descriptor->enhancement_enabled != 0 &&
             descriptor->enhancement_enabled != 1) || sampling != NULL ||
            !aligned(map,_Alignof(struct yb_mapping_config)) ||
            overlap(context,sizeof(*context),map,sizeof(*map)) ||
            yb_validate_mapping(map) != YB_OK) {
            return YB_INTEGRATION_INVALID;
        }
        candidate.mapping=*map;
        if (descriptor->enhancement_enabled) {
            if (!aligned(nlq,_Alignof(struct yb_nlq_config)) ||
                overlap(context,sizeof(*context),nlq,3*sizeof(*nlq))) {
                return YB_INTEGRATION_INVALID;
            }
            for (i=0;i<3;++i) {
                if (yb_validate_nlq(&nlq[i]) != YB_OK ||
                    nlq[i].denominator != map->denominator ||
                    nlq[i].bit_depth != nlq[0].bit_depth) {
                    return YB_INTEGRATION_INVALID;
                }
                candidate.nlq[i]=nlq[i];
            }
        } else if (nlq != NULL) {
            return YB_INTEGRATION_INVALID;
        }
    } else if (descriptor->input_kind == YB_INPUT_RAW_DIAGNOSTIC) {
        /* Exercise the sampler's existing complete contract validator without
         * inventing a parallel list of allowed coordinate/precision values. */
        uint16_t dummy=0;
        yb_sampling_plane plane={&dummy,1,1,1,1};
        yb_sampling_contract checked;
        yb_sampling_query query={0,0};
        yb_sampling_result result;
        if (map != NULL || nlq != NULL || descriptor->output_depth != 0 ||
            descriptor->enhancement_enabled != 0 ||
            !aligned(sampling,_Alignof(yb_sampling_contract)) ||
            overlap(context,sizeof(*context),sampling,sizeof(*sampling)) ||
            sampling->width != descriptor->width ||
            sampling->height != descriptor->height) {
            return YB_INTEGRATION_INVALID;
        }
        checked=*sampling;
        checked.width=1;
        checked.height=1;
        if (checked.method != 1 && checked.method != 2) {
            return YB_INTEGRATION_INVALID;
        }
        /* Integer-point integrality is query-specific, not an init rule. */
        checked.method=2;
        if (yb_sampling_probe(&plane,&checked,&query,1,&result,1) !=
            YB_SAMPLING_OK) {
            return YB_INTEGRATION_INVALID;
        }
        candidate.sampling=*sampling;
    } else {
        return YB_INTEGRATION_ROUTE;
    }
    candidate.initialized=YB_CONTEXT_MAGIC;
    *context=candidate;
    return YB_INTEGRATION_OK;
}

int yb_integration_integer(yb_integration_context *context,const uint8_t id[32],
                          int32_t component,uint64_t start,const uint16_t *y,
                          const uint16_t *cb,const uint16_t *cr,const uint16_t *el,
                          uint32_t count,uint16_t *mapped,int32_t *residual,
                          int32_t *sum,uint16_t *reconstructed)
{
    uint64_t total;
    int status=ready(context);
    if (status != YB_INTEGRATION_OK) {
        return status;
    }
    if (!association(context,id)) {
        return YB_INTEGRATION_ASSOCIATION;
    }
    if (context->descriptor.input_kind != YB_INPUT_WHOLE_CODES) {
        return YB_INTEGRATION_FRACTIONAL_POLICY_REQUIRED;
    }
    if (component < 0 || component > 2 || count == 0 || count > 65536) {
        return YB_INTEGRATION_INVALID;
    }
    total=(uint64_t)context->descriptor.width*context->descriptor.height;
    if (component != 0) {
        total/=4;
    }
    if (start != context->consumed[component] || start > total ||
        count > total-start) {
        return YB_INTEGRATION_COUNTS;
    }
    if (overlap(mapped,(uint64_t)count*2,context,sizeof(*context)) ||
        overlap(residual,(uint64_t)count*4,context,sizeof(*context)) ||
        overlap(sum,(uint64_t)count*4,context,sizeof(*context)) ||
        overlap(reconstructed,(uint64_t)count*2,context,sizeof(*context)) ||
        overlap(mapped,(uint64_t)count*2,id,32) ||
        overlap(residual,(uint64_t)count*4,id,32) ||
        overlap(sum,(uint64_t)count*4,id,32) ||
        overlap(reconstructed,(uint64_t)count*2,id,32)) {
        return YB_INTEGRATION_ALIAS;
    }
    if (overlap(y,(uint64_t)count*2,context,sizeof(*context)) ||
        overlap(cb,(uint64_t)count*2,context,sizeof(*context)) ||
        overlap(cr,(uint64_t)count*2,context,sizeof(*context)) ||
        (el != NULL && overlap(el,(uint64_t)count*2,context,sizeof(*context)))) {
        return YB_INTEGRATION_ALIAS;
    }
    status=yb_process_chunk(&context->mapping,
        context->descriptor.enhancement_enabled ? &context->nlq[component] : NULL,
        component,y,cb,cr,el,count,context->descriptor.enhancement_enabled,
        context->descriptor.output_depth,mapped,residual,sum,reconstructed);
    if (status != YB_OK) {
        return YB_INTEGRATION_STAGE;
    }
    context->consumed[component]+=count;
    return YB_INTEGRATION_OK;
}

int yb_integration_raw(yb_integration_context *context,const uint8_t id[32],
                      const yb_sampling_plane *plane,
                      const yb_sampling_query *queries,uint64_t count,
                      yb_sampling_result *results)
{
    int status=ready(context);
    if (status != YB_INTEGRATION_OK) {
        return status;
    }
    if (!association(context,id)) {
        return YB_INTEGRATION_ASSOCIATION;
    }
    if (context->descriptor.input_kind != YB_INPUT_RAW_DIAGNOSTIC) {
        return YB_INTEGRATION_ROUTE;
    }
    if (count == 0 || count > 65536 ||
        context->diagnostic_queries > UINT64_MAX-count) {
        return YB_INTEGRATION_COUNTS;
    }
    if (overlap(results,count*sizeof(*results),context,sizeof(*context)) ||
        overlap(results,count*sizeof(*results),id,32)) {
        return YB_INTEGRATION_ALIAS;
    }
    if (!aligned(plane,_Alignof(yb_sampling_plane)) ||
        !aligned(queries,_Alignof(yb_sampling_query)) ||
        !span_valid(plane,sizeof(*plane)) ||
        overlap(plane,sizeof(*plane),context,sizeof(*context)) ||
        plane->samples > UINT64_MAX/2 ||
        overlap(plane->data,plane->samples*2,context,sizeof(*context)) ||
        overlap(queries,count*sizeof(*queries),context,sizeof(*context))) {
        return YB_INTEGRATION_ALIAS;
    }
    status=yb_sampling_probe(plane,&context->sampling,queries,count,results,count);
    if (status != YB_SAMPLING_OK) {
        return YB_INTEGRATION_STAGE;
    }
    context->diagnostic_queries+=count;
    return YB_INTEGRATION_OK;
}

int yb_integration_finish(yb_integration_context *context,
                        yb_integration_completion *completion)
{
    yb_integration_completion candidate;
    uint64_t total;
    int status=ready(context);
    if (status != YB_INTEGRATION_OK) {
        return status;
    }
    if (!aligned(completion,_Alignof(yb_integration_completion)) ||
        overlap(completion,sizeof(*completion),context,sizeof(*context))) {
        return YB_INTEGRATION_ALIAS;
    }
    memset(&candidate,0,sizeof(candidate));
    if (context->descriptor.input_kind == YB_INPUT_WHOLE_CODES) {
        total=(uint64_t)context->descriptor.width*context->descriptor.height;
        if (context->consumed[0] != total || context->consumed[1] != total/4 ||
            context->consumed[2] != total/4) {
            return YB_INTEGRATION_COUNTS;
        }
        candidate.kind=YB_ARITHMETIC_FRAME_COMPLETE;
        memcpy(candidate.counts,context->consumed,sizeof(candidate.counts));
    } else if (context->descriptor.input_kind == YB_INPUT_RAW_DIAGNOSTIC) {
        if (context->diagnostic_queries == 0) {
            return YB_INTEGRATION_COUNTS;
        }
        candidate.kind=YB_DIAGNOSTIC_SESSION_COMPLETE;
        candidate.diagnostic_queries=context->diagnostic_queries;
    } else {
        return YB_INTEGRATION_ROUTE;
    }
    *completion=candidate;
    context->finalized=1;
    return YB_INTEGRATION_OK;
}

void yb_integration_reset(yb_integration_context *context)
{
    if (aligned(context,_Alignof(yb_integration_context)) &&
        span_valid(context,sizeof(*context))) {
        memset(context,0,sizeof(*context));
    }
}
