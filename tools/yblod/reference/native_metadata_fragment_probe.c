/* CPU-only synthetic fragmentation of the existing pinned serializer.
 * Use ACTUAL patched dvbridge/FFmpeg headers + matching libavutil allocator.
 * No ABI stand-ins, device calls or Dolby-conformance assertion.
 */
#include "dvbridge_metadata.h"
#include <libavutil/mem.h>
#include <stdio.h>
#include <string.h>

_Static_assert(AV_DOVI_MAX_EXT_BLOCKS >= 23, "fragment fixture needs 23 blocks");

static void bits(uint8_t *raw, unsigned *position, unsigned value, unsigned count)
{
    for (unsigned bit=count; bit>0; --bit) {
        unsigned at=(*position)++;
        raw[at/8] |= (uint8_t)(((value>>(bit-1))&1U)<<(7-at%8));
    }
}

static int populate(AVDOVIMetadata *metadata, size_t bytes,
                    unsigned l2_count, unsigned boundary)
{
    unsigned blocks=2+l2_count+(boundary ? 2 : 0);
    metadata->num_ext_blocks=(int)blocks;
    if (!dvbridge_dv_bounds(metadata,bytes))
        return 0;
    av_dovi_get_header(metadata)->disable_residual_flag=1;
    AVDOVIColorMetadata *color=av_dovi_get_color(metadata);
    color->signal_eotf=65535;
    color->signal_color_space=0;
    color->source_min_pq=0;
    color->source_max_pq=4000;
    color->scene_refresh_flag=0;
    for (unsigned i=0; i<blocks; ++i)
        memset(av_dovi_get_ext(metadata,(int)i),0,sizeof(AVDOVIDmData));
    AVDOVIDmData *l1=av_dovi_get_ext(metadata,0);
    l1->level=1;
    l1->l1.max_pq=3000;
    l1->l1.avg_pq=512;
    av_dovi_get_ext(metadata,1)->level=5;
    for (unsigned i=0; i<l2_count; ++i) {
        /* Deliberately descending targets: stable same-level order, not a
         * target sort. Input L5 precedes L2; level sort moves L2 before L5. */
        unsigned tag=l2_count-1-i;
        AVDOVIDmData *extra=av_dovi_get_ext(metadata,(int)(2+i));
        extra->level=2;
        extra->l2.target_max_pq=1000+tag;
        extra->l2.trim_slope=2048+tag;
        extra->l2.trim_offset=2048;
        extra->l2.trim_power=2048;
        extra->l2.trim_chroma_weight=2048;
        extra->l2.trim_saturation_gain=2048;
        extra->l2.ms_weight=-1;
    }
    if (boundary) {
        AVDOVIDmData *l8=av_dovi_get_ext(metadata,2);
        l8->level=8;
        l8->dvbridge_raw_magic=0x41424456U;
        l8->dvbridge_original_length=10;
        unsigned position=0;
        bits(l8->dvbridge_original_bytes,&position,1,8);
        for (unsigned i=0; i<6; ++i)
            bits(l8->dvbridge_original_bytes,&position,2048,12);
        AVDOVIDmData *extra=av_dovi_get_ext(metadata,3);
        extra->level=boundary == 119 ? 9 : 254;
        extra->dvbridge_raw_magic=0x41424456U;
        extra->dvbridge_original_length=boundary == 119 ? 1 : 2;
        /* L9 index0, or L254 two zero bytes: accepted converter grammar only. */
    }
    return 1;
}

static int emit(struct dvbridge_dv *committed, const AVDOVIMetadata *metadata,
                double pts, int first)
{
    struct dvbridge_dv before, candidate;
    memcpy(&before,committed,sizeof(before));
    memcpy(&candidate,committed,sizeof(candidate));
    bool accepted=dvbridge_dv_metadata(&candidate,metadata,pts);
    bool changed=memcmp(&candidate,&before,sizeof(before)) != 0;
    if (accepted)
        memcpy(committed,&candidate,sizeof(candidate));
    printf("%s{\"accepted\":%s,\"committed\":%s,"
           "\"failure_preserved_outer_state\":%s,\"inner_mutated_on_failure\":%s,"
           "\"frames\":%llu,\"changes\":%llu,\"packet_count\":%u,"
           "\"payload_hex\":\"",first ? "" : ",",
           accepted ? "true" : "false",accepted ? "true" : "false",
           !accepted && memcmp(committed,&before,sizeof(before)) == 0 ? "true" : "false",
           !accepted && changed ? "true" : "false",
           (unsigned long long)committed->frames,
           (unsigned long long)committed->changes,accepted ? candidate.count : 0U);
    if (accepted)
        for (unsigned i=0; i<candidate.size; ++i)
            printf("%02x",(unsigned)candidate.payload[i]);
    printf("\",\"packet_hex\":\"");
    if (accepted)
        for (unsigned i=0; i<candidate.count*128U; ++i)
            printf("%02x",(unsigned)candidate.packets[i]);
    printf("\"}");
    return accepted;
}

int main(int argc, char **argv)
{
    static const char *names[]={"baseline", "l2-2", "l2-8", "l2-15",
        "l2-20", "l2-21-reject", "boundary-119", "boundary-120"};
    static const unsigned counts[]={0,2,8,15,20,21,0,0};
    unsigned which=0;
    if (argc != 2)
        return 2;
    while (which < sizeof(names)/sizeof(names[0]) && strcmp(argv[1],names[which]))
        ++which;
    if (which == sizeof(names)/sizeof(names[0]))
        return 2;
    size_t bytes=0;
    AVDOVIMetadata *metadata=av_dovi_metadata_alloc(&bytes);
    struct dvbridge_dv state={0};
    if (!metadata || !dvbridge_dv_geometry(&state,3840,2160,0,0,3840,2160) ||
        !populate(metadata,bytes,0,0)) {
        av_free(metadata);
        return 2;
    }
    printf("{\"schema\":\"yblod.native-metadata-fragment-probe.v1\","
           "\"synthetic_only\":true,\"case\":\"%s\",\"records\":[",names[which]);
    int seeded=emit(&state,metadata,1.0,1);
    unsigned boundary=which == 6 ? 119 : which == 7 ? 120 : 0;
    if (!seeded || !populate(metadata,bytes,counts[which],boundary)) {
        av_free(metadata);
        return 2;
    }
    int accepted=emit(&state,metadata,1.02,0);
    printf("]}\n");
    av_free(metadata);
    return accepted ? 0 : 3;
}
