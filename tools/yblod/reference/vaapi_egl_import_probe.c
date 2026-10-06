/* Fixed public synthetic allocation/upload/export inventory; not DV playback. */
#define _POSIX_C_SOURCE 200809L
#include <va/va.h>
#include <va/va_drm.h>
#include <va/va_drmcommon.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include "vaapi_surface_export_validation.h"
static VADisplay display;
static int fd=-1, initialized, mapped;
static VASurfaceID surface=VA_INVALID_ID;
static VAImage image;
static int image_created;
static VADRMPRIMESurfaceDescriptor exported;
static int cleanup_ok=1;
static int export_succeeded;
static void cleanup(void) {
    int owned_fds[4];
    for(unsigned i=0;i<4;++i) owned_fds[i]=exported.objects[i].fd;
    uint32_t owned=yb_export_owned_fd_mask(export_succeeded?exported.num_objects:0,owned_fds);
    for (unsigned i=0;i<4;++i) {
        int value=exported.objects[i].fd;
        if((owned & (1u<<i)) && close(value)) cleanup_ok=0;
        exported.objects[i].fd=-1;
    }
    export_succeeded=0;
    if(mapped) { if(vaUnmapBuffer(display,image.buf)) cleanup_ok=0; mapped=0; }
    if(image_created) { if(vaDestroyImage(display,image.image_id)) cleanup_ok=0; image_created=0; }
    if(surface!=VA_INVALID_ID) { if(vaDestroySurfaces(display,&surface,1)) cleanup_ok=0; surface=VA_INVALID_ID; }
    if(initialized) { if(vaTerminate(display)) cleanup_ok=0; initialized=0; }
    if(fd>=0) { if(close(fd)) cleanup_ok=0; fd=-1; }
}
static void fail(const char *why) { fprintf(stderr,"surface export failed: %s\n",why); cleanup(); exit(1); }
static void check(VAStatus status,const char *name) { if(status!=VA_STATUS_SUCCESS) fail(name); }
#define CHECK(x) check((x),#x)
static void string_json(const char *s) {
    putchar('"');
    for(const unsigned char *p=(const unsigned char *)s;*p;++p) {
        if(*p=='"'||*p=='\\') printf("\\%c",*p);
        else if(*p<32) printf("\\u%04x",(unsigned)*p);
        else putchar(*p);
    }
    putchar('"');
}
#include "vaapi_egl_import_reader.h"
int main(int argc,char **argv) {
    for(unsigned i=0;i<4;++i) exported.objects[i].fd=-1;
    if(argc!=3) fail("usage: vaapi_egl_import_probe /dev/dri/renderD128 p010|y416");
    unsigned format, rt;
    if(!strcmp(argv[2],"p010")) {format=VA_FOURCC_P010;rt=VA_RT_FORMAT_YUV420_10;}
    else if(!strcmp(argv[2],"y416")) {format=VA_FOURCC_Y416;rt=VA_RT_FORMAT_YUV444_12;}
    else fail("format must be p010 or y416");
    if(strncmp(argv[1],"/dev/dri/renderD",strlen("/dev/dri/renderD"))) fail("explicit render node required");
    const char *number=argv[1]+strlen("/dev/dri/renderD");
    if(strlen(number)!=3 ||
        strspn(number,"0123456789")!=3 || atoi(number)<128 || atoi(number)>255)
        fail("explicit render node required");
    fd=open(argv[1],O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0) fail("open render device");
    struct stat st;
    if(fstat(fd,&st)||!S_ISCHR(st.st_mode)||major(st.st_rdev)!=226||minor(st.st_rdev)!=(unsigned)atoi(number)) fail("not requested DRM render character device");
    display=vaGetDisplayDRM(fd);
    if(!display) fail("vaGetDisplayDRM");
    int major_version=0,minor_version=0;
    CHECK(vaInitialize(display,&major_version,&minor_version)); initialized=1;
    const char *vendor=vaQueryVendorString(display);
    if(!vendor||!strstr(vendor,"Intel")) fail("Intel VA driver required");
    char vendor_copy[1024];
    if(strlen(vendor)>=sizeof(vendor_copy)) fail("vendor string bound");
    strcpy(vendor_copy,vendor);
    VASurfaceAttrib attrs[2]; memset(attrs,0,sizeof(attrs));
    attrs[0].type=VASurfaceAttribPixelFormat; attrs[0].flags=VA_SURFACE_ATTRIB_SETTABLE;
    attrs[0].value.type=VAGenericValueTypeInteger; attrs[0].value.value.i=(int)format;
    attrs[1].type=VASurfaceAttribUsageHint;attrs[1].flags=VA_SURFACE_ATTRIB_SETTABLE;
    attrs[1].value.type=VAGenericValueTypeInteger;attrs[1].value.value.i=VA_SURFACE_ATTRIB_USAGE_HINT_EXPORT;
    CHECK(vaCreateSurfaces(display,rt,4,4,&surface,1,attrs,2));
    int maximum=vaMaxNumImageFormats(display),count=0,found=0;
    if(maximum<=0||maximum>4096) fail("image format capacity");
    VAImageFormat *formats=calloc((size_t)maximum,sizeof(*formats));
    if(!formats) fail("format allocation");
    VAStatus query=vaQueryImageFormats(display,formats,&count);
    if(query!=VA_STATUS_SUCCESS||count<0||count>maximum) {free(formats);fail("image format query");}
    VAImageFormat selected;memset(&selected,0,sizeof(selected));
    for(int i=0;i<count;++i) if(formats[i].fourcc==format) {selected=formats[i];found=1;break;}
    free(formats);
    if(!found||selected.byte_order!=VA_LSB_FIRST) fail("exact little-endian image format unavailable");
    CHECK(vaCreateImage(display,&selected,4,4,&image));image_created=1;
    unsigned planes=format==VA_FOURCC_P010?2u:1u,bytes=planes==2?8u:32u;
    if(image.format.fourcc!=format||image.format.byte_order!=VA_LSB_FIRST||image.width!=4||image.height!=4||image.num_planes!=planes||image.data_size>16u*1024u*1024u) fail("image shape");
    uint64_t starts[2]={0},ends[2]={0};
    for(unsigned p=0;p<planes;++p) {
        unsigned rows=p?2u:4u;
        starts[p]=image.offsets[p];ends[p]=starts[p]+(uint64_t)(rows-1u)*image.pitches[p]+bytes;
        if(image.pitches[p]<bytes||ends[p]>image.data_size) fail("image extent");
    }
    if(planes==2&&starts[0]<ends[1]&&starts[1]<ends[0]) fail("image plane overlap");
    unsigned char *data=NULL;CHECK(vaMapBuffer(display,image.buf,(void **)&data));mapped=1;
    if(!data) fail("null image mapping");
    memset(data,0,image.data_size);
    /* Fixed numeric pattern only: P010 values always have six zero low bits;
     * Y416 packed words include public low-bit detail, without conversion.
     * This inventory does not interpret their component ordering. */
    for(unsigned p=0;p<planes;++p) for(unsigned y=0;y<(p?2u:4u);++y) for(unsigned x=0;x<bytes/2u;++x) {
        unsigned value=planes==2?((64u+x*47u+y*83u+p*127u)&1023u)<<6:((x*997u+y*1231u+17u)&65535u);
        size_t offset=image.offsets[p]+(size_t)y*image.pitches[p]+x*2u;
        data[offset]=(unsigned char)(value&255u);data[offset+1]=(unsigned char)(value>>8);
    }
    CHECK(vaUnmapBuffer(display,image.buf));mapped=0;
    CHECK(vaPutImage(display,surface,image.image_id,0,0,4,4,0,0,4,4));
    CHECK(vaSyncSurface(display,surface));
    CHECK(vaExportSurfaceHandle(display,surface,VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2,
        VA_EXPORT_SURFACE_READ_ONLY|VA_EXPORT_SURFACE_SEPARATE_LAYERS,&exported));
    export_succeeded=1;
    YbExportDescriptor d;memset(&d,0,sizeof(d));
    d.format=exported.fourcc;d.width=exported.width;d.height=exported.height;
    d.objects=exported.num_objects;d.layers=exported.num_layers;
    for(unsigned i=0;i<4;++i) {
        d.obj[i].fd=exported.objects[i].fd;d.obj[i].size=exported.objects[i].size;d.obj[i].modifier=exported.objects[i].drm_format_modifier;
        d.layer[i].format=exported.layers[i].drm_format;d.layer[i].planes=exported.layers[i].num_planes;
        for(unsigned p=0;p<4;++p) {d.layer[i].object[p]=exported.layers[i].object_index[p];d.layer[i].offset[p]=exported.layers[i].offset[p];d.layer[i].pitch[p]=exported.layers[i].pitch[p];}
    }
    int linear=0;if(!yb_export_validate(&d,format,&linear)) fail("export descriptor validation");
    import_probe(&d,&st);
    cleanup();if(!cleanup_ok) fail("cleanup");
    printf("{\"schema\":\"yblod.vaapi-egl-import-probe.v1\",\"complete\":true,\"vendor\":");string_json(vendor_copy);
    printf(",\"va_major\":%d,\"va_minor\":%d,\"fourcc\":%u,\"rt_format\":%u,\"nominal_rt_bits\":%u,\"width\":4,\"height\":4,\"objects\":%u,\"layers\":%u,\"synthetic_upload\":true,\"surface_synchronized\":true,\"descriptor_structural_valid\":true,\"layout_extent_verified\":%s,\"zero_copy_proven\":false,\"dv_playback_tested\":false,\"cleanup_complete\":true,\"object_layout\":[",major_version,minor_version,d.format,rt,planes==2?10u:12u,d.objects,d.layers,linear?"true":"false");
    for(unsigned i=0;i<d.objects;++i) printf("%s{\"size\":%u,\"modifier\":%llu}",i?",":"",d.obj[i].size,(unsigned long long)d.obj[i].modifier);
    printf("],\"layer_layout\":[");
    for(unsigned i=0;i<d.layers;++i) {
        printf("%s{\"drm_format\":%u,\"planes\":[",i?",":"",d.layer[i].format);
        for(unsigned p=0;p<d.layer[i].planes;++p) printf("%s{\"object_index\":%u,\"offset\":%u,\"pitch\":%u}",p?",":"",d.layer[i].object[p],d.layer[i].offset[p],d.layer[i].pitch[p]);
        printf("]}");
    }
    printf("]");import_json();printf("}\n");return import_read && mismatches ? 1 : 0;
}
