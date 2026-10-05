#include "native_scaled_surface.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>

uint32_t yb_scaled_surface_abi_version(void) { return 1; }
uint64_t yb_scaled_surface_sizeof_descriptor(void) { return sizeof(yb_scaled_surface); }
static int span(const void *p, uint64_t n, uintptr_t *lo, uintptr_t *hi)
{
    uintptr_t a=(uintptr_t)p;
    if (!p || !n || n>UINTPTR_MAX || a>UINTPTR_MAX-(uintptr_t)n) return 0;
    *lo=a; *hi=a+(uintptr_t)n; return 1;
}
static int overlap(uintptr_t a, uintptr_t b, uintptr_t c, uintptr_t d)
{ return a<d && c<b; }
static int plane(uint64_t offset,uint64_t stride,uint64_t rows,
                 uint64_t rowbytes,uint64_t allocation,uint64_t *end)
{
    uint64_t tail;
    if ((offset|stride)&1U || stride<rowbytes || !rows ||
        rows-1>(UINT64_MAX-rowbytes)/stride) return 0;
    tail=(rows-1)*stride+rowbytes;
    if (offset>allocation || tail>allocation-offset) return 0;
    *end=offset+tail; return 1;
}
static uint16_t word(const yb_scaled_surface *d,uint32_t c,uint64_t index)
{
    uint64_t width=c ? d->width/2U : d->width;
    uint64_t offset=(c ? d->uv_offset : d->y_offset)+
        (index/width)*(c ? d->uv_stride : d->y_stride)+
        (index%width)*(c ? 4U : 2U)+(c==2 ? 2U : 0U);
    const uint8_t *p=d->allocation+(size_t)offset;
    return (uint16_t)((uint16_t)p[0]|((uint16_t)p[1]<<8));
}
int yb_scaled_surface_extract(const yb_scaled_surface *d,
    const uint8_t frame[32],const uint8_t provenance[32],uint32_t c,
    uint64_t start,uint32_t count,uint32_t mode,uint16_t *output)
{
    uintptr_t dl,dh,fl,fh,pl,ph,al,ah,ol,oh;
    uint64_t ye,ue,total;
    if (!span(d,sizeof(*d),&dl,&dh) || dl%_Alignof(yb_scaled_surface) ||
        !span(frame,32,&fl,&fh) || !span(provenance,32,&pl,&ph) ||
        !count || count>65536 || !span(output,(uint64_t)count*2,&ol,&oh) ||
        ol%_Alignof(uint16_t)) return YB_SURFACE_INVALID;
    if (overlap(dl,dh,fl,fh)||overlap(dl,dh,pl,ph)||
        overlap(fl,fh,pl,ph)||overlap(ol,oh,dl,dh)||
        overlap(ol,oh,fl,fh)||overlap(ol,oh,pl,ph)) return YB_SURFACE_ALIAS;
    if (d->version!=1 || d->format!=YB_SURFACE_NATIVE10_Q6 || d->coherent_ready!=1 ||
        !d->width || !d->height || d->width>8192 || d->height>8192 ||
        ((d->width|d->height)&1U) || c>2 ||
        (mode!=YB_SURFACE_RAW_WORDS && mode!=YB_SURFACE_EXACT_WHOLE_CODES) ||
        !span(d->allocation,d->allocation_bytes,&al,&ah) || (al&1U) ||
        !plane(d->y_offset,d->y_stride,d->height,(uint64_t)d->width*2,
               d->allocation_bytes,&ye) ||
        !plane(d->uv_offset,d->uv_stride,d->height/2U,(uint64_t)d->width*2,
               d->allocation_bytes,&ue)) return YB_SURFACE_INVALID;
    if (overlap(al,ah,dl,dh)||overlap(al,ah,fl,fh)||overlap(al,ah,pl,ph)||
        overlap(al,ah,ol,oh)||
        (d->y_offset<ue && d->uv_offset<ye)) return YB_SURFACE_ALIAS;
    total=(uint64_t)d->width*d->height/(c ? 4U : 1U);
    if (start>total || count>total-start) return YB_SURFACE_INVALID;
    if (memcmp(frame,d->frame_id,32)||memcmp(provenance,d->provenance_id,32))
        return YB_SURFACE_ASSOCIATION;
    if (mode==YB_SURFACE_EXACT_WHOLE_CODES)
        for(uint32_t i=0;i<count;i++)
            if (word(d,c,start+i)&63U) return YB_SURFACE_FRACTIONAL;
    for(uint32_t i=0;i<count;i++) {
        uint16_t v=word(d,c,start+i);
        output[i]=mode==YB_SURFACE_RAW_WORDS ? v : (uint16_t)(v>>6);
    }
    return YB_SURFACE_OK;
}
