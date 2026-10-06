/* Public synthetic desktop GL -> GLES sibling test; owns only its own display. */
#define _POSIX_C_SOURCE 200809L
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include "native_egl_output_bridge.h"
#define LOAD(T,V,N) T V=(T)eglGetProcAddress(N);if(!V)goto done
static int retained_resources;
static int same_binding(const yb_egl_binding *b)
{
    return b->display==(uintptr_t)eglGetCurrentDisplay() &&
        b->context==(uintptr_t)eglGetCurrentContext() &&
        b->draw==(uintptr_t)eglGetCurrentSurface(EGL_DRAW) &&
        b->read==(uintptr_t)eglGetCurrentSurface(EGL_READ) && b->api==(uint32_t)eglQueryAPI();
}
static int run_format(EGLDisplay display,EGLContext producer,EGLContext consumer,int integer)
{
    GLuint texture=0,buffer=0,shader=0,program=0;
    yb_egl_output_bridge *bridge=NULL;
    int success=0;
    LOAD(PFNGLGENTEXTURESPROC,gen_texture,"glGenTextures");
    LOAD(PFNGLBINDTEXTUREPROC,bind_texture,"glBindTexture");
    LOAD(PFNGLTEXIMAGE2DPROC,image,"glTexImage2D");
    LOAD(PFNGLTEXPARAMETERIPROC,param,"glTexParameteri");
    LOAD(PFNGLDELETETEXTURESPROC,delete_texture,"glDeleteTextures");
    LOAD(PFNGLGETERRORPROC,error,"glGetError");
    LOAD(PFNGLCREATESHADERPROC,create_shader,"glCreateShader");
    LOAD(PFNGLSHADERSOURCEPROC,shader_source,"glShaderSource");
    LOAD(PFNGLCOMPILESHADERPROC,compile_shader,"glCompileShader");
    LOAD(PFNGLGETSHADERIVPROC,shader_status,"glGetShaderiv");
    LOAD(PFNGLCREATEPROGRAMPROC,create_program,"glCreateProgram");
    LOAD(PFNGLATTACHSHADERPROC,attach_shader,"glAttachShader");
    LOAD(PFNGLLINKPROGRAMPROC,link_program,"glLinkProgram");
    LOAD(PFNGLGETPROGRAMIVPROC,program_status,"glGetProgramiv");
    LOAD(PFNGLUSEPROGRAMPROC,use_program,"glUseProgram");
    LOAD(PFNGLGENBUFFERSPROC,gen_buffer,"glGenBuffers");
    LOAD(PFNGLBINDBUFFERPROC,bind_buffer,"glBindBuffer");
    LOAD(PFNGLBUFFERDATAPROC,buffer_data,"glBufferData");
    LOAD(PFNGLBINDBUFFERBASEPROC,bind_base,"glBindBufferBase");
    LOAD(PFNGLDISPATCHCOMPUTEPROC,dispatch,"glDispatchCompute");
    LOAD(PFNGLMEMORYBARRIERPROC,barrier,"glMemoryBarrier");
    LOAD(PFNGLMAPBUFFERRANGEPROC,map,"glMapBufferRange");
    LOAD(PFNGLUNMAPBUFFERPROC,unmap,"glUnmapBuffer");
    LOAD(PFNGLDELETEBUFFERSPROC,delete_buffer,"glDeleteBuffers");
    LOAD(PFNGLDELETEPROGRAMPROC,delete_program,"glDeleteProgram");
    LOAD(PFNGLDELETESHADERPROC,delete_shader,"glDeleteShader");
    LOAD(PFNGLFENCESYNCPROC,fence,"glFenceSync");
    LOAD(PFNGLCLIENTWAITSYNCPROC,wait,"glClientWaitSync");
    LOAD(PFNGLDELETESYNCPROC,delete_sync,"glDeleteSync");
    uint32_t expected[64];GLfloat floats[64];uint16_t shorts[64];
    for(unsigned i=0;i<64;++i) {
        floats[i]=(GLfloat)(i+1u)/64.0f;shorts[i]=(uint16_t)(17u+i*997u);
        if(integer)expected[i]=shorts[i];else memcpy(&expected[i],&floats[i],sizeof(expected[i]));
    }
    if(!eglBindAPI(EGL_OPENGL_API)||!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,producer))goto done;
    gen_texture(1,&texture);bind_texture(GL_TEXTURE_2D,texture);
    param(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);param(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    image(GL_TEXTURE_2D,0,integer?GL_RGBA16UI:GL_RGBA32F,4,4,0,
          integer?GL_RGBA_INTEGER:GL_RGBA,integer?GL_UNSIGNED_SHORT:GL_FLOAT,integer?(void*)shorts:(void*)floats);
    if(error()!=GL_NO_ERROR)goto done;
    if(!eglBindAPI(EGL_OPENGL_ES_API)||!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,consumer))goto done;
    yb_egl_binding original={(uintptr_t)display,(uintptr_t)consumer,0,0,EGL_OPENGL_ES_API};
    int status=yb_egl_output_bridge_create((uintptr_t)producer,texture,&bridge);
    if(status!=YB_EGL_BRIDGE_OK || !same_binding(&original))goto done;
    const char *float_source="#version 310 es\nprecision highp float;precision highp int;layout(local_size_x=4,local_size_y=4)in;layout(binding=0)uniform highp sampler2D source;layout(std430,binding=0)buffer O{uint words[];};void main(){ivec2 p=ivec2(gl_GlobalInvocationID.xy);uvec4 v=floatBitsToUint(texelFetch(source,p,0));int i=p.y*16+p.x*4;words[i]=v.r;words[i+1]=v.g;words[i+2]=v.b;words[i+3]=v.a;}";
    const char *int_source="#version 310 es\nprecision highp float;precision highp int;layout(local_size_x=4,local_size_y=4)in;layout(binding=0)uniform highp usampler2D source;layout(std430,binding=0)buffer O{uint words[];};void main(){ivec2 p=ivec2(gl_GlobalInvocationID.xy);uvec4 v=texelFetch(source,p,0);int i=p.y*16+p.x*4;words[i]=v.r;words[i+1]=v.g;words[i+2]=v.b;words[i+3]=v.a;}";
    const char *code=integer?int_source:float_source;
    shader=create_shader(GL_COMPUTE_SHADER);shader_source(shader,1,&code,NULL);compile_shader(shader);GLint ok=0;shader_status(shader,GL_COMPILE_STATUS,&ok);if(!ok)goto done;
    program=create_program();attach_shader(program,shader);link_program(program);program_status(program,GL_LINK_STATUS,&ok);if(!ok)goto done;
    use_program(program);bind_texture(GL_TEXTURE_2D,yb_egl_output_bridge_texture(bridge));
    uint32_t observed[64];for(unsigned i=0;i<64;++i)observed[i]=UINT32_MAX;
    gen_buffer(1,&buffer);bind_buffer(GL_SHADER_STORAGE_BUFFER,buffer);buffer_data(GL_SHADER_STORAGE_BUFFER,(GLsizeiptr)sizeof(observed),observed,GL_DYNAMIC_READ);bind_base(GL_SHADER_STORAGE_BUFFER,0,buffer);
    dispatch(1,1,1);barrier(GL_BUFFER_UPDATE_BARRIER_BIT);
    GLsync sync=fence(GL_SYNC_GPU_COMMANDS_COMPLETE,0);if(!sync)goto done;
    GLenum waited=GL_TIMEOUT_EXPIRED;
    for(unsigned i=0;i<5&&waited==GL_TIMEOUT_EXPIRED;++i)waited=wait(sync,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(1000000000));
    delete_sync(sync);if(waited!=GL_ALREADY_SIGNALED&&waited!=GL_CONDITION_SATISFIED)goto done;
    void *mapped=map(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)sizeof(observed),GL_MAP_READ_BIT);if(!mapped)goto done;
    memcpy(observed,mapped,sizeof(observed));if(!unmap(GL_SHADER_STORAGE_BUFFER)||error()!=GL_NO_ERROR)goto done;
    if(memcmp(expected,observed,sizeof(expected)))goto done;
    if(yb_egl_output_bridge_release_timed(&bridge,UINT64_C(5000000000))!=0||bridge||!same_binding(&original))goto done;
    success=1;
