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
static int compare(pl_gpu gpu,unsigned width,unsigned height,const char *checkpoint,
                   unsigned long long *compared,unsigned *failure_checks)
{
    int okay=0; const char *phase="row-allocation"; FILE *file=NULL; struct dvbridge_renderer *renderer=NULL;
    pl_tex tex[5]={0}; float *row=calloc(3840U*4U,sizeof(float));
    float *saved=calloc(3840U*4U,sizeof(float)); uint32_t *packets=NULL;
    unsigned count=0,margins[4]={0};
    PFNGLGETTEXTURESUBIMAGEPROC read=(PFNGLGETTEXTURESUBIMAGEPROC)eglGetProcAddress("glGetTextureSubImage");
    PFNGLGETERRORPROC error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");
    if(!row||!saved||!read||!error)goto done;
    phase="formats";
    pl_fmt rgba=pl_find_named_fmt(gpu,"rgba32f"),r16=pl_find_named_fmt(gpu,"r16"),rg16=pl_find_named_fmt(gpu,"rg16");
    if(!rgba||!r16||!rg16)goto done;
    phase="textures";
    tex[0]=pl_tex_create(gpu,pl_tex_params(.w=width,.h=height,.format=rgba,.sampleable=true,.host_writable=true));
    for(unsigned i=1;i<5;i++)tex[i]=pl_tex_create(gpu,pl_tex_params(
        .w=i==1?width:i==4?width/4:width/2,.h=i==1?height:i==4?height/4:height/2,
        .format=i%2?r16:rg16,.sampleable=true));
    for(unsigned i=0;i<5;i++)if(!tex[i])goto done;
    phase="upload";
    for(unsigned y=0;y<height;y++) {
        for(unsigned x=0;x<width;x++)for(unsigned c=0;c<4;c++)
            row[x*4+c]=c==3?1.0f:(float)((x*37U+y*13U+c*211U)%3072U)/4096.0f;
        if(!pl_tex_upload(gpu,pl_tex_transfer_params(.tex=tex[0],.rc={0,(int)y,0,(int)width,(int)y+1,1},.ptr=row)))goto done;
    }
    phase="renderer-create";
    renderer=dvbridge_renderer_create(gpu);if(!renderer)goto done;
    struct fixture f;metadata(&f);
    phase="metadata-map";
    struct dvbridge_color mapped;
    if(!dvbridge_map_color(&mapped,&f,sizeof(f),true))goto done;
    struct pl_frame el={.num_planes=2,.planes={
        {.texture=tex[3],.components=1,.component_mapping={0}},
        {.texture=tex[4],.components=2,.component_mapping={1,2}}},
        .crop={0,0,(float)width/2,(float)height/2},
        .repr={.bits={.sample_depth=16,.color_depth=10,.bit_shift=6}}};
    struct pl_frame bl={.num_planes=2,.planes={
        {.texture=tex[1],.components=1,.component_mapping={0}},
        {.texture=tex[2],.components=2,.component_mapping={1,2}}},
        .repr={.bits={.sample_depth=16,.color_depth=10,.bit_shift=6}},
        .crop={0,0,(float)width,(float)height},.enhancement_layer=&el};
    struct dvbridge_geometry geometry={(int)width,(int)height,0,0,(int)width,(int)height};
    struct dvbridge_native_colour_association a={.version=1,.width=width,.height=height,
        .enhancement_width=width/2,.enhancement_height=height/2,.vaapi_p010_admitted=1,
        .unrotated=1,.reconstructed_depth=12,.bl_pts=100,.el_pts=100,.timebase_num=1,
        .timebase_den=1000,.expected_frame_id={1},.reconstructed_frame_id={1},
        .presentation_pts=100,.enhancement_presentation_pts=100};
    phase="metadata-prepare";
    struct dvbridge_context *test_context=dvbridge_create();
    if(!test_context)goto done;
    struct dvbridge_candidate *test_candidate=dvbridge_prepare(test_context,&f,sizeof(f),100,geometry,false);
    if(!test_candidate){dvbridge_destroy(test_context);goto done;}
    dvbridge_candidate_destroy(test_candidate);dvbridge_destroy(test_context);
    phase="checkpoint-create";
    file=fopen(checkpoint,"wb+x");if(!file)goto done;
    for(unsigned route=0;route<2;route++) {
        phase=route?"render-new":"render-old";
        int rendered=route?dvbridge_render_native_reconstructed_rgb(renderer,&a,tex[0],&f,sizeof(f),geometry):
            dvbridge_render_reconstructed_rgb(renderer,&bl,tex[0],&f,sizeof(f),100,100,geometry);
        if(!rendered)goto done;
        phase=route?"candidate-new":"candidate-old";
        const struct dvbridge_candidate *candidate=dvbridge_render_candidate(renderer);
        unsigned current_count=0,current_margins[4];
        const uint32_t *current=dvbridge_packets(candidate,&current_count);
        if(!current||!dvbridge_active_area(candidate,current_margins))goto done;
        if(!route) {
            count=current_count;packets=malloc((size_t)count*sizeof(*packets));if(!packets)goto done;
            memcpy(packets,current,(size_t)count*sizeof(*packets));memcpy(margins,current_margins,sizeof(margins));
        } else if(current_count!=count||memcmp(packets,current,(size_t)count*sizeof(*packets))||memcmp(margins,current_margins,sizeof(margins)))goto done;
        phase=route?"output-new":"output-old";
        pl_gpu_finish(gpu);
        GLuint texture=pl_opengl_unwrap(gpu,dvbridge_render_texture(renderer),NULL,NULL,NULL);
        if(!texture)goto done;
        if(route&&fseek(file,0,SEEK_SET))goto done;
        phase=route?"row-compare":"row-save";
        for(unsigned y=0;y<2160;y++) {
            read(texture,0,0,(GLint)y,0,3840,1,1,GL_RGBA,GL_FLOAT,61440,row);
            if(error()!=GL_NO_ERROR)goto done;
            if(!route) {if(fwrite(row,61440,1,file)!=1)goto done;}
            else {if(fread(saved,61440,1,file)!=1||memcmp(row,saved,61440))goto done;*compared+=15360;}
        }
        if(!route&&fflush(file))goto done;
    }
    phase="reject-pairing";
    a.el_pts++;
    if(dvbridge_render_native_reconstructed_rgb(renderer,&a,tex[0],&f,sizeof(f),geometry)||dvbridge_render_texture(renderer))goto done;
    (*failure_checks)++;a.el_pts--;
    phase="reject-metadata";
    if(dvbridge_render_native_reconstructed_rgb(renderer,&a,tex[0],&f,0,geometry)||dvbridge_render_texture(renderer))goto done;
    (*failure_checks)++;
    okay=1;
done:
    fprintf(stderr,"colour-entry-probe phase=%s complete=%d compared=%llu gl_error=0x%x egl_error=0x%x\n",
            phase,okay,*compared,error?error():0U,(unsigned)eglGetError());
    if(file&&fclose(file))okay=0;
    dvbridge_renderer_destroy(renderer);for(unsigned i=0;i<5;i++)pl_tex_destroy(gpu,&tex[i]);
    free(row);free(saved);free(packets);return okay;
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
        if(!*argv[3]||*end||w<4||w>3840||w%4)return 2;
        unsigned long h=strtoul(argv[4],&end,10);
        if(!*argv[4]||*end||h<4||h>2160||h%4)return 2;
        width=(unsigned)w;height=(unsigned)h;
    }
    EGLDisplay display=EGL_NO_DISPLAY;EGLContext ctx=EGL_NO_CONTEXT;
    pl_opengl gl=NULL;pl_log log=NULL;int okay=0,cleanup=1;unsigned long long compared=0;unsigned failures=0;
    if(!context(argv[1],&display,&ctx))goto done;
    log=pl_log_create(PL_API_VER,pl_log_params(.log_cb=gpu_log,.log_level=PL_LOG_DEBUG));
    if(!log)goto done;
    gl=pl_opengl_create(log,pl_opengl_params(.get_proc_addr=(pl_voidfunc_t(*)(const char*))eglGetProcAddress,
        .egl_display=display,.egl_context=ctx,.allow_software=false));
    if(!gl)goto done;
    okay=compare(gl->gpu,width,height,argv[2],&compared,&failures);
done:
    pl_opengl_destroy(&gl);
    pl_log_destroy(&log);
    if(display!=EGL_NO_DISPLAY) {
        if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT))cleanup=0;
        if(ctx!=EGL_NO_CONTEXT&&!eglDestroyContext(display,ctx))cleanup=0;
        if(!eglTerminate(display))cleanup=0;
    }
    printf("{\"complete\":%s,\"cleanup_complete\":%s,\"rgb_float_values_bit_compared\":%llu,\"failure_checks\":%u,\"synthetic_source_size\":[%u,%u],\"full_output_size\":[3840,2160]}\n",
        okay?"true":"false",cleanup?"true":"false",compared,failures,width,height);
    return okay&&cleanup?0:1;
}
