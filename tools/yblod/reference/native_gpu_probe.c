#define _POSIX_C_SOURCE 200809L
#include "native_gpu_probe_fixture.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void validation_report(const struct yb_probe_fixture *f, int accepted)
{
    printf("\"accepted\":%s,\"algorithm_supported\":%s,\"polynomial_only\":%s,\"samples\":%u,\"component\":%d,"
           "\"width_report\":{\"supported\":%s,\"mmr_segment_count\":%u,\"worst_l1_bound\":%llu,"
           "\"first_unsupported_component\":%d,\"first_unsupported_segment\":%d}",
           accepted ? "true" : "false",f->algorithm_supported ? "true" : "false",f->polynomial_only ? "true" : "false",f->count,f->component,
           f->width.supported ? "true" : "false",f->width.mmr_segment_count,
           (unsigned long long)f->width.worst_l1_bound,f->width.first_unsupported_component,f->width.first_unsupported_segment);
}

#ifndef YB_GPU_PROBE_HOST_ONLY
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <ctype.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

static int extension(const char *list,const char *name)
{
    if (!list) return 0;
    size_t size=strlen(name);
    for (const char *p=list;(p=strstr(p,name))!=NULL;p+=size)
        if ((p==list || p[-1]==' ') && (p[size]==' ' || !p[size])) return 1;
    return 0;
}
static void string_json(const char *text)
{
    if (!text) { fputs("null",stdout); return; }
    putchar('"');
    for (const unsigned char *p=(const unsigned char *)text;*p;++p) {
        if (*p=='"' || *p=='\\') { putchar('\\'); putchar(*p); }
        else if (*p<32U || *p>=127U) printf("\\u%04x",(unsigned)*p);
        else putchar(*p);
    }
    putchar('"');
}
static int node_valid(const char *path)
{
    const char prefix[]="/dev/dri/renderD";
    if (strncmp(path,prefix,sizeof(prefix)-1)) return 0;
    const char *p=path+sizeof(prefix)-1;
    if (!*p) return 0;
    unsigned value=0;
    for (;*p;++p) {
        if (*p<'0' || *p>'9' || value>104857U) return 0;
        value=value*10U+(unsigned)(*p-'0');
    }
    return value>=128U && value<=1048575U;
}
static int software(const char *text)
{
    if (!text || strlen(text)>=4096) return 1;
    char lower[4096];
    for (size_t i=0;i<=strlen(text);++i) lower[i]=(char)tolower((unsigned char)text[i]);
    return strstr(lower,"llvmpipe") || strstr(lower,"softpipe") || strstr(lower,"software") || strstr(lower,"swrast");
}

struct gl_api {
    PFNGLGETSTRINGPROC GetString; PFNGLGETSTRINGIPROC GetStringi;
    PFNGLGETINTEGERVPROC GetIntegerv; PFNGLGETINTEGERI_VPROC GetIntegeri_v;
    PFNGLGETINTEGER64VPROC GetInteger64v; PFNGLGETERRORPROC GetError;
    PFNGLCREATESHADERPROC CreateShader; PFNGLSHADERSOURCEPROC ShaderSource;
    PFNGLCOMPILESHADERPROC CompileShader; PFNGLGETSHADERIVPROC GetShaderiv;
    PFNGLGETSHADERINFOLOGPROC GetShaderInfoLog; PFNGLDELETESHADERPROC DeleteShader;
    PFNGLCREATEPROGRAMPROC CreateProgram; PFNGLATTACHSHADERPROC AttachShader;
    PFNGLLINKPROGRAMPROC LinkProgram; PFNGLGETPROGRAMIVPROC GetProgramiv;
    PFNGLGETPROGRAMINFOLOGPROC GetProgramInfoLog; PFNGLDELETEPROGRAMPROC DeleteProgram;
    PFNGLUSEPROGRAMPROC UseProgram; PFNGLGENBUFFERSPROC GenBuffers;
    PFNGLBINDBUFFERPROC BindBuffer; PFNGLBUFFERDATAPROC BufferData;
    PFNGLBINDBUFFERBASEPROC BindBufferBase; PFNGLDELETEBUFFERSPROC DeleteBuffers;
    PFNGLDISPATCHCOMPUTEPROC DispatchCompute; PFNGLMEMORYBARRIERPROC MemoryBarrier;
    PFNGLFENCESYNCPROC FenceSync; PFNGLCLIENTWAITSYNCPROC ClientWaitSync;
    PFNGLDELETESYNCPROC DeleteSync; PFNGLGETBUFFERSUBDATAPROC GetBufferSubData;
};
#define LOAD(field,type) do { gl.field=(type)eglGetProcAddress("gl" #field); if(!gl.field) goto cleanup; } while(0)

