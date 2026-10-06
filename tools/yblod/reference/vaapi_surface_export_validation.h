#ifndef YB_SURFACE_EXPORT_VALIDATION_H
#define YB_SURFACE_EXPORT_VALIDATION_H
#include <stdint.h>
#include <stddef.h>
#define YB_FOURCC(a,b,c,d) ((uint32_t)(a)|((uint32_t)(b)<<8)|((uint32_t)(c)<<16)|((uint32_t)(d)<<24))
typedef struct { int fd; uint32_t size; uint64_t modifier; } YbExportObject;
typedef struct { uint32_t format, planes, object[4], offset[4], pitch[4]; } YbExportLayer;
typedef struct { uint32_t format, width, height, objects, layers; YbExportObject obj[4]; YbExportLayer layer[4]; } YbExportDescriptor;
/* Only slots within a successfully returned descriptor's declared object
 * count transfer ownership. Never infer ownership from unused fd fields. */
static uint32_t yb_export_owned_fd_mask(uint32_t count, const int fds[4])
{
    if (!fds) return 0;
    if (count > 4) count = 4;
    uint32_t mask=0;
    for(uint32_t i=0;i<count;++i) {
        if(fds[i]<0) continue;
        int duplicate=0;
        for(uint32_t j=0;j<i;++j) if(fds[j]==fds[i]) duplicate=1;
        if(!duplicate) mask |= 1u<<i;
    }
    return mask;
}
/* Structural checks apply to every modifier. Linear layout checks additionally
 * establish active row extents; opaque tiled/compressed extents are NOT inferred. */
static int yb_export_validate(const YbExportDescriptor *d, uint32_t format, int *linear)
{
    if (!d || !linear || d->format != format || d->width != 4 || d->height != 4 ||
        !d->objects || d->objects > 4 || !d->layers || d->layers > 4) return 0;
    if (format != YB_FOURCC('P','0','1','0') && format != YB_FOURCC('Y','4','1','6')) return 0;
    int all_linear = 1;
    for (uint32_t i=0;i<d->objects;++i) {
        if (d->obj[i].fd < 0 || !d->obj[i].size || d->obj[i].size > 16u*1024u*1024u) return 0;
        for (uint32_t j=0;j<i;++j) if (d->obj[i].fd == d->obj[j].fd) return 0;
        if (d->obj[i].modifier) all_linear = 0;
    }
    uint32_t used = 0;
    for (uint32_t i=0;i<d->layers;++i) {
        const YbExportLayer *l=&d->layer[i];
        if (!l->planes || l->planes > 4 || !l->format) return 0;
        for (uint32_t p=0;p<l->planes;++p) {
            if (l->object[p] >= d->objects || !l->pitch[p] || l->pitch[p] > 16u*1024u*1024u ||
                l->offset[p] >= d->obj[l->object[p]].size) return 0;
            used |= 1u << l->object[p];
        }
    }
    if (used != (1u << d->objects)-1u) return 0;
    if (all_linear) {
        uint32_t layers = format == YB_FOURCC('P','0','1','0') ? 2u : 1u;
        if (d->layers != layers) return 0;
        uint64_t start[2]={0}, end[2]={0};
        for (uint32_t i=0;i<layers;++i) {
            const YbExportLayer *l=&d->layer[i];
            uint32_t expected = layers == 2 ? (i ? YB_FOURCC('G','R','3','2') : YB_FOURCC('R','1','6',' ')) : YB_FOURCC('Y','4','1','6');
            uint32_t rows = i ? 2u : 4u, bytes = layers == 2 ? 8u : 32u;
            if (l->planes != 1 || l->format != expected || l->pitch[0] < bytes) return 0;
            start[i]=l->offset[0];
            end[i]=start[i]+(uint64_t)(rows-1u)*l->pitch[0]+bytes;
            if (end[i] > d->obj[l->object[0]].size) return 0;
        }
        if (layers==2 && d->layer[0].object[0]==d->layer[1].object[0] &&
            start[0]<end[1] && start[1]<end[0]) return 0;
    }
    *linear=all_linear;
    return 1;
}
#endif
