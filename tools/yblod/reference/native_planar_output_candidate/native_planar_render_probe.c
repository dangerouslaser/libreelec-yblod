#define _POSIX_C_SOURCE 200809L
#include "dvbridge_render.h"
#include "dvbridge_native_colour.h"
#include "dvbridge_placebo.h"
#include <libavutil/dovi_meta.h>
#include <libplacebo/opengl.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

struct fixture { AVDOVIMetadata meta; AVDOVIRpuDataHeader header;
    AVDOVIDataMapping mapping; AVDOVIColorMetadata colour; AVDOVIDmData ext; };
static void metadata(struct fixture *f)
{
    memset(f,0,sizeof(*f));
    f->meta.header_offset=offsetof(struct fixture,header);
    f->meta.mapping_offset=offsetof(struct fixture,mapping);
    f->meta.color_offset=offsetof(struct fixture,colour);
    f->meta.ext_block_offset=offsetof(struct fixture,ext);
    f->meta.ext_block_size=sizeof(f->ext);
    f->meta.num_ext_blocks=1;
    f->ext.level=1;
    f->ext.l1.min_pq=0;f->ext.l1.max_pq=3079;f->ext.l1.avg_pq=1500;
    f->header.rpu_type=2; f->header.rpu_format=18;
    f->header.vdr_rpu_normalized_idc=1; f->header.vdr_bit_depth=12;
    f->header.bl_bit_depth=10; f->header.el_bit_depth=10;
    f->header.coef_log2_denom=10; f->header.disable_residual_flag=1;
    f->colour.signal_eotf=65535; f->colour.signal_bit_depth=12;
    f->colour.signal_full_range_flag=1; f->colour.source_max_pq=3079;
    for(unsigned i=0;i<9;i++) {
        f->colour.ycc_to_rgb_matrix[i]=(AVRational){i%4?0:8192,8192};
        f->colour.rgb_to_lms_matrix[i]=(AVRational){i%4?0:16384,16384};
    }
    for(unsigned c=0;c<3;c++) {
        f->colour.ycc_to_rgb_offset[c]=(AVRational){0,1<<28};
        f->mapping.curves[c].num_pivots=2;
        f->mapping.curves[c].pivots[1]=1023;
        f->mapping.curves[c].poly_order[0]=1;
        f->mapping.curves[c].poly_coef[0][1]=1024;
    }
}
static int context(const char *node,EGLDisplay *display,EGLContext *ctx)
{
    PFNEGLQUERYDEVICESEXTPROC query=(PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLQUERYDEVICESTRINGEXTPROC string=(PFNEGLQUERYDEVICESTRINGEXTPROC)eglGetProcAddress("eglQueryDeviceStringEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    if(!query||!string||!platform)return 0;
    EGLDeviceEXT devices[32],selected=EGL_NO_DEVICE_EXT; EGLint n=0;
    if(!query(32,devices,&n)||n<1||n>32)return 0;
    struct stat requested,candidate; if(stat(node,&requested)||!S_ISCHR(requested.st_mode))return 0;
    unsigned matches=0;
    for(int i=0;i<n;i++) {
        const char *path=string(devices[i],EGL_DRM_RENDER_NODE_FILE_EXT);
        if(path&&!stat(path,&candidate)&&candidate.st_rdev==requested.st_rdev) {selected=devices[i];matches++;}
    }
    if(matches!=1)return 0;
    *display=platform(EGL_PLATFORM_DEVICE_EXT,selected,NULL);
    if(*display==EGL_NO_DISPLAY||!eglInitialize(*display,NULL,NULL)||!eglBindAPI(EGL_OPENGL_API))return 0;
    EGLint attributes[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT,EGL_NONE};
    EGLConfig config; EGLint count=0;
    if(!eglChooseConfig(*display,attributes,&config,1,&count)||count!=1)return 0;
    EGLint ca[]={EGL_CONTEXT_MAJOR_VERSION,4,EGL_CONTEXT_MINOR_VERSION,5,
                EGL_CONTEXT_OPENGL_PROFILE_MASK,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,EGL_NONE};
    *ctx=eglCreateContext(*display,config,EGL_NO_CONTEXT,ca);
    return *ctx!=EGL_NO_CONTEXT&&eglMakeCurrent(*display,EGL_NO_SURFACE,EGL_NO_SURFACE,*ctx);
}
static unsigned clamped(int v,unsigned limit)
{return v<0?0U:(unsigned)v>=limit?limit-1U:(unsigned)v;}
static int compare(pl_gpu gpu,unsigned width,unsigned height,const char *checkpoint,
                   unsigned long long *compared,unsigned *failure_checks,unsigned *packet_words)
{
    (void)checkpoint;
    int okay=0;const char *phase="allocate";
    struct dvbridge_renderer *renderer=NULL;
    pl_tex tex[4]={0};
    size_t samples=(size_t)width*height;
    uint16_t *planes[3]={calloc(samples,sizeof(uint16_t)),calloc(samples/4,sizeof(uint16_t)),calloc(samples/4,sizeof(uint16_t))};
    float *rgba=calloc(samples*4,sizeof(float));
    float *row=calloc((size_t)width*4,sizeof(float)),*saved=calloc(samples*4,sizeof(float));
    uint32_t packets[512];unsigned count=0;
    PFNGLGETTEXTURESUBIMAGEPROC read=(PFNGLGETTEXTURESUBIMAGEPROC)eglGetProcAddress("glGetTextureSubImage");
    PFNGLGETERRORPROC error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");
    if(!planes[0]||!planes[1]||!planes[2]||!rgba||!row||!saved||!read||!error)goto done;
    phase="formats";
    pl_fmt floating=pl_find_named_fmt(gpu,"rgba32f"),integer=pl_find_named_fmt(gpu,"r16u");
    if(!floating||!integer)goto done;
    phase="textures";
    tex[0]=pl_tex_create(gpu,pl_tex_params(.w=width,.h=height,.format=floating,.sampleable=true,.host_writable=true));
    for(unsigned c=0;c<3;c++) {
        unsigned w=c?width/2:width,h=c?height/2:height;
        tex[c+1]=pl_tex_create(gpu,pl_tex_params(.w=w,.h=h,.format=integer,.sampleable=true,.host_writable=true));
        if(!tex[c+1])goto done;
        for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++)
            planes[c][(size_t)y*w+x]=(uint16_t)((x*379U+y*173U+c*1249U)%4096U);
        if(!pl_tex_upload(gpu,pl_tex_transfer_params(.tex=tex[c+1],.ptr=planes[c])))goto done;
    }
    if(!tex[0])goto done;
    phase="oracle";
    for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++) {
        size_t p=((size_t)y*width+x)*4;
        rgba[p]=(float)planes[0][(size_t)y*width+x]/4096.0f;
        for(unsigned c=1;c<3;c++) {
            unsigned w=width/2,h=height/2,fx=x%2,fy=y%2?1U:3U;
            int firstx=(int)(x/2),firsty=(int)(y/2)-(y%2?0:1);
            unsigned x0=clamped(firstx,w),x1=clamped(firstx+1,w),y0=clamped(firsty,h),y1=clamped(firsty+1,h);
            uint32_t a=planes[c][(size_t)y0*w+x0],b=planes[c][(size_t)y1*w+x0];
            uint32_t v=planes[c][(size_t)y0*w+x1],d=planes[c][(size_t)y1*w+x1];
            uint32_t numerator=a*(4U-fy)*(2U-fx)+b*fy*(2U-fx)+v*(4U-fy)*fx+d*fy*fx;
            rgba[p+c]=(float)numerator/32768.0f;
        }
        rgba[p+3]=1;
    }
    if(!pl_tex_upload(gpu,pl_tex_transfer_params(.tex=tex[0],.ptr=rgba)))goto done;
    phase="renderer-create";
    renderer=dvbridge_renderer_create(gpu);if(!renderer)goto done;
    struct fixture f;metadata(&f);
    struct dvbridge_geometry geometry={(int)width,(int)height,0,0,(int)width,(int)height};
    struct dvbridge_native_colour_association a={.version=1,.width=width,.height=height,
        .enhancement_width=width/2,.enhancement_height=height/2,.vaapi_p010_admitted=1,
        .unrotated=1,.reconstructed_depth=12,.bl_pts=100,.el_pts=100,.timebase_num=1,
        .timebase_den=1000,.expected_frame_id={1},.reconstructed_frame_id={1},
        .presentation_pts=100,.enhancement_presentation_pts=100};
    struct dvbridge_native_planar native={.textures={tex[1],tex[2],tex[3]},
        .width=width,.height=height,.output_depth=12,.sampling_contract=1};
    for(unsigned route=0;route<3;route++) {
        phase=route==1?"render-planar":"render-float";
        int rendered=route==1?dvbridge_render_native_planar_rgb(renderer,&a,&native,&f,sizeof(f),geometry):
            dvbridge_render_native_reconstructed_rgb(renderer,&a,tex[0],&f,sizeof(f),geometry);
        if(!rendered)goto done;
        unsigned current_count=0;
        const uint32_t *current=dvbridge_packets(dvbridge_render_candidate(renderer),&current_count);
        if(!current||!current_count||current_count>4)goto done;
        if(!route){count=current_count;memcpy(packets,current,(size_t)count*128U*sizeof(uint32_t));}
        else if(current_count!=count||memcmp(packets,current,(size_t)count*128U*sizeof(uint32_t)))goto done;
        else *packet_words+=count*128U;
        pl_gpu_finish(gpu);
        GLuint texture=pl_opengl_unwrap(gpu,dvbridge_render_texture(renderer),NULL,NULL,NULL);
        if(!texture)goto done;
        phase=route?"compare":"save";
        for(unsigned y=0;y<height;y++) {
            read(texture,0,0,(GLint)y,0,(GLsizei)width,1,1,GL_RGBA,GL_FLOAT,(GLsizei)(width*16U),row);
            if(error()!=GL_NO_ERROR)goto done;
            if(!route)memcpy(saved+(size_t)y*width*4,row,(size_t)width*16);
            else if(memcmp(saved+(size_t)y*width*4,row,(size_t)width*16))goto done;
            else *compared+=(unsigned long long)width*4U;
        }
    }
    phase="reject";
    native.output_depth=10;
    if(dvbridge_render_native_planar_rgb(renderer,&a,&native,&f,sizeof(f),geometry)||dvbridge_render_texture(renderer))goto done;
    (*failure_checks)++;native.output_depth=12;
    native.sampling_contract=0;
    if(dvbridge_render_native_planar_rgb(renderer,&a,&native,&f,sizeof(f),geometry)||dvbridge_render_texture(renderer))goto done;
    (*failure_checks)++;native.sampling_contract=1;
    a.el_pts++;
    if(dvbridge_render_native_planar_rgb(renderer,&a,&native,&f,sizeof(f),geometry)||dvbridge_render_texture(renderer))goto done;
    (*failure_checks)++;
    okay=1;
done:
    fprintf(stderr,"planar-render-probe phase=%s complete=%d compared=%llu gl_error=0x%x egl_error=0x%x\n",
        phase,okay,*compared,error?error():0U,(unsigned)eglGetError());
    dvbridge_renderer_destroy(renderer);
    for(unsigned i=0;i<4;i++)pl_tex_destroy(gpu,&tex[i]);
    for(unsigned i=0;i<3;i++)free(planes[i]);
    free(rgba);free(row);free(saved);return okay;
}
static void gpu_log(void *opaque,enum pl_log_level level,const char *message)
{
    (void)opaque;fprintf(stderr,"libplacebo level=%d: %s\n",(int)level,message?message:"unavailable");
}
int main(int argc,char **argv)
{
    if(argc==2&&!strcmp(argv[1],"--metadata-only")) {
        struct fixture f;metadata(&f);struct dvbridge_color colour;
        int mapped=dvbridge_map_color(&colour,&f,sizeof(f),true);
        struct dvbridge_context *owner=dvbridge_create();
        struct dvbridge_geometry g={64,64,0,0,64,64};
        struct dvbridge_candidate *candidate=owner?dvbridge_prepare(owner,&f,sizeof(f),100,g,false):NULL;
        int prepared=candidate!=NULL;
        dvbridge_candidate_destroy(candidate);dvbridge_destroy(owner);
        printf("{\"metadata_map\":%s,\"metadata_prepare\":%s,\"gpu_attempted\":false}\n",
               mapped?"true":"false",prepared?"true":"false");
        return mapped&&prepared?0:1;
    }
    if(argc!=3&&argc!=5)return 2;
    unsigned width=64,height=64;
    if(argc==5) {
        char *end=NULL;unsigned long w=strtoul(argv[3],&end,10);
        if(!*argv[3]||*end||w<4||w>64||w%4)return 2;
        unsigned long h=strtoul(argv[4],&end,10);
        if(!*argv[4]||*end||h<4||h>64||h%4)return 2;
        width=(unsigned)w;height=(unsigned)h;
    }
    EGLDisplay display=EGL_NO_DISPLAY;EGLContext ctx=EGL_NO_CONTEXT;
    pl_opengl gl=NULL;pl_log log=NULL;int okay=0,cleanup=1;unsigned long long compared=0;unsigned failures=0,packet_words=0;
    if(!context(argv[1],&display,&ctx))goto done;
    log=pl_log_create(PL_API_VER,pl_log_params(.log_cb=gpu_log,.log_level=PL_LOG_WARN));
    if(!log)goto done;
    gl=pl_opengl_create(log,pl_opengl_params(.get_proc_addr=(pl_voidfunc_t(*)(const char*))eglGetProcAddress,
        .egl_display=display,.egl_context=ctx,.allow_software=false));
    if(!gl)goto done;
    okay=compare(gl->gpu,width,height,argv[2],&compared,&failures,&packet_words);
done:
    pl_opengl_destroy(&gl);
    pl_log_destroy(&log);
    if(display!=EGL_NO_DISPLAY) {
        if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT))cleanup=0;
        if(ctx!=EGL_NO_CONTEXT&&!eglDestroyContext(display,ctx))cleanup=0;
        if(!eglTerminate(display))cleanup=0;
    }
    printf("{\"complete\":%s,\"cleanup_complete\":%s,\"rgb_float_values_bit_compared\":%llu,\"packet_words_bit_compared\":%u,\"failure_checks\":%u,\"synthetic_source_size\":[%u,%u],\"full_output_size\":[3840,2160]}\n",
        okay?"true":"false",cleanup?"true":"false",compared,packet_words,failures,width,height);
    return okay&&cleanup?0:1;
}
