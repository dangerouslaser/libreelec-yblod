#define _POSIX_C_SOURCE 200809L
#include "native_gpu_probe_fixture.h"
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int unchanged(const struct stat *a,const struct stat *b)
{
#if defined(__APPLE__)
    return a->st_dev==b->st_dev && a->st_ino==b->st_ino && a->st_size==b->st_size &&
           a->st_mtime==b->st_mtime && a->st_mtimensec==b->st_mtimensec &&
           a->st_ctime==b->st_ctime && a->st_ctimensec==b->st_ctimensec;
#else
    return a->st_dev==b->st_dev && a->st_ino==b->st_ino && a->st_size==b->st_size &&
           a->st_mtim.tv_sec==b->st_mtim.tv_sec && a->st_mtim.tv_nsec==b->st_mtim.tv_nsec &&
           a->st_ctim.tv_sec==b->st_ctim.tv_sec && a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
#endif
}

static uint32_t u32(FILE *stream, int *valid)
{
    unsigned char bytes[4];
    if (fread(bytes,1,4,stream) != 4) { *valid = 0; return 0; }
    return (uint32_t)bytes[0] | (uint32_t)bytes[1]<<8 | (uint32_t)bytes[2]<<16 | (uint32_t)bytes[3]<<24;
}
static uint64_t u64(FILE *stream, int *valid)
{
    uint64_t low = u32(stream,valid), high = u32(stream,valid);
    return low | high<<32;
}
static int64_t i64(FILE *stream, int *valid)
{
    uint64_t value = u64(stream,valid);
    return value <= INT64_MAX ? (int64_t)value : -1-(int64_t)(UINT64_MAX-value);
}
static int32_t i32(FILE *stream, int *valid)
{
    uint32_t value = u32(stream,valid);
    return value <= INT32_MAX ? (int32_t)value : -1-(int32_t)(UINT32_MAX-value);
}

int yb_probe_load(const char *path, struct yb_probe_fixture *f)
{
    if (!path || !f) return 0;
    int fd = open(path,O_RDONLY|O_NONBLOCK);
    if (fd < 0) return 0;
    struct stat info;
    if (fstat(fd,&info) || !S_ISREG(info.st_mode) || info.st_size < 64 || info.st_size > 262144) { close(fd); return 0; }
    FILE *stream = fdopen(fd,"rb");
    if (!stream) { close(fd); return 0; }
    memset(f,0,sizeof(*f));
    unsigned char magic[8];
    int valid = fread(magic,1,8,stream) == 8 && memcmp(magic,"YBGPU01\0",8) == 0;
    f->count = u32(stream,&valid);
    f->component = i32(stream,&valid); f->enabled = i32(stream,&valid); f->output_depth = i32(stream,&valid);
    f->mapping.bit_depth = i32(stream,&valid); f->mapping.denominator = i32(stream,&valid);
    f->nlq.bit_depth = i32(stream,&valid); f->nlq.offset = i32(stream,&valid);
    f->nlq.denominator = f->mapping.denominator;
    f->nlq.slope = u64(stream,&valid); f->nlq.threshold = u64(stream,&valid); f->nlq.maximum = u64(stream,&valid);
    for (unsigned c = 0; c < 3; ++c) {
        struct yb_component_mapping *curve = &f->mapping.components[c];
        curve->pivot_count = i32(stream,&valid);
        for (unsigned p = 0; p < 17; ++p) curve->pivots[p] = i32(stream,&valid);
        for (unsigned s = 0; s < 16; ++s) {
            struct yb_segment *segment = &curve->segments[s];
            segment->method = i32(stream,&valid); segment->order = i32(stream,&valid); segment->constant = i64(stream,&valid);
            for (unsigned r = 0; r < 3; ++r)
                for (unsigned t = 0; t < 7; ++t) segment->coefficients[r][t] = i64(stream,&valid);
        }
    }
    if (!valid || f->count < 1 || f->count > YB_PROBE_MAX_SAMPLES || f->component < 0 || f->component > 2 ||
        (f->enabled != 0 && f->enabled != 1) || (f->output_depth != 10 && f->output_depth != 12) ||
        yb_validate_mapping(&f->mapping) != YB_OK) { fclose(stream); return 0; }
    if (f->enabled ? yb_validate_nlq(&f->nlq) != YB_OK :
        (f->nlq.bit_depth || f->nlq.offset || f->nlq.slope || f->nlq.threshold || f->nlq.maximum)) {
        fclose(stream); return 0;
    }
    uint32_t top = (UINT32_C(1) << (unsigned)f->mapping.bit_depth)-1;
    uint32_t el_top = f->enabled ? (UINT32_C(1) << (unsigned)f->nlq.bit_depth)-1 : 0;
    for (uint32_t index = 0; index < f->count; ++index) {
        struct yb_probe_sample *sample = &f->samples[index];
        sample->y = u32(stream,&valid); sample->cb = u32(stream,&valid);
        sample->cr = u32(stream,&valid); sample->el = u32(stream,&valid);
        if (sample->y > top || sample->cb > top || sample->cr > top || sample->el > el_top) valid = 0;
    }
    if (fgetc(stream) != EOF || ferror(stream)) valid = 0;
    struct stat after,path_after;
    if (fstat(fileno(stream),&after) || stat(path,&path_after) ||
        !unchanged(&info,&after) || !unchanged(&info,&path_after)) valid = 0;
    if (fclose(stream)) valid = 0;
    if (!valid || yb_gpu_check_mapping_width(&f->mapping,&f->width) != YB_OK) return 0;
    f->polynomial_only = 1;
    f->algorithm_supported = 1;
    for (unsigned c = 0; c < 3; ++c)
        for (int32_t s = 0; s < f->mapping.components[c].pivot_count-1; ++s)
            if (f->mapping.components[c].segments[s].method != YB_POLYNOMIAL) f->polynomial_only = 0;
    return 1;
}

