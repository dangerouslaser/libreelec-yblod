#define _POSIX_C_SOURCE 200809L
/* Standalone tiny synthetic guide/phase probe. EGL lifecycle copied from the
 * reviewed colour runner; no generic rendering framework or playback change. */
#include "native_gpu_preparation.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
enum { CASES=11 };
struct prep_case {unsigned operation,location,pattern;uint16_t input[64],expected[32],actual[32];uint32_t expected_status[3],actual_status[3];unsigned words;};
static struct prep_case cases[CASES];
static unsigned busy_submit_checks,pending_destroy_checks;
static int floor128(int n) {return n>=0?n/128:-1-(-(n+1))/128;}
static unsigned clamp_index(int p,unsigned extent) {return p<0?0u:(unsigned)p>=extent?extent-1u:(unsigned)p;}
static int native_at(const struct prep_case *c,int x,int y,unsigned channel)
{
    unsigned width=c->operation?4u:8u,height=c->operation?4u:8u,channels=c->operation?2u:1u;
    return c->input[(clamp_index(y,height)*width+clamp_index(x,width))*channels+channel]>>6;
}
static void prepare(void)
{
    for(unsigned i=0;i<CASES;++i) {
        struct prep_case *c=&cases[i];
        c->operation=i<3?0u:i<7?1u:2u;c->location=i<3?0u:(i-3u)%2u;c->pattern=i<3?i:(i<7?(i-3u)/2u:(i-5u)/2u);
        unsigned width=c->operation?4u:8u,height=c->operation?4u:8u,channels=c->operation?2u:1u;
        for(unsigned y=0;y<height;++y) for(unsigned x=0;x<width;++x) for(unsigned k=0;k<channels;++k) {
            unsigned value=c->pattern==0?(64u+37u*x+83u*y+127u*k)%1024u:c->pattern==1?(x==width/2u&&y==height/2u?1023u:0u):((x+y+k)%2u?1023u:0u);
            c->input[(y*width+x)*channels+k]=(uint16_t)(value<<6);
        }
        c->words=c->operation?32u:16u;
        for(unsigned y=0;y<4;++y) for(unsigned x=0;x<4;++x) for(unsigned k=0;k<(c->operation?2u:1u);++k) {
            int result;
            if(!c->operation) {
                int row[2];
                for(unsigned dy=0;dy<2;++dy) row[dy]=(native_at(c,(int)(2u*x)-1,(int)(2u*y+dy),0)+2*native_at(c,(int)(2u*x),(int)(2u*y+dy),0)+native_at(c,(int)(2u*x)+1,(int)(2u*y+dy),0)+2)/4;
                result=(row[0]+row[1]+1)/2;
            } else if(!c->location) result=native_at(c,(int)x,(int)y,k);
            else if(c->operation==1) result=(3*native_at(c,(int)x,(int)y,k)+native_at(c,(int)x,(int)y+1,k)+2)/4;
            else result=floor128(-9*native_at(c,(int)x,(int)y-1,k)+111*native_at(c,(int)x,(int)y,k)+29*native_at(c,(int)x,(int)y+1,k)-3*native_at(c,(int)x,(int)y+2,k)+64);
            if(c->operation) {
                if(result<0) {++c->expected_status[1];result=0;}
                if(result>1023) {++c->expected_status[2];result=1023;}
            }
            c->expected[(y*4u+x)*(c->operation?2u:1u)+k]=(uint16_t)(c->operation?(unsigned)result<<6:(unsigned)result);
        }
    }
}
static int extension(const char *all,const char *wanted)
{
    if(!all) return 0;
    size_t n=strlen(wanted);const char *p=all;
    while((p=strstr(p,wanted))) {if((p==all||p[-1]==' ')&&(p[n]==' '||!p[n])) return 1;p+=n;}return 0;
}
static int node_valid(const char *node)
{
    const char *prefix="/dev/dri/renderD";if(strncmp(node,prefix,strlen(prefix))) return 0;
    const char *n=node+strlen(prefix);return strlen(n)==3&&strspn(n,"0123456789")==3&&atoi(n)>=128&&atoi(n)<=255;
}
static char *shader_read(const char *path)
{
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);struct stat before,after;char *text=NULL;
    if(fd<0) return NULL;
    if(fstat(fd,&before)||!S_ISREG(before.st_mode)||before.st_size<=0||before.st_size>65536) goto done;
    size_t size=(size_t)before.st_size,used=0;text=malloc(size+1);if(!text) goto done;
    while(used<size) {ssize_t n=read(fd,text+used,size-used);if(n<=0) {free(text);text=NULL;goto done;}used+=(size_t)n;}
    if(fstat(fd,&after)||after.st_size!=before.st_size||after.st_ino!=before.st_ino||after.st_dev!=before.st_dev||
        after.st_mtim.tv_sec!=before.st_mtim.tv_sec||after.st_mtim.tv_nsec!=before.st_mtim.tv_nsec||memchr(text,0,size)) {free(text);text=NULL;goto done;}
    text[size]=0;