static char *read_shader(const char *path)
{
    int fd=open(path,O_RDONLY|O_NONBLOCK);
    if (fd<0) return NULL;
    struct stat info;
    if (fstat(fd,&info) || !S_ISREG(info.st_mode) || info.st_size<1 || info.st_size>65536) { close(fd); return NULL; }
    char *text=calloc((size_t)info.st_size+1,1);
    FILE *stream=fdopen(fd,"rb");
    if (!stream) { close(fd); free(text); return NULL; }
    int ok=text && fread(text,1,(size_t)info.st_size,stream)==(size_t)info.st_size && fgetc(stream)==EOF && !ferror(stream);
    struct stat after,path_after;
    if (fstat(fileno(stream),&after) || stat(path,&path_after) ||
        info.st_dev!=after.st_dev || info.st_ino!=after.st_ino || info.st_size!=after.st_size ||
        info.st_dev!=path_after.st_dev || info.st_ino!=path_after.st_ino || info.st_size!=path_after.st_size ||
        info.st_mtim.tv_sec!=after.st_mtim.tv_sec || info.st_mtim.tv_nsec!=after.st_mtim.tv_nsec ||
        info.st_ctim.tv_sec!=after.st_ctim.tv_sec || info.st_ctim.tv_nsec!=after.st_ctim.tv_nsec ||
        info.st_mtim.tv_sec!=path_after.st_mtim.tv_sec || info.st_mtim.tv_nsec!=path_after.st_mtim.tv_nsec ||
        info.st_ctim.tv_sec!=path_after.st_ctim.tv_sec || info.st_ctim.tv_nsec!=path_after.st_ctim.tv_nsec) ok=0;
    if (fclose(stream)) ok=0;
    if (!ok || memchr(text,0,(size_t)info.st_size)) { free(text); return NULL; }
    return text;
}

