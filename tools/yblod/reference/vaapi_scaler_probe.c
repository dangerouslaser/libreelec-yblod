/* Standalone native-code P010 upload/readback and submitted VPP probe.
 * No Kodi, display-owned surfaces, RPU, RGB conversion or playback settings.
 * Build against the target libva SDK; see HARDWARE_SCALING.md.
 */
#define _POSIX_C_SOURCE 200809L
#include <va/va.h>
#include <va/va_drm.h>
#include <va/va_vpp.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "drm_engine_accounting.h"

static VADisplay display;
static int device_fd = -1, initialized;
static VAConfigID config = VA_INVALID_ID;
static VAContextID context = VA_INVALID_ID;
static VABufferID pipeline = VA_INVALID_ID;
static VASurfaceID surfaces[2] = {VA_INVALID_ID, VA_INVALID_ID};

/* Optional Linux DRM per-client accounting, not an SFC or algorithm proof.
 * The probe reads its own fd only; counters never include Kodi's client. */
static EngineSample engine_sample(void)
{
    EngineSample result = {0};
    char path[64], line[256];
    snprintf(path, sizeof(path), "/proc/self/fdinfo/%d", device_fd);
    FILE *file = fopen(path, "r");
    if (!file) return result;
    while (fgets(line, sizeof(line), file)) {
        if (!strchr(line, '\n') || !engine_parse_line(&result, line)) {
            memset(&result, 0, sizeof(result));
            break;
        }
    }
    if (ferror(file)) memset(&result, 0, sizeof(result));
    fclose(file);
    return result;
}

static void engine_json(EngineSample sample)
{
    printf("{\"client_id\":");
    if (sample.client_present) printf("%llu", sample.client_id);
    else printf("null");
    printf(",\"pci_device\":");
    if (*sample.pci_device) printf("\"%s\"", sample.pci_device);
    else printf("null");
    for (unsigned i = 0; i < 4; ++i) {
        printf(",\"%s\":", engine_names[i]);
        if (sample.present[i]) printf("%llu", sample.ns[i]);
        else printf("null");
    }
    putchar('}');
}

static void engine_delta_json(EngineSample before, EngineSample after)
{
    engine_json(engine_delta(before, after));
}

static void cleanup(void)
{
    if (initialized) {
        if (pipeline != VA_INVALID_ID) vaDestroyBuffer(display, pipeline);
        if (context != VA_INVALID_ID) vaDestroyContext(display, context);
        if (config != VA_INVALID_ID) vaDestroyConfig(display, config);
        for (unsigned i = 0; i < 2; ++i)
            if (surfaces[i] != VA_INVALID_ID) vaDestroySurfaces(display, &surfaces[i], 1);
        vaTerminate(display);
    }
    if (device_fd >= 0) close(device_fd);
}

static void fail(const char *message)
{
    fprintf(stderr, "probe failed: %s\n", message);
    exit(EXIT_FAILURE);
}

static void checked(VAStatus status, const char *name)
{
    fprintf(stderr, "api %s status=%d (%s)\n", name, status, vaErrorStr(status));
    if (status != VA_STATUS_SUCCESS) fail(name);
}
#define VA_CHECK(call) checked((call), #call)

static unsigned dimension(const char *text)
{
    char *end;
    errno = 0;
    unsigned long n = strtoul(text, &end, 10);
    if (errno || !*text || *end || n < 2 || n > 4096 || n % 2)
        fail("dimensions must be even integers in [2,4096]");
    return (unsigned)n;
}

static void json_string(const char *text)
{
    putchar('"');
    for (const unsigned char *s = (const unsigned char *)text; *s; ++s) {
        if (*s == '"' || *s == '\\') printf("\\%c", *s);
        else if (*s < 32) printf("\\u%04x", *s);
        else putchar(*s);
    }
    putchar('"');
}