int yb_probe_cpu(const struct yb_probe_fixture *f, struct yb_probe_result *output)
{
    for (uint32_t index = 0; index < f->count; ++index) {
        const struct yb_probe_sample *sample = &f->samples[index];
        const int64_t values[3] = {sample->y,sample->cb,sample->cr};
        uint16_t mapped = 0, reconstructed = 0;
        int64_t residual = 0;
        if (yb_map_sample(&f->mapping,f->component,values,&mapped) != YB_OK ||
            (f->enabled && yb_nlq(&f->nlq,sample->el,&residual) != YB_OK) ||
            yb_compose_residual(mapped,residual,f->output_depth,&reconstructed) != YB_OK ||
            residual < INT32_MIN || residual > INT32_MAX || mapped+residual < INT32_MIN || mapped+residual > INT32_MAX) return 0;
        output[index] = (struct yb_probe_result){mapped,(int32_t)residual,(int32_t)(mapped+residual),reconstructed};
    }
    return 1;
}

void yb_probe_metadata(const struct yb_probe_fixture *f, int64_t words[YB_PROBE_METADATA_WORDS])
{
    memset(words,0,sizeof(int64_t)*YB_PROBE_METADATA_WORDS);
    const struct yb_component_mapping *curve = &f->mapping.components[f->component];
    words[0]=f->count; words[1]=f->component; words[2]=f->enabled; words[3]=f->output_depth;
    words[4]=f->mapping.bit_depth; words[5]=f->mapping.denominator; words[6]=f->nlq.bit_depth; words[7]=f->nlq.offset;
    words[8]=(int64_t)f->nlq.slope; words[9]=(int64_t)f->nlq.threshold; words[10]=(int64_t)f->nlq.maximum;
    for (unsigned c=0;c<3;++c) {
        const struct yb_component_mapping *bounds=&f->mapping.components[c];
        words[11+c*2]=bounds->pivots[0];
        words[12+c*2]=bounds->pivots[bounds->pivot_count-1];
    }
    words[17]=curve->pivot_count;
    for (unsigned p=0;p<17;++p) words[18+p]=curve->pivots[p];
    for (unsigned s=0;s<16;++s) {
        words[35+s*24]=curve->segments[s].method;
        words[36+s*24]=curve->segments[s].order;
        words[37+s*24]=curve->segments[s].constant;
        for (unsigned r=0;r<3;++r)
            for (unsigned t=0;t<7;++t) words[38+s*24+r*7+t]=curve->segments[s].coefficients[r][t];
    }
}
