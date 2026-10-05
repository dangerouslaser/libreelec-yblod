/* Synthetic host-only exercise of the EXISTING pinned tunnel serializer.
 * Compile against the real patched dvbridge/FFmpeg headers and libavutil.
 * No reconstructed media, GL/EGL, DRM, HDMI or display operation.
 */
#include "dvbridge_metadata.h"
#include <libavutil/mem.h>

static void word_bits(uint8_t *bytes, unsigned *position, unsigned value,
                      unsigned width)
{
    for (unsigned bit = width; bit > 0U; --bit) {
        unsigned at = (*position)++;
        bytes[at / 8U] |= (uint8_t)(((value >> (bit - 1U)) & 1U) << (7U - at % 8U));
    }
}

static int populate(AVDOVIMetadata *metadata, size_t bytes, const char *name)
{
    AVDOVIRpuDataHeader *header = av_dovi_get_header(metadata);
    AVDOVIColorMetadata *color = av_dovi_get_color(metadata);
    header->disable_residual_flag = 1; /* no media/EL certification is inferred */
    color->signal_eotf = 65535;
    color->signal_color_space = 0;
    color->source_min_pq = 0;
    color->source_max_pq = 4000;
    color->scene_refresh_flag = 0;
    metadata->num_ext_blocks = 2;
    if (!dvbridge_dv_bounds(metadata, bytes))
        return 0;
    AVDOVIDmData *l1 = av_dovi_get_ext(metadata, 0);
    AVDOVIDmData *l5 = av_dovi_get_ext(metadata, 1);
    l1->level = 1;
    l1->l1.min_pq = 0;
    l1->l1.max_pq = 3000;
    l1->l1.avg_pq = strcmp(name, "l1-changed") == 0 ? 513 : 512;
    l5->level = 5; /* zero margins in full-raster synthetic geometry */
    if (strcmp(name, "l2-added") == 0 || strcmp(name, "l2-changed") == 0 ||
        strcmp(name, "l8-added") == 0 || strcmp(name, "l8-changed") == 0 ||
        strcmp(name, "invalid-duplicate-l1") == 0) {
        metadata->num_ext_blocks = 3;
        if (!dvbridge_dv_bounds(metadata, bytes))
            return 0;
        AVDOVIDmData *extra = av_dovi_get_ext(metadata, 2);
        if (strcmp(name, "invalid-duplicate-l1") == 0) {
            *extra = *l1;
        } else if (name[1] == '2') {
            extra->level = 2;
            extra->l2.target_max_pq = 2500;
            extra->l2.trim_slope = strcmp(name, "l2-changed") == 0 ? 2049 : 2048;
            extra->l2.trim_offset = 2048;
            extra->l2.trim_power = 2048;
            extra->l2.trim_chroma_weight = 2048;
            extra->l2.trim_saturation_gain = 2048;
            extra->l2.ms_weight = -1;
        } else {
            extra->level = 8;
            extra->dvbridge_raw_magic = 0x41424456U;
            extra->dvbridge_original_length = 10;
            unsigned position = 0;
            word_bits(extra->dvbridge_original_bytes, &position, 1, 8);
            for (unsigned control = 0; control < 6; ++control)
                word_bits(extra->dvbridge_original_bytes, &position,
                    control == 0U && strcmp(name, "l8-changed") == 0 ? 2049U : 2048U, 12);
        }
    }
    return 1;
}

static void hex_payload(const uint8_t *data, unsigned size)
{
    putchar('"');
    for (unsigned index = 0; index < size; ++index)
        printf("%02x", data[index]);
    putchar('"');
}

static int emit(struct dvbridge_dv *committed, const AVDOVIMetadata *metadata,
                double pts, int initial)
{
    struct dvbridge_dv before, candidate;
    memcpy(&before, committed, sizeof(before));
    memcpy(&candidate, committed, sizeof(candidate));
    bool accepted = dvbridge_dv_metadata(&candidate, metadata, pts);
    bool inner_changed = memcmp(&candidate, &before, sizeof(before)) != 0;
    if (accepted)
        memcpy(committed, &candidate, sizeof(candidate));
    printf("%s{\"accepted\":%s,\"committed\":%s,"
           "\"failure_preserved_outer_state\":%s,\"inner_mutated_on_failure\":%s,"
           "\"frames\":%llu,\"changes\":%llu,\"packet_count\":%u,\"payload_hex\":",
           initial ? "" : ",", accepted ? "true" : "false",
           accepted ? "true" : "false",
           !accepted && memcmp(committed, &before, sizeof(before)) == 0 ? "true" : "false",
           !accepted && inner_changed ? "true" : "false",
           (unsigned long long)committed->frames, (unsigned long long)committed->changes,
           accepted ? committed->count : 0U);
    hex_payload(candidate.payload, accepted ? candidate.size : 0U);
    printf(",\"packet_hex\":\"");
    if (accepted)
        for (unsigned index = 0; index < candidate.count * 128U; ++index)
            printf("%02x", (unsigned)candidate.packets[index]);
    printf("\"}");
    return accepted ? 1 : 0;
}

int main(int argc, char **argv)
{
    static const char *names[] = {"baseline", "l1-changed", "l2-added", "l2-changed",
        "l8-added", "l8-changed", "repeat", "seek", "invalid-duplicate-l1"};
    int known = 0;
    if (argc != 2)
        return 2;
    for (unsigned index = 0; index < sizeof(names) / sizeof(names[0]); ++index)
        known |= strcmp(argv[1], names[index]) == 0;
    if (!known)
        return 2;
    size_t bytes = 0;
    AVDOVIMetadata *metadata = av_dovi_metadata_alloc(&bytes);
    if (!metadata)
        return 2;
    const char *name = argv[1];
    struct dvbridge_dv state = {0};
    if (!dvbridge_dv_geometry(&state, 3840, 2160, 0, 0, 3840, 2160) ||
        !populate(metadata, bytes, name)) {
        av_free(metadata);
        return 2;
    }
    printf("{\"schema\":\"yblod.native-metadata-probe.v1\","
           "\"synthetic_only\":true,\"case\":\"%s\",\"records\":[", name);
    int result = emit(&state, metadata, 1.0, 1);
    if (strcmp(name, "repeat") == 0 || strcmp(name, "seek") == 0) {
        result &= emit(&state, metadata, 1.0, 0);
        result &= emit(&state, metadata, strcmp(name, "repeat") == 0 ? 1.02 : 0.8, 0);
    }
    printf("]}\n");
    av_free(metadata);
    return result ? 0 : 3; /* valid synthetic case deliberately rejected */
}