static VAImage image_create(unsigned width, unsigned height, unsigned fourcc)
{
    int maximum = vaMaxNumImageFormats(display), count = 0, found = 0;
    if (maximum <= 0 || maximum > 4096) fail("invalid image format capacity");
    VAImageFormat *formats = calloc((size_t)maximum, sizeof(*formats));
    if (!formats) fail("image format allocation");
    VA_CHECK(vaQueryImageFormats(display, formats, &count));
    if (count < 0 || count > maximum) fail("invalid image format count");
    VAImageFormat selected = {0};
    for (int i = 0; i < count && i < maximum; ++i)
        if (formats[i].fourcc == fourcc) { selected = formats[i]; found = 1; break; }
    free(formats);
    if (!found) fail("requested image format unavailable; no substitute conversion");
    if (selected.byte_order != VA_LSB_FIRST) fail("requested image format is not little endian");
    unsigned planes = fourcc == VA_FOURCC_P010 ? 2 : 1;
    unsigned row_bytes = width * (fourcc == VA_FOURCC_P010 ? 2 : 8);
    VAImage image = {0};
    VA_CHECK(vaCreateImage(display, &selected, (int)width, (int)height, &image));
    if (image.format.fourcc != fourcc || image.format.byte_order != VA_LSB_FIRST || image.num_planes != planes
            || image.width != width || image.height != height)
        fail("unexpected image format or size");
    if (image.data_size > 128u * 1024u * 1024u) fail("image storage exceeds probe memory bound");
    uint64_t ends[2];
    for (unsigned p = 0; p < planes; ++p) {
        unsigned rows = p ? height / 2 : height;
        ends[p] = (uint64_t)image.offsets[p] + (uint64_t)(rows - 1) * image.pitches[p] + row_bytes;
        if (image.pitches[p] < row_bytes || ends[p] > image.data_size)
            fail("image stride/offset exceeds mapped storage");
    }
    if (planes == 2 && (uint64_t)image.offsets[0] < ends[1] && (uint64_t)image.offsets[1] < ends[0])
        fail("active Y/UV image storage spans overlap");
    fprintf(stderr, "image %ux%u size=%u pitches=%u,%u offsets=%u,%u\n",
            width, height, image.data_size, image.pitches[0], image.pitches[1],
            image.offsets[0], image.offsets[1]);
    return image;
}

static void upload(const unsigned char *packed, unsigned width, unsigned height)
{
    VAImage image = image_create(width, height, VA_FOURCC_P010);
    unsigned char *mapped;
    VA_CHECK(vaMapBuffer(display, image.buf, (void **)&mapped));
    if (!mapped) fail("null upload mapping");
    memset(mapped, 0, image.data_size);
    size_t cursor = 0;
    for (unsigned p = 0; p < 2; ++p)
        for (unsigned y = 0; y < (p ? height / 2 : height); ++y) {
            memcpy(mapped + image.offsets[p] + (size_t)y * image.pitches[p],
                    packed + cursor, width * 2);
            cursor += width * 2;
        }
    VA_CHECK(vaUnmapBuffer(display, image.buf));
    VA_CHECK(vaPutImage(display, surfaces[0], image.image_id, 0, 0, width, height,
                       0, 0, width, height));
    VA_CHECK(vaSyncSurface(display, surfaces[0]));
    VA_CHECK(vaDestroyImage(display, image.image_id));
}

static unsigned char *download(VASurfaceID surface, unsigned width, unsigned height, unsigned fourcc)
{
    VA_CHECK(vaSyncSurface(display, surface));
    VAImage image = image_create(width, height, fourcc);
    VA_CHECK(vaGetImage(display, surface, 0, 0, width, height, image.image_id));
    unsigned char *mapped;
    VA_CHECK(vaMapBuffer(display, image.buf, (void **)&mapped));
    if (!mapped) fail("null download mapping");
    unsigned planes = fourcc == VA_FOURCC_P010 ? 2 : 1;
    unsigned row_bytes = width * (fourcc == VA_FOURCC_P010 ? 2 : 8);
    size_t size = (size_t)width * height * (fourcc == VA_FOURCC_P010 ? 3 : 8), cursor = 0;
    unsigned char *packed = malloc(size);
    if (!packed) fail("download allocation");
    for (unsigned p = 0; p < planes; ++p)
        for (unsigned y = 0; y < (p ? height / 2 : height); ++y) {
            memcpy(packed + cursor, mapped + image.offsets[p] + (size_t)y * image.pitches[p], row_bytes);
            cursor += row_bytes;
        }
    VA_CHECK(vaUnmapBuffer(display, image.buf));
    VA_CHECK(vaDestroyImage(display, image.image_id));
    /* Preserve failures in raw output for diagnosis; do not drop precision. */
    for (size_t i = 0; fourcc == VA_FOURCC_P010 && i < size; i += 2)
        if (packed[i] & 63) { fprintf(stderr, "warning: downloaded P010 low bits are nonzero\n"); break; }
    return packed;
}

