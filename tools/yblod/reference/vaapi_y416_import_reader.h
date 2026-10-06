/* Included only by the isolated synthetic inventory variant. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <GL/glext.h>
#include "vaapi_y416_import_helpers.h"
/* Desktop SDK lacks the OES function-pointer typedef; Khronos signature uses
 * GLenum plus opaque EGL image pointer. No GLES context is created. */
typedef void (APIENTRYP YbImageTextureProc)(GLenum target, void *image);
static EGLDisplay egl_display=EGL_NO_DISPLAY;
static EGLContext egl_context=EGL_NO_CONTEXT;
static EGLImageKHR imported[2]={EGL_NO_IMAGE_KHR,EGL_NO_IMAGE_KHR};
static GLuint textures[2],program,shader,buffer;
static int egl_initialized,egl_current,import_attempted,import_supported,import_read;
static unsigned mismatches,compared;
static uint32_t observed_words[64];
static const char *import_reason="not attempted";
static PFNEGLDESTROYIMAGEKHRPROC destroy_image;
static PFNGLDELETETEXTURESPROC delete_textures;
static PFNGLDELETEPROGRAMPROC delete_program;
static PFNGLDELETESHADERPROC delete_shader;
static PFNGLDELETEBUFFERSPROC delete_buffers;
static PFNGLGETERRORPROC gl_error;
static PFNGLGETSTRINGPROC gl_string;
static char renderer_copy[1024],gl_version_copy[1024];
static uint32_t va_reference_words[64];
static unsigned upload_readback_mismatches;
static EGLint modifier_count[2];
static int modifier_advertised[2],external_only[2];
static void import_cleanup(void)
{
    if(egl_current) {
        if(buffer&&delete_buffers) delete_buffers(1,&buffer);
        if(program&&delete_program) delete_program(program);
        if(shader&&delete_shader) delete_shader(shader);
        if(delete_textures) delete_textures(2,textures);
        if(gl_error&&gl_error()!=GL_NO_ERROR) cleanup_ok=0;
        if(!eglMakeCurrent(egl_display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT)) cleanup_ok=0;
        egl_current=0;
    }
    for(unsigned i=0;i<2;++i) if(imported[i]!=EGL_NO_IMAGE_KHR&&destroy_image) {
        if(!destroy_image(egl_display,imported[i])) cleanup_ok=0;
        imported[i]=EGL_NO_IMAGE_KHR;
    }
    if(egl_context!=EGL_NO_CONTEXT) {if(!eglDestroyContext(egl_display,egl_context)) cleanup_ok=0;egl_context=EGL_NO_CONTEXT;}
    if(egl_initialized) {if(!eglTerminate(egl_display)) cleanup_ok=0;egl_initialized=0;}
}
#define ELOAD(type,var,name) type var=(type)eglGetProcAddress(name); if(!var) {import_reason="missing entrypoint";goto done;}
static EGLint bits32(uint32_t value) {EGLint result;memcpy(&result,&value,sizeof(result));return result;}
static void import_probe(const YbExportDescriptor *d,const struct stat *requested)
{
    import_attempted=1;
    const char *client=eglQueryString(EGL_NO_DISPLAY,EGL_EXTENSIONS);
    if(!yb_import_extension(client,"EGL_EXT_platform_device")||
        !(yb_import_extension(client,"EGL_EXT_device_base")||
          (yb_import_extension(client,"EGL_EXT_device_enumeration")&&yb_import_extension(client,"EGL_EXT_device_query")))) {
        import_reason="device extensions unavailable";return;
    }
    ELOAD(PFNEGLQUERYDEVICESEXTPROC,query_devices,"eglQueryDevicesEXT");
    ELOAD(PFNEGLQUERYDEVICESTRINGEXTPROC,device_string,"eglQueryDeviceStringEXT");
    ELOAD(PFNEGLGETPLATFORMDISPLAYEXTPROC,platform_display,"eglGetPlatformDisplayEXT");
    ELOAD(PFNEGLQUERYDISPLAYATTRIBEXTPROC,display_attribute,"eglQueryDisplayAttribEXT");
    EGLint count=0,returned=0;EGLDeviceEXT devices[32],selected=EGL_NO_DEVICE_EXT;unsigned matches=0;
    if(!query_devices(0,NULL,&count)||count<1||count>32||!query_devices(count,devices,&returned)||returned!=count) {import_reason="device query failed";goto done;}
    for(EGLint i=0;i<count;++i) {
        const char *ext=device_string(devices[i],EGL_EXTENSIONS);
        if(!yb_import_extension(ext,"EGL_EXT_device_drm_render_node")||yb_import_extension(ext,"EGL_MESA_device_software")) continue;
        const char *path=device_string(devices[i],EGL_DRM_RENDER_NODE_FILE_EXT);struct stat candidate;
        if(path&&!stat(path,&candidate)&&S_ISCHR(candidate.st_mode)&&candidate.st_rdev==requested->st_rdev) {selected=devices[i];++matches;}
    }
    if(matches!=1) {import_reason="device association failed";goto done;}
    egl_display=platform_display(EGL_PLATFORM_DEVICE_EXT,selected,NULL);
    EGLint major_version=0,minor_version=0;
    if(egl_display==EGL_NO_DISPLAY||!eglInitialize(egl_display,&major_version,&minor_version)) {import_reason="display initialization failed";goto done;}
    egl_initialized=1;EGLAttrib actual_device=0;
    if(!display_attribute(egl_display,EGL_DEVICE_EXT,&actual_device)||(EGLDeviceEXT)actual_device!=selected) {import_reason="display association failed";goto done;}
    const char *ext=eglQueryString(egl_display,EGL_EXTENSIONS);
    if(!yb_import_extension(ext,"EGL_EXT_image_dma_buf_import")||!yb_import_extension(ext,"EGL_EXT_image_dma_buf_import_modifiers")) {import_reason="DMA import extensions unavailable";goto done;}
    ELOAD(PFNEGLQUERYDMABUFFORMATSEXTPROC,query_formats,"eglQueryDmaBufFormatsEXT");
    ELOAD(PFNEGLQUERYDMABUFMODIFIERSEXTPROC,query_modifiers,"eglQueryDmaBufModifiersEXT");
    ELOAD(PFNEGLCREATEIMAGEKHRPROC,create_image,"eglCreateImageKHR");
    destroy_image=(PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR");
    if(!destroy_image) {import_reason="image cleanup unavailable";goto done;}
    EGLint formats[1024],format_count=0;
    if(!query_formats(egl_display,1024,formats,&format_count)||format_count<0||format_count>1024) {import_reason="format query failed";goto done;}
    /* Explicit same-storage ABGR16161616 reinterpret, not YUV conversion. */
    for(unsigned l=0;l<d->layers&&l<2;++l) {
        int found=0;for(EGLint i=0;i<format_count;++i) if((uint32_t)formats[i]==YB_FOURCC('A','B','4','8')) found=1;
        if(!found) continue;
        EGLuint64KHR mods[1024];EGLBoolean external[1024];EGLint n=0;
        if(!query_modifiers(egl_display,(EGLint)YB_FOURCC('A','B','4','8'),1024,mods,external,&n)||n<0||n>1024) {import_reason="modifier query failed";goto done;}
        modifier_count[l]=n;
        uint64_t wanted=d->obj[d->layer[l].object[0]].modifier;
        for(EGLint i=0;i<n;++i) if(mods[i]==wanted) {modifier_advertised[l]=1;external_only[l]=external[i]?1:0;}
    }
    if(d->format!=VA_FOURCC_Y416||d->layers!=1||d->layer[0].planes!=1||d->layer[0].format!=VA_FOURCC_Y416) {import_reason="packed Y416 shape unsupported";goto done;}
    if(!modifier_advertised[0]||external_only[0]) {import_reason="reinterpret modifier unavailable for texture2D";goto done;}
    import_supported=1;
    if(!yb_import_extension(ext,"EGL_KHR_surfaceless_context")||!eglBindAPI(EGL_OPENGL_API)) {import_reason="desktop GL unavailable";goto done;}
    const EGLint config_attrs[]={EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,EGL_OPENGL_BIT,EGL_NONE};
    const EGLint context_attrs[]={EGL_CONTEXT_MAJOR_VERSION_KHR,4,EGL_CONTEXT_MINOR_VERSION_KHR,3,EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
    EGLConfig config;EGLint configs=0;
    if(!eglChooseConfig(egl_display,config_attrs,&config,1,&configs)||configs!=1) {import_reason="GL config failed";goto done;}
    egl_context=eglCreateContext(egl_display,config,EGL_NO_CONTEXT,context_attrs);
    if(egl_context==EGL_NO_CONTEXT||!eglMakeCurrent(egl_display,EGL_NO_SURFACE,EGL_NO_SURFACE,egl_context)) {import_reason="GL context failed";goto done;}
    egl_current=1;
    gl_error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");gl_string=(PFNGLGETSTRINGPROC)eglGetProcAddress("glGetString");
    if(!gl_error||!gl_string) {import_reason="GL identity unavailable";goto done;}
    const char *renderer=(const char *)gl_string(GL_RENDERER),*version=(const char *)gl_string(GL_VERSION);
    if(!renderer||!version||strlen(renderer)>=sizeof(renderer_copy)||strlen(version)>=sizeof(gl_version_copy)) {import_reason="GL identity invalid";goto done;}
    strcpy(renderer_copy,renderer);strcpy(gl_version_copy,version);
    ELOAD(PFNGLGETSTRINGIPROC,string_index,"glGetStringi");
    ELOAD(PFNGLGETINTEGERVPROC,integer_query,"glGetIntegerv");
    GLint extension_count=0;integer_query(GL_NUM_EXTENSIONS,&extension_count);
    if(extension_count<0||extension_count>4096) {import_reason="GL extension count invalid";goto done;}
    int image_extension=0;
    for(GLint i=0;i<extension_count;++i) {
        const char *name=(const char *)string_index(GL_EXTENSIONS,(GLuint)i);
        if(name&&!strcmp(name,"GL_OES_EGL_image")) image_extension=1;
    }
    if(!image_extension) {import_reason="GL EGL image extension unavailable";goto done;}
    ELOAD(PFNGLGENTEXTURESPROC,gen_textures,"glGenTextures");
    ELOAD(PFNGLBINDTEXTUREPROC,bind_texture,"glBindTexture");
    ELOAD(YbImageTextureProc,image_texture,"glEGLImageTargetTexture2DOES");
    ELOAD(PFNGLTEXPARAMETERIPROC,texture_parameter,"glTexParameteri");
    ELOAD(PFNGLGETTEXLEVELPARAMETERIVPROC,texture_level,"glGetTexLevelParameteriv");
    ELOAD(PFNGLCREATESHADERPROC,create_shader,"glCreateShader");
    ELOAD(PFNGLSHADERSOURCEPROC,shader_source,"glShaderSource");
    ELOAD(PFNGLCOMPILESHADERPROC,compile_shader,"glCompileShader");
    ELOAD(PFNGLGETSHADERIVPROC,shader_status,"glGetShaderiv");
    ELOAD(PFNGLCREATEPROGRAMPROC,create_program,"glCreateProgram");
    ELOAD(PFNGLATTACHSHADERPROC,attach_shader,"glAttachShader");
    ELOAD(PFNGLLINKPROGRAMPROC,link_program,"glLinkProgram");
    ELOAD(PFNGLGETPROGRAMIVPROC,program_status,"glGetProgramiv");
    ELOAD(PFNGLUSEPROGRAMPROC,use_program,"glUseProgram");
    ELOAD(PFNGLGENBUFFERSPROC,gen_buffers,"glGenBuffers");
    ELOAD(PFNGLBINDBUFFERPROC,bind_buffer,"glBindBuffer");
    ELOAD(PFNGLBUFFERDATAPROC,buffer_data,"glBufferData");
    ELOAD(PFNGLBINDBUFFERBASEPROC,bind_buffer_base,"glBindBufferBase");
    ELOAD(PFNGLDISPATCHCOMPUTEPROC,dispatch_compute,"glDispatchCompute");
    ELOAD(PFNGLMEMORYBARRIERPROC,memory_barrier,"glMemoryBarrier");
    ELOAD(PFNGLGETBUFFERSUBDATAPROC,read_buffer,"glGetBufferSubData");
    ELOAD(PFNGLFENCESYNCPROC,fence_sync,"glFenceSync");
    ELOAD(PFNGLCLIENTWAITSYNCPROC,wait_sync,"glClientWaitSync");
    ELOAD(PFNGLDELETESYNCPROC,delete_sync,"glDeleteSync");
    delete_textures=(PFNGLDELETETEXTURESPROC)eglGetProcAddress("glDeleteTextures");delete_program=(PFNGLDELETEPROGRAMPROC)eglGetProcAddress("glDeleteProgram");delete_shader=(PFNGLDELETESHADERPROC)eglGetProcAddress("glDeleteShader");delete_buffers=(PFNGLDELETEBUFFERSPROC)eglGetProcAddress("glDeleteBuffers");
    if(!delete_textures||!delete_program||!delete_shader||!delete_buffers) {import_reason="GL cleanup unavailable";goto done;}
    gen_textures(2,textures);
    for(unsigned l=0;l<1;++l) {
        const YbExportLayer *layer=&d->layer[l];const YbExportObject *obj=&d->obj[layer->object[0]];
        EGLint attrs[]={EGL_WIDTH,4,EGL_HEIGHT,4,EGL_LINUX_DRM_FOURCC_EXT,(EGLint)YB_FOURCC('A','B','4','8'),
            EGL_DMA_BUF_PLANE0_FD_EXT,obj->fd,EGL_DMA_BUF_PLANE0_OFFSET_EXT,(EGLint)layer->offset[0],EGL_DMA_BUF_PLANE0_PITCH_EXT,(EGLint)layer->pitch[0],
            EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT,bits32((uint32_t)obj->modifier),EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT,bits32((uint32_t)(obj->modifier>>32)),EGL_NONE};
        imported[l]=create_image(egl_display,EGL_NO_CONTEXT,EGL_LINUX_DMA_BUF_EXT,NULL,attrs);
        if(imported[l]==EGL_NO_IMAGE_KHR) {import_reason="exact EGL image import failed";goto done;}
        bind_texture(GL_TEXTURE_2D,textures[l]);image_texture(GL_TEXTURE_2D,(void *)imported[l]);
        texture_parameter(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);texture_parameter(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        GLint internal_format=0;texture_level(GL_TEXTURE_2D,0,GL_TEXTURE_INTERNAL_FORMAT,&internal_format);
        if(internal_format!=GL_RGBA16) {import_reason="unexpected normalized texture storage";goto done;}
        if(gl_error()!=GL_NO_ERROR) {import_reason="raw texture bind failed";goto done;}
    }
    const char *code="#version 430\nlayout(local_size_x=4,local_size_y=4)in;layout(binding=0)uniform sampler2D raw_plane;layout(std430,binding=0)buffer Out{uint word[];};void main(){ivec2 p=ivec2(gl_GlobalInvocationID.xy);if(p.x>=4||p.y>=4)return;vec4 v=texelFetch(raw_plane,p,0);uvec4 w=uvec4(round(v*65535.0));int i=p.y*16+p.x*4;word[i]=w.r;word[i+1]=w.g;word[i+2]=w.b;word[i+3]=w.a;}";
    shader=create_shader(GL_COMPUTE_SHADER);shader_source(shader,1,&code,NULL);compile_shader(shader);GLint good=0;shader_status(shader,GL_COMPILE_STATUS,&good);
    if(!good) {import_reason="read shader compile failed";goto done;}
    program=create_program();attach_shader(program,shader);link_program(program);program_status(program,GL_LINK_STATUS,&good);
    if(!good) {import_reason="read shader link failed";goto done;}
    use_program(program);
    uint32_t words[64];for(unsigned i=0;i<64;++i) words[i]=UINT32_MAX;
    gen_buffers(1,&buffer);bind_buffer(GL_SHADER_STORAGE_BUFFER,buffer);buffer_data(GL_SHADER_STORAGE_BUFFER,(GLsizeiptr)sizeof(words),words,GL_DYNAMIC_READ);bind_buffer_base(GL_SHADER_STORAGE_BUFFER,0,buffer);
    bind_texture(GL_TEXTURE_2D,textures[0]);dispatch_compute(1,1,1);
    memory_barrier(GL_BUFFER_UPDATE_BARRIER_BIT);GLsync fence=fence_sync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
    if(!fence) {import_reason="read fence failed";goto done;}
    GLenum status=GL_TIMEOUT_EXPIRED;
    for(unsigned i=0;i<5&&status==GL_TIMEOUT_EXPIRED;++i) status=wait_sync(fence,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(1000000000));
    delete_sync(fence);
    if(status!=GL_ALREADY_SIGNALED&&status!=GL_CONDITION_SATISFIED) {import_reason="read fence timed out or failed";goto done;}
    read_buffer(GL_SHADER_STORAGE_BUFFER,0,(GLsizeiptr)sizeof(words),words);
    if(gl_error()!=GL_NO_ERROR) {import_reason="readback GL error";goto done;}
    memcpy(observed_words,words,sizeof(words));
    for(unsigned i=0;i<64;++i) {
        if(words[i]!=va_reference_words[i]) ++mismatches;
        ++compared;
    }
    import_read=1;import_reason=mismatches?"storage word mismatch":"all storage words exact";
done:
    import_cleanup();
}
static void import_json(void)
{
    printf(",\"egl_import\":{\"attempted\":%s,\"exact_modifier_texture2d_advertised\":%s,\"actual_shader_read\":%s,\"normalized_texture\":true,\"integer_texture\":false,\"storage_words_compared\":%u,\"storage_word_mismatches\":%u,\"colour_conversion\":false,\"filtering\":false,\"reason\":",import_attempted?"true":"false",import_supported?"true":"false",import_read?"true":"false",compared,mismatches);
    string_json(import_reason);printf(",\"renderer\":");string_json(renderer_copy);printf(",\"gl_version\":");string_json(gl_version_copy);
    printf(",\"layer_caps\":[");
    for(unsigned i=0;i<1;++i) printf("%s{\"modifier_count\":%d,\"exact_modifier_advertised\":%s,\"external_only\":%s}",i?",":"",modifier_count[i],modifier_advertised[i]?"true":"false",external_only[i]?"true":"false");
    printf("],\"public_synthetic_storage_words\":[");
    if(import_read) for(unsigned i=0;i<64;++i) printf("%s%u",i?",":"",observed_words[i]);
    printf("],\"va_readback_storage_words\":[");
    for(unsigned i=0;i<64;++i) printf("%s%u",i?",":"",va_reference_words[i]);
    printf("],\"upload_vs_va_words_compared\":64,\"upload_vs_va_word_mismatches\":%u,\"reinterpret_drm_format\":%u,\"packed_component_semantics_assumed\":false}",upload_readback_mismatches,YB_FOURCC('A','B','4','8'));
}
#undef ELOAD