static int dispatch(const char *node,const char *shader_path,const struct yb_probe_fixture *f,
                     const struct yb_probe_result *expected)
{
    int ok=0, fd=-1, initialized=0, current=0, bound=0;
    const char *operation="preflight";
    EGLDisplay display=EGL_NO_DISPLAY; EGLContext context=EGL_NO_CONTEXT;
    GLuint shader=0,program=0,buffers[3]={0,0,0}; GLsync fence=NULL;
    struct gl_api gl={0};
    char *source=NULL;
    _Static_assert(sizeof(uint32_t)==4 && sizeof(int32_t)==4 && sizeof(int64_t)==8,"SSBO scalar widths");
    const size_t wire_bytes=(size_t)f->count*4*sizeof(int32_t);
    int32_t *actual=calloc((size_t)f->count*4,sizeof(*actual));
    uint32_t *input_words=calloc((size_t)f->count*4,sizeof(*input_words));
    GLenum observed_gl_error=GL_NO_ERROR;
    EGLint observed_egl_error=EGL_SUCCESS;
    struct stat requested;
    const uint16_t endian=1;
    if (!actual || !input_words || *(const unsigned char *)&endian!=1 || !node_valid(node)) goto cleanup;
    for(size_t i=0;i<(size_t)f->count*4;++i) actual[i]=INT32_MIN;
    for(uint32_t i=0;i<f->count;++i) {
        input_words[4*i]=f->samples[i].y; input_words[4*i+1]=f->samples[i].cb;
        input_words[4*i+2]=f->samples[i].cr; input_words[4*i+3]=f->samples[i].el;
    }
    source=read_shader(shader_path);
    if (!source) goto cleanup;
    operation="requested render-node open";
    fd=open(node,O_RDWR|O_CLOEXEC);
    if (fd<0 || fstat(fd,&requested) || !S_ISCHR(requested.st_mode)) goto cleanup;
    operation="EGL device capabilities";
    const char *client=eglQueryString(EGL_NO_DISPLAY,EGL_EXTENSIONS);
    if ((observed_egl_error=eglGetError())!=EGL_SUCCESS || !extension(client,"EGL_EXT_platform_device") ||
        !(extension(client,"EGL_EXT_device_base") || (extension(client,"EGL_EXT_device_enumeration") && extension(client,"EGL_EXT_device_query")))) goto cleanup;
    PFNEGLQUERYDEVICESEXTPROC query_devices=(PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLQUERYDEVICESTRINGEXTPROC device_string=(PFNEGLQUERYDEVICESTRINGEXTPROC)eglGetProcAddress("eglQueryDeviceStringEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform_display=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    PFNEGLQUERYDISPLAYATTRIBEXTPROC display_attribute=(PFNEGLQUERYDISPLAYATTRIBEXTPROC)eglGetProcAddress("eglQueryDisplayAttribEXT");
    if (!query_devices || !device_string || !platform_display || !display_attribute) goto cleanup;
    EGLint count=0,returned=0; EGLDeviceEXT listed[32],selected=EGL_NO_DEVICE_EXT;
    if (!query_devices(0,NULL,&count) || count<1 || count>32 || !query_devices(count,listed,&returned) || count!=returned) goto cleanup;
    unsigned matches=0;
    for (EGLint i=0;i<count;++i) {
        const char *extensions=device_string(listed[i],EGL_EXTENSIONS);
        if (eglGetError()!=EGL_SUCCESS || !extension(extensions,"EGL_EXT_device_drm_render_node") || extension(extensions,"EGL_MESA_device_software")) continue;
        const char *path=device_string(listed[i],EGL_DRM_RENDER_NODE_FILE_EXT);
        EGLint error=eglGetError(); struct stat candidate;
        if (error==EGL_SUCCESS && path && !stat(path,&candidate) && S_ISCHR(candidate.st_mode) && candidate.st_rdev==requested.st_rdev) { ++matches; selected=listed[i]; }
    }
    if (matches!=1) goto cleanup;
    operation="EGL display association";
    display=platform_display(EGL_PLATFORM_DEVICE_EXT,selected,NULL);
    EGLint egl_major=0,egl_minor=0;
    if (display==EGL_NO_DISPLAY || !eglInitialize(display,&egl_major,&egl_minor)) goto cleanup;
    initialized=1; EGLAttrib device=0;
    if (!display_attribute(display,EGL_DEVICE_EXT,&device) || (EGLDeviceEXT)device!=selected) goto cleanup;
    bound=1;
    const char *display_extensions=eglQueryString(display,EGL_EXTENSIONS);
    if ((observed_egl_error=eglGetError())!=EGL_SUCCESS || !extension(display_extensions,"EGL_KHR_surfaceless_context") ||
        !((egl_major>1 || (egl_major==1 && egl_minor>=5)) || extension(display_extensions,"EGL_KHR_create_context"))) goto cleanup;
    operation="desktop GL4.3 core context";
    if (!eglBindAPI(EGL_OPENGL_API)) goto cleanup;
    const EGLint config_attributes[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT,EGL_NONE};
    const EGLint context_attributes[]={EGL_CONTEXT_MAJOR_VERSION_KHR,4,EGL_CONTEXT_MINOR_VERSION_KHR,3,
        EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
    EGLConfig config; EGLint configs=0;
    if (!eglChooseConfig(display,config_attributes,&config,1,&configs) || configs!=1) goto cleanup;
    context=eglCreateContext(display,config,EGL_NO_CONTEXT,context_attributes);
    if (context==EGL_NO_CONTEXT || !eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,context)) goto cleanup;
    current=1; operation="GL entrypoints";
    LOAD(GetString,PFNGLGETSTRINGPROC); LOAD(GetStringi,PFNGLGETSTRINGIPROC);
    LOAD(GetIntegerv,PFNGLGETINTEGERVPROC); LOAD(GetIntegeri_v,PFNGLGETINTEGERI_VPROC);
    LOAD(GetInteger64v,PFNGLGETINTEGER64VPROC); LOAD(GetError,PFNGLGETERRORPROC);
    LOAD(CreateShader,PFNGLCREATESHADERPROC); LOAD(ShaderSource,PFNGLSHADERSOURCEPROC);
    LOAD(CompileShader,PFNGLCOMPILESHADERPROC); LOAD(GetShaderiv,PFNGLGETSHADERIVPROC);
    LOAD(GetShaderInfoLog,PFNGLGETSHADERINFOLOGPROC); LOAD(DeleteShader,PFNGLDELETESHADERPROC);
    LOAD(CreateProgram,PFNGLCREATEPROGRAMPROC); LOAD(AttachShader,PFNGLATTACHSHADERPROC);
    LOAD(LinkProgram,PFNGLLINKPROGRAMPROC); LOAD(GetProgramiv,PFNGLGETPROGRAMIVPROC);
    LOAD(GetProgramInfoLog,PFNGLGETPROGRAMINFOLOGPROC); LOAD(DeleteProgram,PFNGLDELETEPROGRAMPROC);
    LOAD(UseProgram,PFNGLUSEPROGRAMPROC); LOAD(GenBuffers,PFNGLGENBUFFERSPROC);
    LOAD(BindBuffer,PFNGLBINDBUFFERPROC); LOAD(BufferData,PFNGLBUFFERDATAPROC);
    LOAD(BindBufferBase,PFNGLBINDBUFFERBASEPROC); LOAD(DeleteBuffers,PFNGLDELETEBUFFERSPROC);
    LOAD(DispatchCompute,PFNGLDISPATCHCOMPUTEPROC); LOAD(MemoryBarrier,PFNGLMEMORYBARRIERPROC);
    LOAD(FenceSync,PFNGLFENCESYNCPROC); LOAD(ClientWaitSync,PFNGLCLIENTWAITSYNCPROC);
    LOAD(DeleteSync,PFNGLDELETESYNCPROC); LOAD(GetBufferSubData,PFNGLGETBUFFERSUBDATAPROC);
    operation="GL version/renderer/int64 checks";
    const char *renderer=(const char *)gl.GetString(GL_RENDERER), *version=(const char *)gl.GetString(GL_VERSION);
    fputs(",\"renderer\":",stdout); string_json(renderer); fputs(",\"gl_version\":",stdout); string_json(version);
    GLint major=0,minor=0,num_extensions=0; gl.GetIntegerv(GL_MAJOR_VERSION,&major); gl.GetIntegerv(GL_MINOR_VERSION,&minor); gl.GetIntegerv(GL_NUM_EXTENSIONS,&num_extensions);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || software(renderer) || major<4 || (major==4 && minor<3) || num_extensions<0 || num_extensions>8192) goto cleanup;
    int int64_supported=0;
    for (GLint i=0;i<num_extensions;++i) { const char *name=(const char *)gl.GetStringi(GL_EXTENSIONS,(GLuint)i); if(name && !strcmp(name,"GL_ARB_gpu_shader_int64")) int64_supported=1; }
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || !int64_supported) goto cleanup;
    operation="compute limits";
    GLint invocations=0,size=0,groups=0,blocks=0,bindings=0; GLint64 block_size=0;
    gl.GetIntegerv(GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS,&invocations); gl.GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_SIZE,0,&size);
    gl.GetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT,0,&groups); gl.GetIntegerv(GL_MAX_COMPUTE_SHADER_STORAGE_BLOCKS,&blocks);
    gl.GetIntegerv(GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS,&bindings); gl.GetInteger64v(GL_MAX_SHADER_STORAGE_BLOCK_SIZE,&block_size);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || invocations<64 || size<64 || groups<(GLint)((f->count+63)/64) || blocks<3 || bindings<3 || block_size<(GLint64)wire_bytes || block_size<(GLint64)(YB_PROBE_METADATA_WORDS*sizeof(int64_t))) goto cleanup;
    operation="shader compile";
    shader=gl.CreateShader(GL_COMPUTE_SHADER); if (!shader) goto cleanup;
    const GLchar *source_pointer=source; gl.ShaderSource(shader,1,&source_pointer,NULL); gl.CompileShader(shader);
    GLint compiled=0; gl.GetShaderiv(shader,GL_COMPILE_STATUS,&compiled);
    char log[8192]={0}; GLsizei log_length=0; gl.GetShaderInfoLog(shader,(GLsizei)sizeof(log)-1,&log_length,log);
    fputs(",\"shader_log\":",stdout); string_json(log);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || !compiled) goto cleanup;
    operation="program link";
    program=gl.CreateProgram(); if(!program) goto cleanup;
    gl.AttachShader(program,shader); gl.LinkProgram(program);
    GLint linked=0; gl.GetProgramiv(program,GL_LINK_STATUS,&linked); memset(log,0,sizeof(log));
    gl.GetProgramInfoLog(program,(GLsizei)sizeof(log)-1,&log_length,log); fputs(",\"link_log\":",stdout); string_json(log);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || !linked) goto cleanup;
    operation="linked work-group dimensions";
    GLint linked_group_size[3]={0,0,0};
    gl.GetProgramiv(program,GL_COMPUTE_WORK_GROUP_SIZE,linked_group_size);
    if ((observed_gl_error=gl.GetError())!=GL_NO_ERROR || linked_group_size[0]!=64 ||
        linked_group_size[1]!=1 || linked_group_size[2]!=1) goto cleanup;
    operation="private SSBO allocation";
    int64_t metadata[YB_PROBE_METADATA_WORDS]; yb_probe_metadata(f,metadata);
    gl.GenBuffers(3,buffers);
    for (unsigned i=0;i<3;++i) if(!buffers[i]) goto cleanup;
    for (GLuint i=0;i<3;++i) {
        gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[i]);
        GLsizeiptr bytes=i==0 ? (GLsizeiptr)sizeof(metadata) : (GLsizeiptr)wire_bytes;
        const void *data=i==0 ? (const void *)metadata : i==1 ? (const void *)input_words : (const void *)actual;
        gl.BufferData(GL_SHADER_STORAGE_BUFFER,bytes,data,GL_DYNAMIC_COPY); gl.BindBufferBase(GL_SHADER_STORAGE_BUFFER,i,buffers[i]);
    }
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR) goto cleanup;
    operation="bounded compute dispatch";
    gl.UseProgram(program); gl.DispatchCompute((f->count+63)/64,1,1);
    gl.MemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT);
    fence=gl.FenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR || !fence) goto cleanup;
    GLenum waited=gl.ClientWaitSync(fence,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(5000000000));
    printf(",\"fence_wait_result\":%u",(unsigned)waited);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR || (waited!=GL_ALREADY_SIGNALED && waited!=GL_CONDITION_SATISFIED)) goto cleanup;
    operation="bounded readback";
    gl.BindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[2]); gl.GetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)wire_bytes,actual);
    if((observed_gl_error=gl.GetError())!=GL_NO_ERROR) goto cleanup;
    operation="stage comparison";
    uint32_t mismatches[4]={0,0,0,0};
    for(uint32_t i=0;i<f->count;++i) {
        if(actual[4*i]!=expected[i].mapped) ++mismatches[0];
        if(actual[4*i+1]!=expected[i].residual) ++mismatches[1];
        if(actual[4*i+2]!=expected[i].sum) ++mismatches[2];
        if(actual[4*i+3]!=expected[i].reconstructed) ++mismatches[3];
    }
    printf(",\"stage_mismatch_counts\":[%u,%u,%u,%u]",mismatches[0],mismatches[1],mismatches[2],mismatches[3]);
    ok=!(mismatches[0]||mismatches[1]||mismatches[2]||mismatches[3]);