done:close(fd);return text;
}
struct gl_api {
    PFNGLGETSTRINGPROC GetString;PFNGLGETERRORPROC GetError;PFNGLGETINTEGERVPROC GetIntegerv;
    PFNGLCREATESHADERPROC CreateShader;PFNGLSHADERSOURCEPROC ShaderSource;PFNGLCOMPILESHADERPROC CompileShader;
    PFNGLGETSHADERIVPROC GetShaderiv;PFNGLDELETESHADERPROC DeleteShader;
    PFNGLGETSHADERINFOLOGPROC GetShaderInfoLog;PFNGLGETPROGRAMINFOLOGPROC GetProgramInfoLog;
    PFNGLCREATEPROGRAMPROC CreateProgram;PFNGLATTACHSHADERPROC AttachShader;PFNGLLINKPROGRAMPROC LinkProgram;
    PFNGLGETPROGRAMIVPROC GetProgramiv;PFNGLDELETEPROGRAMPROC DeleteProgram;PFNGLUSEPROGRAMPROC UseProgram;
    PFNGLGENBUFFERSPROC GenBuffers;PFNGLBINDBUFFERPROC BindBuffer;PFNGLBUFFERDATAPROC BufferData;
    PFNGLBINDBUFFERBASEPROC BindBufferBase;PFNGLDELETEBUFFERSPROC DeleteBuffers;PFNGLGETBUFFERSUBDATAPROC GetBufferSubData;
    PFNGLDISPATCHCOMPUTEPROC DispatchCompute;PFNGLMEMORYBARRIERPROC MemoryBarrier;
    PFNGLFENCESYNCPROC FenceSync;PFNGLCLIENTWAITSYNCPROC ClientWaitSync;PFNGLDELETESYNCPROC DeleteSync;
    PFNGLGETUNIFORMLOCATIONPROC GetUniformLocation;PFNGLUNIFORMMATRIX3FVPROC UniformMatrix3fv;
    PFNGLUNIFORM3FVPROC Uniform3fv;PFNGLUNIFORM1IPROC Uniform1i;PFNGLUNIFORM1UIPROC Uniform1ui;
    PFNGLGENTEXTURESPROC GenTextures;PFNGLBINDTEXTUREPROC BindTexture;PFNGLTEXIMAGE2DPROC TexImage2D;
    PFNGLGETTEXIMAGEPROC GetTexImage;PFNGLTEXPARAMETERIPROC TexParameteri;PFNGLDELETETEXTURESPROC DeleteTextures;
    PFNGLBINDIMAGETEXTUREPROC BindImageTexture;PFNGLUNIFORM2UIPROC Uniform2ui;
};
#define LOAD(member,type) do{gl.member=(type)eglGetProcAddress("gl" #member);if(!gl.member)goto cleanup;}while(0)
static yb_gpu_proc api_proc(const char *name,void *opaque) {(void)opaque;return (yb_gpu_proc)eglGetProcAddress(name);}
static uintptr_t api_context(void *opaque) {(void)opaque;return (uintptr_t)eglGetCurrentContext();}
static int execute(const char *node,char *source,char renderer[1024],char version[1024])
{
    int ok=0,fd=-1,initialized=0,current=0;yb_gpu_preparation *api=NULL;EGLDisplay display=EGL_NO_DISPLAY;EGLContext context=EGL_NO_CONTEXT;
    GLuint shader=0,program=0,buffers[2]={0},textures[2]={0};GLsync fence=NULL;struct gl_api gl={0};struct stat requested;
    fd=open(node,O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0||fstat(fd,&requested)||!S_ISCHR(requested.st_mode)||major(requested.st_rdev)!=226||minor(requested.st_rdev)!=(unsigned)atoi(node+strlen("/dev/dri/renderD"))) goto cleanup;
    const char *client=eglQueryString(EGL_NO_DISPLAY,EGL_EXTENSIONS);
    if(eglGetError()!=EGL_SUCCESS||!extension(client,"EGL_EXT_platform_device")||
        !(extension(client,"EGL_EXT_device_base")||(extension(client,"EGL_EXT_device_enumeration")&&extension(client,"EGL_EXT_device_query")))) goto cleanup;
    PFNEGLQUERYDEVICESEXTPROC query_devices=(PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLQUERYDEVICESTRINGEXTPROC device_string=(PFNEGLQUERYDEVICESTRINGEXTPROC)eglGetProcAddress("eglQueryDeviceStringEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform_display=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    PFNEGLQUERYDISPLAYATTRIBEXTPROC display_attribute=(PFNEGLQUERYDISPLAYATTRIBEXTPROC)eglGetProcAddress("eglQueryDisplayAttribEXT");
    if(!query_devices||!device_string||!platform_display||!display_attribute) goto cleanup;
    EGLint count=0,returned=0;EGLDeviceEXT listed[32],selected=EGL_NO_DEVICE_EXT;
    if(!query_devices(0,NULL,&count)||count<1||count>32||!query_devices(count,listed,&returned)||count!=returned) goto cleanup;
    unsigned matches=0;
    for(EGLint i=0;i<count;++i) {
        const char *ext=device_string(listed[i],EGL_EXTENSIONS);
        if(eglGetError()!=EGL_SUCCESS||!extension(ext,"EGL_EXT_device_drm_render_node")||extension(ext,"EGL_MESA_device_software")) continue;
        const char *path=device_string(listed[i],EGL_DRM_RENDER_NODE_FILE_EXT);struct stat candidate;
        if(eglGetError()==EGL_SUCCESS&&path&&!stat(path,&candidate)&&S_ISCHR(candidate.st_mode)&&candidate.st_rdev==requested.st_rdev) {++matches;selected=listed[i];}
    }
    if(matches!=1) goto cleanup;
    display=platform_display(EGL_PLATFORM_DEVICE_EXT,selected,NULL);EGLint egl_major=0,egl_minor=0;
    if(display==EGL_NO_DISPLAY||!eglInitialize(display,&egl_major,&egl_minor)) goto cleanup;
    initialized=1;EGLAttrib device=0;
    if(!display_attribute(display,EGL_DEVICE_EXT,&device)||(EGLDeviceEXT)device!=selected) goto cleanup;
    const char *ext=eglQueryString(display,EGL_EXTENSIONS);
    if(eglGetError()!=EGL_SUCCESS||!extension(ext,"EGL_KHR_surfaceless_context")||!eglBindAPI(EGL_OPENGL_API)) goto cleanup;
    const EGLint config_attributes[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT,EGL_NONE};
    const EGLint context_attributes[]={EGL_CONTEXT_MAJOR_VERSION_KHR,4,EGL_CONTEXT_MINOR_VERSION_KHR,3,EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
    EGLConfig config;EGLint configs_count=0;
    if(!eglChooseConfig(display,config_attributes,&config,1,&configs_count)||configs_count!=1) goto cleanup;
    context=eglCreateContext(display,config,EGL_NO_CONTEXT,context_attributes);
    if(context==EGL_NO_CONTEXT||!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,context)) goto cleanup;
    current=1;
    LOAD(GetString,PFNGLGETSTRINGPROC);LOAD(GetError,PFNGLGETERRORPROC);LOAD(GetIntegerv,PFNGLGETINTEGERVPROC);
    LOAD(CreateShader,PFNGLCREATESHADERPROC);LOAD(ShaderSource,PFNGLSHADERSOURCEPROC);LOAD(CompileShader,PFNGLCOMPILESHADERPROC);LOAD(GetShaderiv,PFNGLGETSHADERIVPROC);LOAD(DeleteShader,PFNGLDELETESHADERPROC);
    LOAD(GetShaderInfoLog,PFNGLGETSHADERINFOLOGPROC);LOAD(GetProgramInfoLog,PFNGLGETPROGRAMINFOLOGPROC);
    LOAD(CreateProgram,PFNGLCREATEPROGRAMPROC);LOAD(AttachShader,PFNGLATTACHSHADERPROC);LOAD(LinkProgram,PFNGLLINKPROGRAMPROC);LOAD(GetProgramiv,PFNGLGETPROGRAMIVPROC);LOAD(DeleteProgram,PFNGLDELETEPROGRAMPROC);LOAD(UseProgram,PFNGLUSEPROGRAMPROC);
    LOAD(GenBuffers,PFNGLGENBUFFERSPROC);LOAD(BindBuffer,PFNGLBINDBUFFERPROC);LOAD(BufferData,PFNGLBUFFERDATAPROC);LOAD(BindBufferBase,PFNGLBINDBUFFERBASEPROC);LOAD(DeleteBuffers,PFNGLDELETEBUFFERSPROC);LOAD(GetBufferSubData,PFNGLGETBUFFERSUBDATAPROC);
    LOAD(DispatchCompute,PFNGLDISPATCHCOMPUTEPROC);LOAD(MemoryBarrier,PFNGLMEMORYBARRIERPROC);LOAD(FenceSync,PFNGLFENCESYNCPROC);LOAD(ClientWaitSync,PFNGLCLIENTWAITSYNCPROC);LOAD(DeleteSync,PFNGLDELETESYNCPROC);
    LOAD(GetUniformLocation,PFNGLGETUNIFORMLOCATIONPROC);LOAD(UniformMatrix3fv,PFNGLUNIFORMMATRIX3FVPROC);LOAD(Uniform3fv,PFNGLUNIFORM3FVPROC);LOAD(Uniform1i,PFNGLUNIFORM1IPROC);LOAD(Uniform1ui,PFNGLUNIFORM1UIPROC);
    LOAD(GenTextures,PFNGLGENTEXTURESPROC);LOAD(BindTexture,PFNGLBINDTEXTUREPROC);LOAD(TexImage2D,PFNGLTEXIMAGE2DPROC);
    LOAD(GetTexImage,PFNGLGETTEXIMAGEPROC);LOAD(TexParameteri,PFNGLTEXPARAMETERIPROC);LOAD(DeleteTextures,PFNGLDELETETEXTURESPROC);
    LOAD(BindImageTexture,PFNGLBINDIMAGETEXTUREPROC);LOAD(Uniform2ui,PFNGLUNIFORM2UIPROC);
    const char *r=(const char *)gl.GetString(GL_RENDERER),*v=(const char *)gl.GetString(GL_VERSION);
    if(!r||!v||!strstr(r,"Intel")||strlen(r)>=1024||strlen(v)>=1024) goto cleanup;
    strcpy(renderer,r);strcpy(version,v);
    GLint max_bindings=0;gl.GetIntegerv(GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS,&max_bindings);if(max_bindings<2) goto cleanup;
    yb_gpu_preparation_create_info info={1,api_proc,api_context,NULL,source,strlen(source)};
    if(yb_gpu_preparation_create(&info,&api)!=YB_GPU_BACKEND_OK) goto cleanup;
    gl.GenTextures(2,textures);
    for(unsigned i=0;i<CASES;++i) {
        struct prep_case *c=&cases[i];uint16_t zeros[64]={0};
        gl.BindTexture(GL_TEXTURE_2D,textures[0]);
        gl.TexImage2D(GL_TEXTURE_2D,0,GL_R16,8,8,0,GL_RED,GL_UNSIGNED_SHORT,c->operation?zeros:c->input);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
        gl.BindTexture(GL_TEXTURE_2D,textures[1]);
        gl.TexImage2D(GL_TEXTURE_2D,0,GL_RG16,4,4,0,GL_RG,GL_UNSIGNED_SHORT,c->operation?c->input:zeros);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
        yb_gpu_preparation_plan p={0};p.version=1;p.width=p.height=8;p.bl_luma_texture=textures[0];p.bl_chroma_texture=textures[1];
        p.phase_filter=c->operation?c->operation:1u;p.chroma_location=c->location;
        p.frame_id[0]=(uint8_t)(i+1u);p.guide_contract_id[0]=2;p.phase_contract_id[0]=3;
        if(yb_gpu_preparation_submit(api,&p)!=YB_GPU_BACKEND_OK) goto cleanup;
        if(yb_gpu_preparation_submit(api,&p)!=YB_GPU_BACKEND_BUSY) goto cleanup;
        ++busy_submit_checks;
        yb_gpu_preparation *pending_handle=api;
        if(yb_gpu_preparation_destroy(&api)!=YB_GPU_BACKEND_BUSY||api!=pending_handle) goto cleanup;
        ++pending_destroy_checks;
        yb_gpu_preparation_output output={0};
        int finished=yb_gpu_preparation_finish(api,0,&output);
        if(finished==YB_GPU_BACKEND_PENDING)finished=yb_gpu_preparation_finish(api,UINT64_C(5000000000),&output);
        if(finished!=YB_GPU_BACKEND_OK||memcmp(output.frame_id,p.frame_id,32)||
           memcmp(output.guide_contract_id,p.guide_contract_id,32)||memcmp(output.phase_contract_id,p.phase_contract_id,32)) goto cleanup;
        c->actual_status[0]=0;c->actual_status[1]=output.phase_below_zero;c->actual_status[2]=output.phase_above_native;
        gl.BindTexture(GL_TEXTURE_2D,c->operation?output.phase_chroma_texture:output.guide_texture);
        gl.GetTexImage(GL_TEXTURE_2D,0,c->operation?GL_RG:GL_RED,GL_UNSIGNED_SHORT,c->actual);
        if(gl.GetError()!=GL_NO_ERROR)goto cleanup;
    }
    if(yb_gpu_preparation_destroy(&api)!=YB_GPU_BACKEND_OK) goto cleanup;
    ok=1;
cleanup:
    if(current) {
        if(fence&&gl.DeleteSync) gl.DeleteSync(fence);
        if(gl.DeleteTextures) gl.DeleteTextures(2,textures);
        if(gl.DeleteBuffers) gl.DeleteBuffers(2,buffers);
        if(program&&gl.DeleteProgram) gl.DeleteProgram(program);
        if(shader&&gl.DeleteShader) gl.DeleteShader(shader);
        if(gl.GetError&&gl.GetError()!=GL_NO_ERROR) ok=0;
        if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT)) ok=0;
    }
    if(context!=EGL_NO_CONTEXT) {
        if(!eglDestroyContext(display,context)) ok=0;
        else if(api&&yb_gpu_preparation_abandon_destroyed_context(&api,1)!=YB_GPU_BACKEND_OK) ok=0;
    }
    if(initialized&&!eglTerminate(display)) ok=0;
    if(fd>=0&&close(fd)) ok=0;
    return ok;
}
int main(int argc,char **argv)
{
    if(argc==2&&!strcmp(argv[1],"--cpu-oracle")) {
        prepare();printf("{\"schema\":\"yblod.preparation-cpu-oracle.v1\",\"gpu_executed\":false,\"cases\":[");
        for(unsigned i=0;i<CASES;++i) {
            struct prep_case *c=&cases[i];printf("%s{\"operation\":%u,\"chroma_location\":%u,\"pattern\":%u,\"expected_status\":[%u,%u,%u],\"expected_words\":[",i?",":"",c->operation,c->location,c->pattern,c->expected_status[0],c->expected_status[1],c->expected_status[2]);
            for(unsigned k=0;k<c->words;++k) {printf("%s%u",k?",":"",c->expected[k]);}printf("]}");
        }
        printf("]}\n");return 0;
    }
    if(argc!=3) {fprintf(stderr,"usage: native_gpu_preparation_api_runner DEVICE SHADER | --cpu-oracle\n");return 1;}
    if(!node_valid(argv[1])) {fprintf(stderr,"explicit render node required\n");return 1;}
    prepare();char *source=shader_read(argv[2]);if(!source) {fprintf(stderr,"bounded regular shader required\n");return 1;}
    char renderer[1024]={0},version[1024]={0};int ok=execute(argv[1],source,renderer,version);free(source);
    if(!ok) {fprintf(stderr,"bounded preparation probe failed\n");return 1;}
    printf("{\"schema\":\"yblod.gpu-preparation-api-synthetic-probe.v1\",\"complete\":true,\"cleanup_complete\":true,\"native_cpu_oracle_first\":true,\"renderer\":");
    /* This source reports public synthetic storage words only. */
    putchar('"');fputs(renderer,stdout);putchar('"');printf(",\"cases\":[");
    unsigned mismatches=0,status_mismatches=0,values=0;
    for(unsigned i=0;i<CASES;++i) {
        struct prep_case *c=&cases[i];printf("%s{\"operation\":%u,\"chroma_location\":%u,\"pattern\":%u,\"word_mismatches\":",i?",":"",c->operation,c->location,c->pattern);
        unsigned bad=0;for(unsigned k=0;k<c->words;++k) if(c->actual[k]!=c->expected[k]) ++bad;
        mismatches+=bad;values+=c->words;printf("%u,\"expected_status\":[%u,%u,%u],\"actual_status\":[%u,%u,%u],\"expected_words\":[",bad,c->expected_status[0],c->expected_status[1],c->expected_status[2],c->actual_status[0],c->actual_status[1],c->actual_status[2]);
        for(unsigned k=0;k<3;++k) if(c->expected_status[k]!=c->actual_status[k]) ++status_mismatches;
        for(unsigned k=0;k<c->words;++k) {printf("%s%u",k?",":"",c->expected[k]);}printf("],\"actual_words\":[");
        for(unsigned k=0;k<c->words;++k) {printf("%s%u",k?",":"",c->actual[k]);}printf("]}");
    }
    printf("],\"compared_words\":%u,\"word_mismatches\":%u,\"status_mismatches\":%u,\"busy_submit_checks\":%u,\"pending_destroy_checks\":%u,\"playback_tested\":false}\n",values,mismatches,status_mismatches,busy_submit_checks,pending_destroy_checks);
    return mismatches||status_mismatches?1:0;
}