done:
    /* A retained bridge means outstanding work/restore failure: do not release
     * producer storage or consumer context; process failure exits without reuse. */
    if(bridge) {retained_resources=1;fprintf(stderr,"retained bridge; no producer reuse\n");return 0;}
    if(display!=EGL_NO_DISPLAY&&consumer!=EGL_NO_CONTEXT&&eglBindAPI(EGL_OPENGL_ES_API)&&eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,consumer)) {
        if(buffer&&delete_buffer)delete_buffer(1,&buffer);
        if(program&&delete_program)delete_program(program);
        if(shader&&delete_shader)delete_shader(shader);
    }
    if(texture&&delete_texture&&eglBindAPI(EGL_OPENGL_API)&&eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,producer))delete_texture(1,&texture);
    if(consumer!=EGL_NO_CONTEXT) {if(!eglBindAPI(EGL_OPENGL_ES_API)||!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,consumer))success=0;}
    return success;
}
int main(int argc,char **argv)
{
    if(argc!=2||strcmp(argv[1],"/dev/dri/renderD128")) {fprintf(stderr,"explicit /dev/dri/renderD128 required\n");return 1;}
    struct stat st;if(lstat(argv[1],&st)||!S_ISCHR(st.st_mode)||major(st.st_rdev)!=226||minor(st.st_rdev)!=128)return 1;
    EGLDisplay display=EGL_NO_DISPLAY;EGLContext producer=EGL_NO_CONTEXT,consumer=EGL_NO_CONTEXT;int initialized=0,result=1;
    LOAD(PFNEGLQUERYDEVICESEXTPROC,devices,"eglQueryDevicesEXT");
    LOAD(PFNEGLQUERYDEVICESTRINGEXTPROC,device_string,"eglQueryDeviceStringEXT");
    LOAD(PFNEGLGETPLATFORMDISPLAYEXTPROC,platform,"eglGetPlatformDisplayEXT");
    EGLDeviceEXT list[32],selected=EGL_NO_DEVICE_EXT;EGLint count=0;unsigned matches=0;
    if(!devices(32,list,&count)||count<1||count>32)goto done;
    for(EGLint i=0;i<count;++i) {
        const char *path=device_string(list[i],EGL_DRM_RENDER_NODE_FILE_EXT);struct stat candidate;
        if(path&&!stat(path,&candidate)&&S_ISCHR(candidate.st_mode)&&candidate.st_rdev==st.st_rdev){selected=list[i];++matches;}
    }
    if(matches!=1)goto done;
    display=platform(EGL_PLATFORM_DEVICE_EXT,selected,NULL);EGLint ma=0,mi=0;
    if(display==EGL_NO_DISPLAY||!eglInitialize(display,&ma,&mi))goto done;
    initialized=1;
    EGLConfig config;EGLint count_config=0;
    const EGLint attrs[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT|EGL_OPENGL_ES3_BIT,EGL_NONE};
    if(!eglChooseConfig(display,attrs,&config,1,&count_config)||count_config!=1)goto done;
    const EGLint gl_attrs[]={EGL_CONTEXT_MAJOR_VERSION_KHR,4,EGL_CONTEXT_MINOR_VERSION_KHR,3,EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
    if(!eglBindAPI(EGL_OPENGL_API))goto done;
    producer=eglCreateContext(display,config,EGL_NO_CONTEXT,gl_attrs);if(producer==EGL_NO_CONTEXT)goto done;
    const EGLint es_attrs[]={EGL_CONTEXT_MAJOR_VERSION_KHR,3,EGL_CONTEXT_MINOR_VERSION_KHR,1,EGL_NONE};
    if(!eglBindAPI(EGL_OPENGL_ES_API))goto done;
    consumer=eglCreateContext(display,config,EGL_NO_CONTEXT,es_attrs);if(consumer==EGL_NO_CONTEXT)goto done;
    if(!run_format(display,producer,consumer,0)||!run_format(display,producer,consumer,1))goto done;
    result=0;
done:
    /* Only this standalone process owns this display; bridge helper never
     * terminates a borrowed display. No connection to Kodi's EGL resources. */
    if(retained_resources)return 1;
    if(display!=EGL_NO_DISPLAY) {
        if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT))result=1;
        if(consumer!=EGL_NO_CONTEXT&&!eglDestroyContext(display,consumer))result=1;
        if(producer!=EGL_NO_CONTEXT&&!eglDestroyContext(display,producer))result=1;
        if(initialized&&!eglTerminate(display))result=1;
    }
    if(!result)puts("{\"schema\":\"yblod.egl-output-bridge-probe.v1\",\"complete\":true,\"width\":4,\"height\":4,\"rgba32f_words_exact\":64,\"rgba16ui_words_exact\":64,\"bindings_restored\":true,\"producer_consumer_fences\":true,\"timed_consumer_release\":true,\"playback_tested\":false}");
    return result;
}