cleanup:
    if(!ok) { fputs(",\"failure_operation\":",stdout); string_json(operation); }
    int cleanup_ok=1;
    EGLint final_egl_error=eglGetError();
    if(final_egl_error!=EGL_SUCCESS) observed_egl_error=final_egl_error;
    if(current && gl.GetError) { GLenum pending=gl.GetError(); if(pending!=GL_NO_ERROR) observed_gl_error=pending; }
    if(current) {
        if(fence && gl.DeleteSync) gl.DeleteSync(fence);
        if(gl.DeleteBuffers) gl.DeleteBuffers(3,buffers);
        if(program && gl.DeleteProgram) gl.DeleteProgram(program);
        if(shader && gl.DeleteShader) gl.DeleteShader(shader);
        if(gl.GetError && gl.GetError()!=GL_NO_ERROR) cleanup_ok=0;
        if(!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT)) cleanup_ok=0;
    }
    if(context!=EGL_NO_CONTEXT && !eglDestroyContext(display,context)) cleanup_ok=0;
    if(initialized && !eglTerminate(display)) cleanup_ok=0;
    if(!eglReleaseThread()) cleanup_ok=0;
    if(fd>=0 && close(fd)) cleanup_ok=0;
    free(actual); free(input_words); free(source);
    printf(",\"device_binding_verified\":%s,\"observed_gl_error\":%u,\"observed_egl_error\":%u,\"cleanup_succeeded\":%s",
           bound ? "true" : "false",(unsigned)observed_gl_error,(unsigned)observed_egl_error,cleanup_ok ? "true" : "false");
    return ok && cleanup_ok;
}
#endif