static void surface_create(unsigned width, unsigned height, unsigned index, unsigned fourcc, unsigned rt_format)
{
    VASurfaceAttrib attribute = {0};
    attribute.type = VASurfaceAttribPixelFormat;
    attribute.flags = VA_SURFACE_ATTRIB_SETTABLE;
    attribute.value.type = VAGenericValueTypeInteger;
    attribute.value.value.i = fourcc;
    VA_CHECK(vaCreateSurfaces(display, rt_format, width, height,
                             &surfaces[index], 1, &attribute, 1));
}

int main(int argc, char **argv)
{
    EngineSample before_vpp = {0}, after_vpp = {0};
    if (argc < 9 || (argc - 9) % 2) {
        fprintf(stderr, "usage: %s DEVICE INPUT OUTPUT IN_W IN_H OUT_W OUT_H copy|default|fast|hq|bilinear|nearest [--input-chroma left|top-left] [--output-chroma left|top-left|unspecified] [--pipeline default|fast] [--output-format p010|y416] [--range full|reduced] [--surface-contract advertised|allocation-diagnostic]\n", argv[0]);
        return EXIT_FAILURE;
    }
    unsigned input_chroma = VA_CHROMA_SITING_VERTICAL_CENTER | VA_CHROMA_SITING_HORIZONTAL_LEFT;
    unsigned output_chroma = input_chroma;
    unsigned pipeline_flags = 0, pipeline_caps_flags = 0;
    unsigned output_fourcc = VA_FOURCC_P010, output_rt = VA_RT_FORMAT_YUV420_10;
    unsigned colour_range = VA_SOURCE_RANGE_FULL;
    int seen_input = 0, seen_output = 0, seen_pipeline = 0, seen_format = 0, seen_range = 0;
    int seen_contract = 0, allocation_diagnostic = 0, surface_output = 0;
    for (int i = 9; i < argc; i += 2) {
        if (!strcmp(argv[i], "--surface-contract")) {
            if (seen_contract++) fail("duplicate surface contract option");
            if (!strcmp(argv[i + 1], "advertised")) allocation_diagnostic = 0;
            else if (!strcmp(argv[i + 1], "allocation-diagnostic")) allocation_diagnostic = 1;
            else fail("unknown surface contract request");
            continue;
        }
        if (!strcmp(argv[i], "--output-format")) {
            if (seen_format++) fail("duplicate output format option");
            if (!strcmp(argv[i + 1], "p010")) {
                output_fourcc = VA_FOURCC_P010; output_rt = VA_RT_FORMAT_YUV420_10;
            } else if (!strcmp(argv[i + 1], "y416")) {
                output_fourcc = VA_FOURCC_Y416; output_rt = VA_RT_FORMAT_YUV444_12;
            } else fail("unknown output format request");
            continue;
        }
        if (!strcmp(argv[i], "--range")) {
            if (seen_range++) fail("duplicate range option");
            if (!strcmp(argv[i + 1], "full")) colour_range = VA_SOURCE_RANGE_FULL;
            else if (!strcmp(argv[i + 1], "reduced")) colour_range = VA_SOURCE_RANGE_REDUCED;
            else fail("unknown range request");
            continue;
        }
        if (!strcmp(argv[i], "--pipeline")) {
            if (seen_pipeline++) fail("duplicate pipeline option");
            if (!strcmp(argv[i + 1], "default")) pipeline_flags = 0;
            else if (!strcmp(argv[i + 1], "fast")) pipeline_flags = VA_PROC_PIPELINE_FAST;
            else fail("unknown pipeline request");
            continue;
        }
        unsigned *value;
        int *seen;
        if (!strcmp(argv[i], "--input-chroma")) { value = &input_chroma; seen = &seen_input; }
        else if (!strcmp(argv[i], "--output-chroma")) { value = &output_chroma; seen = &seen_output; }
        else fail("unknown chroma option");
        if ((*seen)++) fail("duplicate chroma option");
        if (!strcmp(argv[i + 1], "left"))
            *value = VA_CHROMA_SITING_VERTICAL_CENTER | VA_CHROMA_SITING_HORIZONTAL_LEFT;
        else if (!strcmp(argv[i + 1], "top-left"))
            *value = VA_CHROMA_SITING_VERTICAL_TOP | VA_CHROMA_SITING_HORIZONTAL_LEFT;
        else if (value == &output_chroma && !strcmp(argv[i + 1], "unspecified"))
            *value = 0;
        else fail("unknown chroma location");
    }
    unsigned iw = dimension(argv[4]), ih = dimension(argv[5]);
    unsigned ow = dimension(argv[6]), oh = dimension(argv[7]);
    int copy = !strcmp(argv[8], "copy");
    if (copy && seen_contract) fail("copy test does not accept surface contract declarations");
    if (copy && output_fourcc != VA_FOURCC_P010) fail("copy test requires P010 output");
    if (copy && seen_range) fail("copy test does not accept range declarations");
    if (copy && seen_pipeline) fail("copy test does not accept pipeline declarations");
    if (copy && (seen_input || seen_output)) fail("copy test does not accept chroma declarations");
    unsigned flags = 0;
    if (!strcmp(argv[8], "fast")) flags = VA_FILTER_SCALING_FAST;
    else if (!strcmp(argv[8], "hq")) flags = VA_FILTER_SCALING_HQ;
    else if (!strcmp(argv[8], "bilinear")) flags = VA_FILTER_INTERPOLATION_BILINEAR;
    else if (!strcmp(argv[8], "nearest")) flags = VA_FILTER_INTERPOLATION_NEAREST_NEIGHBOR;
    else if (!copy && strcmp(argv[8], "default")) fail("unknown filter request");
    if (copy && (iw != ow || ih != oh)) fail("copy test requires identical dimensions");
    size_t input_size = (size_t)iw * ih * 3;
    unsigned char *input = malloc(input_size);
    if (!input) fail("input allocation");
    FILE *file = fopen(argv[2], "rb");
    if (!file) fail("open input");
    if (fread(input, 1, input_size, file) != input_size || fgetc(file) != EOF || ferror(file))
        fail("input must be exactly one tightly packed P010 frame");
    fclose(file);
    for (size_t i = 0; i < input_size; i += 2)
        if (input[i] & 63) fail("input P010 contains nonzero low six bits");
    device_fd = open(argv[1], O_RDWR | O_CLOEXEC);
    if (device_fd < 0) fail("open render device");
    atexit(cleanup);
    display = vaGetDisplayDRM(device_fd);
    if (!display) fail("DRM VA display unavailable");
    int major, minor;
    VA_CHECK(vaInitialize(display, &major, &minor));
    initialized = 1;
    surface_create(iw, ih, 0, VA_FOURCC_P010, VA_RT_FORMAT_YUV420_10);
    upload(input, iw, ih);
    free(input);
    if (!copy) {
        VAConfigAttrib attribute = {VAConfigAttribRTFormat, 0};
        VA_CHECK(vaGetConfigAttributes(display, VAProfileNone, VAEntrypointVideoProc, &attribute, 1));
        fprintf(stderr, "VideoProc generic RTFormat attribute=0x%08x\n", attribute.value);
        /* VideoProc generic RTFormat is not the decoder's bit-depth list.
         * Intel may omit YUV420_10 here while advertising P010 surfaces.
         * Default VideoProc config follows FFmpeg's VAAPI VPP setup. */
        VA_CHECK(vaCreateConfig(display, VAProfileNone, VAEntrypointVideoProc, NULL, 0, &config));
        unsigned count = 0;
        VA_CHECK(vaQuerySurfaceAttributes(display, config, NULL, &count));
        if (!count || count > 4096) fail("invalid surface capability count");
        unsigned capacity = count;
        VASurfaceAttrib *attributes = calloc(count, sizeof(*attributes));
        if (!attributes) fail("surface capability allocation");
        VA_CHECK(vaQuerySurfaceAttributes(display, config, attributes, &count));
        if (count > capacity) fail("surface capability count exceeds allocation");
        int surface_p010 = 0;
        for (unsigned i = 0; i < count; ++i)
            if (attributes[i].type == VASurfaceAttribPixelFormat
                    && attributes[i].value.type == VAGenericValueTypeInteger) {
                fprintf(stderr, "surface format fourcc=0x%08x flags=%u\n",
                        attributes[i].value.value.i, attributes[i].flags);
                surface_p010 |= attributes[i].value.value.i == VA_FOURCC_P010
                    && (attributes[i].flags & VA_SURFACE_ATTRIB_SETTABLE);
                surface_output |= (unsigned)attributes[i].value.value.i == output_fourcc
                    && (attributes[i].flags & VA_SURFACE_ATTRIB_SETTABLE);
            }
        free(attributes);
        if (!surface_p010) fail("P010 not advertised for VideoProc surfaces");
        if (!surface_output && !allocation_diagnostic)
            fail("requested output not advertised for VideoProc surfaces");
        if (!surface_output)
            fprintf(stderr, "diagnostic: exact unadvertised output allocation/submission; NOT backend qualification\n");
        surface_create(ow, oh, 1, output_fourcc, output_rt);
        VA_CHECK(vaCreateContext(display, config, (int)ow, (int)oh, VA_PROGRESSIVE,
                                &surfaces[1], 1, &context));
        VAProcColorStandardType input_standards_storage[64] = {0}, output_standards_storage[64] = {0};
        VAProcPipelineCaps caps = {0};
        caps.input_color_standards = input_standards_storage;
        caps.num_input_color_standards = 64;
        caps.output_color_standards = output_standards_storage;
        caps.num_output_color_standards = 64;
        VA_CHECK(vaQueryVideoProcPipelineCaps(display, context, NULL, 0, &caps));
        pipeline_caps_flags = caps.pipeline_flags;
        fprintf(stderr, "caps pipeline_flags=%u requested_pipeline_flags=%u\n",
                pipeline_caps_flags, pipeline_flags);
        if ((pipeline_flags & pipeline_caps_flags) != pipeline_flags)
            fail("requested pipeline hint not advertised; no substitute path");
        /* Supply colour buffers per API; Intel can replace their pointers with
         * driver-owned lists. Always read returned pointers; never free them.
         * Leave optional unreported pixel-format lists at NULL/0. */
        if (caps.num_input_pixel_formats > 64 || caps.num_output_pixel_formats > 64
                || caps.num_input_color_standards > 64 || caps.num_output_color_standards > 64)
            fail("pipeline capability list exceeds capacity");
        if ((caps.num_input_pixel_formats && !caps.input_pixel_format)
                || (caps.num_output_pixel_formats && !caps.output_pixel_format)
                || (caps.num_input_color_standards && !caps.input_color_standards)
                || (caps.num_output_color_standards && !caps.output_color_standards))
            fail("pipeline capability list has count without data");
        int input_p010 = 0, output_available = 0;
        for (unsigned i = 0; i < caps.num_input_pixel_formats; ++i) {
            fprintf(stderr, "input format fourcc=0x%08x\n", caps.input_pixel_format[i]);
            input_p010 |= caps.input_pixel_format[i] == VA_FOURCC_P010;
        }
        for (unsigned i = 0; i < caps.num_output_pixel_formats; ++i) {
            fprintf(stderr, "output format fourcc=0x%08x\n", caps.output_pixel_format[i]);
            output_available |= caps.output_pixel_format[i] == output_fourcc;
        }
        int input_bt2020 = 0, output_bt2020 = 0;
        for (unsigned i = 0; i < caps.num_input_color_standards; ++i) {
            fprintf(stderr, "input colour standard=%d\n", caps.input_color_standards[i]);
            input_bt2020 |= caps.input_color_standards[i] == VAProcColorStandardBT2020;
        }
        for (unsigned i = 0; i < caps.num_output_color_standards; ++i) {
            fprintf(stderr, "output colour standard=%d\n", caps.output_color_standards[i]);
            output_bt2020 |= caps.output_color_standards[i] == VAProcColorStandardBT2020;
        }
        if (!input_bt2020 || !output_bt2020)
            fail("matching BT2020 input/output convention not advertised");
        if ((caps.num_input_pixel_formats && !input_p010)
                || (caps.num_output_pixel_formats && !output_available))
            fail("queried pipeline format list lacks requested format");
        fprintf(stderr, "caps filter_flags=%u input=%ux%u..%ux%u output=%ux%u..%ux%u\n",
                caps.filter_flags, caps.min_input_width, caps.min_input_height,
                caps.max_input_width, caps.max_input_height, caps.min_output_width,
                caps.min_output_height, caps.max_output_width, caps.max_output_height);
        /* Scaling/interpolation flags are encoded selectors, not independent
         * capability bits. Record raw caps; accepted submission is separate. */
        if (iw < caps.min_input_width || ih < caps.min_input_height
                || (caps.max_input_width && iw > caps.max_input_width)
                || (caps.max_input_height && ih > caps.max_input_height)
                || ow < caps.min_output_width || oh < caps.min_output_height
                || (caps.max_output_width && ow > caps.max_output_width)
                || (caps.max_output_height && oh > caps.max_output_height))
            fail("requested dimensions outside advertised pipeline bounds");
        VARectangle source = {0, 0, (uint16_t)iw, (uint16_t)ih};
        VARectangle target = {0, 0, (uint16_t)ow, (uint16_t)oh};
        VAProcPipelineParameterBuffer parameters = {0};
        parameters.surface = surfaces[0];
        parameters.surface_region = &source;
        parameters.output_region = &target;
        parameters.filter_flags = flags;
        /* Separate per-job API optimization hint, NOT the scaling-quality
         * selector above or a portable promise of an engine. Measure routing. */
        parameters.pipeline_flags = pipeline_flags;
        /* None can select a size-dependent colour standard in Intel drivers.
         * Equal explicit standards prevent a hidden resize-time CSC request.
         * This is a native-code transport convention, not RPU interpretation. */
        parameters.surface_color_standard = VAProcColorStandardBT2020;
        parameters.output_color_standard = VAProcColorStandardBT2020;
        parameters.input_color_properties.color_range = colour_range;
        parameters.input_color_properties.chroma_sample_location = input_chroma;
        parameters.output_color_properties = parameters.input_color_properties;
        parameters.output_color_properties.chroma_sample_location = output_chroma;
        VA_CHECK(vaCreateBuffer(display, context, VAProcPipelineParameterBufferType,
                               sizeof(parameters), 1, &parameters, &pipeline));
        before_vpp = engine_sample();
        VA_CHECK(vaBeginPicture(display, context, surfaces[1]));
        VA_CHECK(vaRenderPicture(display, context, &pipeline, 1));
        VA_CHECK(vaEndPicture(display, context));
        VA_CHECK(vaSyncSurface(display, surfaces[1]));
        after_vpp = engine_sample();
    }
    unsigned char *output = download(surfaces[copy ? 0 : 1], ow, oh, output_fourcc);
    EngineSample after_download = engine_sample();
    int out_fd = open(argv[3], O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (out_fd < 0) fail("output must be a new writable path");
    FILE *out = fdopen(out_fd, "wb");
    if (!out) { close(out_fd); fail("output stream"); }
    size_t output_size = (size_t)ow * oh * (output_fourcc == VA_FOURCC_P010 ? 3 : 8);
    if (fwrite(output, 1, output_size, out) != output_size || fflush(out) || fclose(out))
        fail("write output");
    free(output);
    printf("{\"schema\":\"yblod.vaapi-scaler-invocation.v1\",\"status\":\"complete\",\"vendor\":");
    json_string(vaQueryVendorString(display) ? vaQueryVendorString(display) : "unknown");
    printf(",\"surface_contract\":\"%s\",\"output_surface_advertised\":",
           allocation_diagnostic ? "allocation-diagnostic" : "advertised");
    if (copy) printf("null");
    else printf("%s", surface_output ? "true" : "false");
    printf(",\"input_fourcc\":%u,\"output_fourcc\":%u,\"input_rt_format\":%u,"
           "\"output_rt_format\":%u,\"output_packed_bytes\":%zu",
           VA_FOURCC_P010, output_fourcc, VA_RT_FORMAT_YUV420_10, output_rt, output_size);
    printf(",\"va_version\":[%d,%d],\"input_size\":[%u,%u],\"output_size\":[%u,%u],"
           "\"filter_flags\":%u,\"input_chroma_siting\":",
           major, minor, iw, ih, ow, oh, flags);
    if (copy) printf("null,\"output_chroma_siting\":null,");
    else printf("%u,\"output_chroma_siting\":%u,", input_chroma, output_chroma);
    if (copy) printf("\"colour_standard\":null,\"colour_range\":null,");
    else printf("\"colour_standard\":%d,\"colour_range\":%u,",
                VAProcColorStandardBT2020, colour_range);
    if (copy) printf("\"pipeline_flags\":null,\"pipeline_caps_flags\":null,");
    else printf("\"pipeline_flags\":%u,\"pipeline_caps_flags\":%u,", pipeline_flags, pipeline_caps_flags);
    printf("\"vpp_submitted\":%s,\"hardware_engine_verified\":false,", copy ? "false" : "true");
    printf("\"drm_client_engine_accounting\":{\"unit\":\"ns\",\"before_vpp\":");
    engine_json(before_vpp);
    printf(",\"after_vpp_sync\":");
    engine_json(after_vpp);
    printf(",\"after_download\":");
    engine_json(after_download);
    printf(",\"vpp_interval_delta\":");
    engine_delta_json(before_vpp, after_vpp);
    printf(",\"download_interval_delta\":");
    engine_delta_json(after_vpp, after_download);
    printf("}}\n");
    if (fflush(stdout) || ferror(stdout)) fail("write invocation report");
    return EXIT_SUCCESS;
}
