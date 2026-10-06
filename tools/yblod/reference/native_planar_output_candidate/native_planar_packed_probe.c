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
    AVDOVIDataMapping mapping; AVDOVIColorMetadata colour; AVDOVIDmData ext,extra; };
_Static_assert(offsetof(struct fixture,extra)==offsetof(struct fixture,ext)+sizeof(AVDOVIDmData),"metadata stride");
static void metadata(struct fixture *f)
{
    memset(f,0,sizeof(*f));
    f->meta.header_offset=offsetof(struct fixture,header);
    f->meta.mapping_offset=offsetof(struct fixture,mapping);
    f->meta.color_offset=offsetof(struct fixture,colour);
    f->meta.ext_block_offset=offsetof(struct fixture,ext);
    f->meta.ext_block_size=sizeof(f->ext);
    f->meta.num_ext_blocks=2;
    f->ext.level=1;
    f->ext.l1.min_pq=0;f->ext.l1.max_pq=3079;f->ext.l1.avg_pq=1500;
    f->extra.level=5;
    f->extra.l5.left_offset=31;f->extra.l5.right_offset=42;
    f->extra.l5.top_offset=17;f->extra.l5.bottom_offset=30;
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
    const char *mode=getenv("YB_PLANAR_PROBE_GLES");
    if(mode&&strcmp(mode,"0")&&strcmp(mode,"1"))return 0;
    const int gles=mode&&!strcmp(mode,"1");
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
    if(*display==EGL_NO_DISPLAY||!eglInitialize(*display,NULL,NULL)||!eglBindAPI(gles?EGL_OPENGL_ES_API:EGL_OPENGL_API))return 0;
    EGLint attributes[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,
        gles?EGL_OPENGL_ES3_BIT:EGL_OPENGL_BIT,EGL_NONE};
    EGLConfig config; EGLint count=0;
    if(!eglChooseConfig(*display,attributes,&config,1,&count)||count!=1)return 0;
    EGLint ca[]={EGL_CONTEXT_MAJOR_VERSION,4,EGL_CONTEXT_MINOR_VERSION,5,
                EGL_CONTEXT_OPENGL_PROFILE_MASK,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,EGL_NONE};
    EGLint es[]={EGL_CONTEXT_MAJOR_VERSION,3,EGL_CONTEXT_MINOR_VERSION,1,EGL_NONE};
    *ctx=eglCreateContext(*display,config,EGL_NO_CONTEXT,gles?es:ca);
    return *ctx!=EGL_NO_CONTEXT&&eglMakeCurrent(*display,EGL_NO_SURFACE,EGL_NO_SURFACE,*ctx);
}
static unsigned clamped(int v,unsigned limit)
{return v<0?0U:(unsigned)v>=limit?limit-1U:(unsigned)v;}
static uint16_t code(unsigned plane,unsigned x,unsigned y)
{return (uint16_t)((x*379U+y*173U+plane*1249U)%4096U);}
static int budget(void)
{
    unsigned long long limit=0,current=0,swap=1;
    const char *names[]={"/sys/fs/cgroup/memory.max","/sys/fs/cgroup/memory.current","/sys/fs/cgroup/memory.swap.max"};
    unsigned long long *values[]={&limit,&current,&swap};
    for(unsigned i=0;i<3;i++){
        FILE *f=fopen(names[i],"r");
        if(!f)return 0;
        int read=fscanf(f,"%llu",values[i]);fclose(f);if(read!=1)return 0;
    }
    const unsigned long long reserve=UINT64_C(436207616);
    fprintf(stderr,"packed-probe budget limit=%llu current=%llu conservative_reserve=%llu swap_max=%llu\n",limit,current,reserve,swap);
    return limit==UINT64_C(536870912)&&swap==0&&current<=limit-reserve;
}
static int compare(pl_gpu gpu,unsigned width,unsigned height,const char *checkpoint,
                   unsigned long long *compared,unsigned *failure_checks,unsigned *packet_words)
{
    if(width!=3840||height!=2160)return 0;
    int okay=0;const char *phase="allocate";FILE *baseline=NULL;
    const char *mode=getenv("YB_PLANAR_PROBE_GLES");
    const int gles=mode&&!strcmp(mode,"1");
    GLuint read_framebuffer=0;GLint saved_read=0;int read_bound=0;
    struct dvbridge_renderer *renderer=NULL;pl_tex tex[5]={0};
    uint16_t *integer_row=calloc(width,sizeof(uint16_t));
    float *float_row=calloc((size_t)width*4,sizeof(float));
    uint8_t *row=calloc((size_t)width*4,1),*saved=calloc((size_t)width*4,1);
    uint32_t packets[512];unsigned count=0;
    PFNGLGETTEXTURESUBIMAGEPROC read=(PFNGLGETTEXTURESUBIMAGEPROC)eglGetProcAddress("glGetTextureSubImage");
    PFNGLGETERRORPROC error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");
    PFNGLGENFRAMEBUFFERSPROC gen_framebuffers=(PFNGLGENFRAMEBUFFERSPROC)eglGetProcAddress("glGenFramebuffers");
    PFNGLBINDFRAMEBUFFERPROC bind_framebuffer=(PFNGLBINDFRAMEBUFFERPROC)eglGetProcAddress("glBindFramebuffer");
    PFNGLFRAMEBUFFERTEXTURE2DPROC framebuffer_texture=(PFNGLFRAMEBUFFERTEXTURE2DPROC)eglGetProcAddress("glFramebufferTexture2D");
    PFNGLCHECKFRAMEBUFFERSTATUSPROC check_framebuffer=(PFNGLCHECKFRAMEBUFFERSTATUSPROC)eglGetProcAddress("glCheckFramebufferStatus");
    PFNGLREADPIXELSPROC read_pixels=(PFNGLREADPIXELSPROC)eglGetProcAddress("glReadPixels");
    PFNGLREADBUFFERPROC read_buffer=(PFNGLREADBUFFERPROC)eglGetProcAddress("glReadBuffer");
    PFNGLGETINTEGERVPROC get_integer=(PFNGLGETINTEGERVPROC)eglGetProcAddress("glGetIntegerv");
    PFNGLDELETEFRAMEBUFFERSPROC delete_framebuffers=(PFNGLDELETEFRAMEBUFFERSPROC)eglGetProcAddress("glDeleteFramebuffers");
    if(!integer_row||!float_row||!row||!saved||(!gles&&!read)||!error)goto done;
    if(gles&&(!gen_framebuffers||!bind_framebuffer||!framebuffer_texture||!check_framebuffer||
              !read_pixels||!read_buffer||!get_integer||!delete_framebuffers))goto done;
    phase="formats";
    pl_fmt floating=pl_find_named_fmt(gpu,"rgba32f"),integer=pl_find_named_fmt(gpu,"r16u"),packed=pl_find_named_fmt(gpu,"rgba8");
    if(!floating||!integer||!packed)goto done;
    phase="textures";
    tex[0]=pl_tex_create(gpu,pl_tex_params(.w=width,.h=height,.format=floating,.sampleable=true,.host_writable=true));
    tex[4]=pl_tex_create(gpu,pl_tex_params(.w=width,.h=height,.format=packed,.sampleable=true,.renderable=true));
    for(unsigned c=0;c<3;c++){
        unsigned w=c?width/2:width,h=c?height/2:height;
        tex[c+1]=pl_tex_create(gpu,pl_tex_params(.w=w,.h=h,.format=integer,.sampleable=true,.host_writable=true));
        if(!tex[c+1])goto done;
        for(unsigned y=0;y<h;y++){
            for(unsigned x=0;x<w;x++)integer_row[x]=code(c,x,y);
            if(!pl_tex_upload(gpu,pl_tex_transfer_params(.tex=tex[c+1],.rc={0,(int)y,0,(int)w,(int)y+1,1},.ptr=integer_row)))goto done;
            if(y%64U==63U)pl_gpu_finish(gpu);
        }
    }
    if(!tex[0]||!tex[4])goto done;
    phase="oracle";
    for(unsigned y=0;y<height;y++){
        for(unsigned x=0;x<width;x++){
            float_row[x*4]=(float)code(0,x,y)/4096.0f;
            for(unsigned c=1;c<3;c++){
                unsigned w=width/2,h=height/2,fx=x%2,fy=y%2?1U:3U;
                int firstx=(int)(x/2),firsty=(int)(y/2)-(y%2?0:1);
                unsigned x0=clamped(firstx,w),x1=clamped(firstx+1,w),y0=clamped(firsty,h),y1=clamped(firsty+1,h);
                uint32_t a=code(c,x0,y0),b=code(c,x0,y1),v=code(c,x1,y0),d=code(c,x1,y1);
                uint32_t numerator=a*(4U-fy)*(2U-fx)+b*fy*(2U-fx)+v*(4U-fy)*fx+d*fy*fx;
                float_row[x*4+c]=(float)numerator/32768.0f;
            }
            float_row[x*4+3]=1;
        }
        if(!pl_tex_upload(gpu,pl_tex_transfer_params(.tex=tex[0],.rc={0,(int)y,0,(int)width,(int)y+1,1},.ptr=float_row)))goto done;
        if(y%64U==63U)pl_gpu_finish(gpu);
    }
    pl_gpu_finish(gpu);
    phase="renderer-create";renderer=dvbridge_renderer_create(gpu);if(!renderer)goto done;
    dvbridge_renderer_set_ipt_offset(renderer,(float[3]){-5.07f,-7.94f,3.62f});
    struct fixture f;metadata(&f);
    struct dvbridge_geometry geometry={(int)width,(int)height,0,0,(int)width,(int)height};
    struct dvbridge_native_colour_association a={.version=1,.width=width,.height=height,
        .enhancement_width=width/2,.enhancement_height=height/2,.vaapi_p010_admitted=1,
        .unrotated=1,.reconstructed_depth=12,.bl_pts=100,.el_pts=100,.timebase_num=1,
        .timebase_den=1000,.expected_frame_id={1},.reconstructed_frame_id={1},
        .presentation_pts=100,.enhancement_presentation_pts=100};
    struct dvbridge_native_planar native={.textures={tex[1],tex[2],tex[3]},
        .width=width,.height=height,.output_depth=12,.sampling_contract=1};
    phase="exclusive-baseline";baseline=fopen(checkpoint,"wb+x");if(!baseline)goto done;
    for(unsigned route=0;route<3;route++){
        phase=route==1?"render-planar-packed":"render-float-packed";
        int rendered=route==1?dvbridge_render_native_planar_packed(renderer,&a,&native,&f,sizeof(f),geometry,tex[4],true):
            dvbridge_render_native_reconstructed_packed(renderer,&a,tex[0],&f,sizeof(f),geometry,tex[4],true);
        if(!rendered)goto done;
        unsigned current_count=0;
        const uint32_t *current=dvbridge_packets(dvbridge_render_candidate(renderer),&current_count);
        if(!current||!current_count||current_count>4)goto done;
        if(!route){count=current_count;memcpy(packets,current,(size_t)count*128U*sizeof(uint32_t));}
        else if(current_count!=count||memcmp(packets,current,(size_t)count*128U*sizeof(uint32_t)))goto done;
        else *packet_words+=count*128U;
        pl_gpu_finish(gpu);
        GLuint texture=pl_opengl_unwrap(gpu,tex[4],NULL,NULL,NULL);
        if(!texture)goto done;
        if(gles){
            get_integer(GL_READ_FRAMEBUFFER_BINDING,&saved_read);
            if(!read_framebuffer)gen_framebuffers(1,&read_framebuffer);
            if(!read_framebuffer)goto done;
            bind_framebuffer(GL_READ_FRAMEBUFFER,read_framebuffer);read_bound=1;
            framebuffer_texture(GL_READ_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture,0);
            read_buffer(GL_COLOR_ATTACHMENT0);
            if(check_framebuffer(GL_READ_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE||error()!=GL_NO_ERROR)goto done;
        }
        if(route&&fseek(baseline,0,SEEK_SET))goto done;
        phase=route?"compare-all-bytes":"save-all-bytes";
        for(unsigned y=0;y<height;y++){
            if(gles)read_pixels(0,(GLint)y,(GLsizei)width,1,GL_RGBA,GL_UNSIGNED_BYTE,row);
            else read(texture,0,0,(GLint)y,0,(GLsizei)width,1,1,GL_RGBA,GL_UNSIGNED_BYTE,(GLsizei)(width*4U),row);
            if(error()!=GL_NO_ERROR)goto done;
            if(!route){if(fwrite(row,(size_t)width*4,1,baseline)!=1)goto done;}
            else{
                if(fread(saved,(size_t)width*4,1,baseline)!=1)goto done;
                if(memcmp(saved,row,(size_t)width*4)){
                    for(unsigned x=0;x<width*4;x++)if(saved[x]!=row[x]){
                        fprintf(stderr,"literal mismatch route=%u y=%u byte=%u baseline=%u actual=%u\n",route,y,x,saved[x],row[x]);break;
                    }
                    goto done;
                }
                *compared+=(unsigned long long)width*4U;
            }
        }
        if(read_bound){bind_framebuffer(GL_READ_FRAMEBUFFER,(GLuint)saved_read);read_bound=0;}
        if(!route&&fflush(baseline))goto done;
    }
    phase="reject";native.sampling_contract=0;
    if(dvbridge_render_native_planar_packed(renderer,&a,&native,&f,sizeof(f),geometry,tex[4],true))goto done;
    (*failure_checks)++;native.sampling_contract=1;a.el_pts++;
    if(dvbridge_render_native_planar_packed(renderer,&a,&native,&f,sizeof(f),geometry,tex[4],true))goto done;
    (*failure_checks)++;
    okay=1;
done:
    if(read_bound)bind_framebuffer(GL_READ_FRAMEBUFFER,(GLuint)saved_read);
    if(read_framebuffer)delete_framebuffers(1,&read_framebuffer);
    fprintf(stderr,"planar-packed-probe phase=%s complete=%d compared_bytes=%llu gl_error=0x%x egl_error=0x%x\n",
        phase,okay,*compared,error?error():0U,(unsigned)eglGetError());
    if(baseline&&fclose(baseline))okay=0;
    dvbridge_renderer_destroy(renderer);
    for(unsigned i=0;i<5;i++)pl_tex_destroy(gpu,&tex[i]);
    free(integer_row);free(float_row);free(row);free(saved);return okay;
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
        struct dvbridge_geometry g={3840,2160,0,0,3840,2160};
        struct dvbridge_candidate *candidate=owner?dvbridge_prepare(owner,&f,sizeof(f),100,g,false):NULL;
        int prepared=candidate!=NULL;
        dvbridge_candidate_destroy(candidate);dvbridge_destroy(owner);
        printf("{\"metadata_map\":%s,\"metadata_prepare\":%s,\"gpu_attempted\":false}\n",
               mapped?"true":"false",prepared?"true":"false");
        return mapped&&prepared?0:1;
    }
    if(argc!=3&&argc!=5)return 2;
    unsigned width=3840,height=2160;
    if(argc==5) {
        char *end=NULL;unsigned long w=strtoul(argv[3],&end,10);
        if(!*argv[3]||*end||w!=3840)return 2;
        unsigned long h=strtoul(argv[4],&end,10);
        if(!*argv[4]||*end||h!=2160)return 2;
        width=(unsigned)w;height=(unsigned)h;
    }
    EGLDisplay display=EGL_NO_DISPLAY;EGLContext ctx=EGL_NO_CONTEXT;
    pl_opengl gl=NULL;pl_log log=NULL;int okay=0,cleanup=1;unsigned long long compared=0;unsigned failures=0,packet_words=0;
    if(!budget()||!context(argv[1],&display,&ctx))goto done;
    PFNGLGETSTRINGPROC get_string=(PFNGLGETSTRINGPROC)eglGetProcAddress("glGetString");
    if(!get_string)goto done;
    fprintf(stderr,"packed-probe actual graphics version=%s\n",(const char *)get_string(GL_VERSION));
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
    printf("{\"complete\":%s,\"cleanup_complete\":%s,\"transport_bytes_bit_compared\":%llu,\"packet_words_bit_compared\":%u,\"failure_checks\":%u,\"synthetic_source_size\":[%u,%u],\"full_output_size\":[3840,2160]}\n",
        okay?"true":"false",cleanup?"true":"false",compared,packet_words,failures,width,height);
    return okay&&cleanup?0:1;
}