int main(int argc,char **argv)
{
    int validate=argc==3 && !strcmp(argv[1],"--validate");
    if(!validate && argc!=4) { fputs("usage: native_gpu_probe --validate FIXTURE | NODE SHADER FIXTURE\n",stderr); return 2; }
    struct yb_probe_fixture *fixture=calloc(1,sizeof(*fixture));
    const char *path=argv[validate ? 2 : 3];
    if(!fixture || !yb_probe_load(path,fixture)) { free(fixture); puts("{\"schema\":\"yblod.native-gpu-probe.v2\",\"status\":\"invalid-fixture\",\"accepted\":false,\"gpu_attempted\":false}"); return 2; }
    int accepted=fixture->algorithm_supported && fixture->width.supported;
    fputs("{\"schema\":\"yblod.native-gpu-probe.v2\",",stdout); validation_report(fixture,accepted);
    struct yb_probe_result *expected=calloc(fixture->count,sizeof(*expected));
    if(!expected || !yb_probe_cpu(fixture,expected)) { free(expected); free(fixture); puts(",\"status\":\"cpu-oracle-failed\",\"gpu_attempted\":false}"); return 2; }
    if(validate) {
        fputs(",\"cpu_stages\":[",stdout);
        for(uint32_t i=0;i<fixture->count;++i) { if(i) putchar(','); printf("[%d,%d,%d,%d]",expected[i].mapped,expected[i].residual,expected[i].sum,expected[i].reconstructed); }
        printf("],\"status\":\"%s\",\"gpu_attempted\":false}\n",accepted ? "validated" : "unsupported");
        free(expected); free(fixture); return accepted ? 0 : 3;
    }
    if(!accepted) { free(expected); free(fixture); puts(",\"status\":\"unsupported\",\"gpu_attempted\":false}"); return 3; }
#ifdef YB_GPU_PROBE_HOST_ONLY
    free(expected); free(fixture); puts(",\"status\":\"host-validation-build\",\"gpu_attempted\":false}"); return 3;
#else
    fputs(",\"gpu_attempted\":true",stdout);
    int ok=dispatch(argv[1],argv[2],fixture,expected);
    printf(",\"status\":\"%s\"}\n",ok ? "exact" : "failed");
    free(expected); free(fixture); return ok ? 0 : 1;
#endif
}
