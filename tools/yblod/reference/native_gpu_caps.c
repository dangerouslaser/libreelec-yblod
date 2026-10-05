#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Capability discovery only. There are deliberately no shader, draw, dispatch,
 * surface creation, buffer allocation, swap or KMS calls in this program. */
static int has_extension(const char *list, const char *name)
{
    if (!list || !name || !*name || strchr(name, ' ')) return 0;
    size_t length = strlen(name);
    for (const char *p = list; (p = strstr(p, name)) != NULL; p += length)
        if ((p == list || p[-1] == ' ') && (p[length] == '\0' || p[length] == ' ')) return 1;
    return 0;
}

static int valid_node(const char *path)
{
    const char prefix[] = "/dev/dri/renderD";
    if (!path || strncmp(path, prefix, sizeof(prefix)-1) != 0) return 0;
    const char *p = path + sizeof(prefix)-1;
    if (!*p) return 0;
    unsigned number = 0;
    for (; *p; ++p) {
        if (*p < '0' || *p > '9' || number > 104857U) return 0;
        number = number*10U + (unsigned)(*p-'0');
    }
    return number >= 128U && number <= 1048575U;
}

static int software_renderer(const char *renderer)
{
    if (!renderer) return 1;
    char lower[4096];
    size_t length = strlen(renderer);
    if (length >= sizeof(lower)) return 1;
    for (size_t i = 0; i <= length; ++i) lower[i] = (char)tolower((unsigned char)renderer[i]);
    return strstr(lower,"llvmpipe") != NULL || strstr(lower,"softpipe") != NULL ||
           strstr(lower,"software") != NULL || strstr(lower,"swrast") != NULL;
}

static int version_at_least(int major, int minor, int required_major, int required_minor)
{
    return major > required_major || (major == required_major && minor >= required_minor);
}

static void json_string(const char *text)
{
    if (!text) { fputs("null",stdout); return; }
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32U || *p >= 127U) printf("\\u%04x", (unsigned)*p);
        else putchar(*p);
    }
    putchar('"');
}

#ifndef YB_GPU_CAPS_UNIT_TEST
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

struct gl_functions {
    PFNGLGETSTRINGPROC string;
    PFNGLGETSTRINGIPROC string_index;
    PFNGLGETINTEGERVPROC integer;
    PFNGLGETINTEGERI_VPROC integer_index;
    PFNGLGETINTEGER64VPROC integer64;
    PFNGLGETERRORPROC error;
};

static void egl_failure(const char *where, EGLint error)
{
    fputs(",\"failure\":{\"operation\":",stdout); json_string(where);
    printf(",\"egl_error\":%u}",(unsigned)error);
}

static void query_integer(struct gl_functions *gl, const char *name, GLenum token,
                          int wide, int *query_ok)
{
    GLint64 value = 0;
    if (wide) gl->integer64(token,&value);
    else { GLint narrow = 0; gl->integer(token,&narrow); value = narrow; }
    GLenum error = gl->error();
    json_string(name); fputs(":{\"value\":",stdout);
    if (error == GL_NO_ERROR) printf("%lld",(long long)value);
    else { fputs("null",stdout); *query_ok = 0; }
    printf(",\"gl_error\":%u}",(unsigned)error);
}

static void query_indexed(struct gl_functions *gl, const char *name, GLenum token,
                          int *query_ok)
{
    json_string(name); fputs(":[",stdout);
    for (GLuint index = 0; index < 3; ++index) {
        GLint value = 0; gl->integer_index(token,index,&value);
        GLenum error = gl->error();
        if (index) putchar(',');
        fputs("{\"value\":",stdout);
        if (error == GL_NO_ERROR) printf("%d",value);
        else { fputs("null",stdout); *query_ok = 0; }
        printf(",\"gl_error\":%u}",(unsigned)error);
    }
    putchar(']');
}

static int inspect_context(EGLDisplay display, int desktop)
{
    EGLContext context = EGL_NO_CONTEXT;
    EGLConfig config;
    EGLint found = 0;
    int available = 0, query_ok = 1, software = 0;
    int compute = 0, int64_extension = 0;
    const EGLint attributes[] = {EGL_SURFACE_TYPE,0,EGL_RENDERABLE_TYPE,
        desktop ? EGL_OPENGL_BIT : EGL_OPENGL_ES3_BIT_KHR,EGL_NONE};
    const EGLint desktop_attributes[] = {EGL_CONTEXT_MAJOR_VERSION_KHR,4,
        EGL_CONTEXT_MINOR_VERSION_KHR,3,EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,
        EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,EGL_NONE};
    const EGLint es_attributes[] = {EGL_CONTEXT_MAJOR_VERSION_KHR,3,
        EGL_CONTEXT_MINOR_VERSION_KHR,1,EGL_NONE};
    printf("{\"api\":\"%s\",\"requested_version\":[%d,%d]",
           desktop ? "desktop-opengl" : "opengl-es",desktop ? 4 : 3,desktop ? 3 : 1);
    if (!eglBindAPI(desktop ? EGL_OPENGL_API : EGL_OPENGL_ES_API)) {
        egl_failure("eglBindAPI",eglGetError()); goto cleanup;
    }
    if (!eglChooseConfig(display,attributes,&config,1,&found) || found != 1) {
        egl_failure("eglChooseConfig",eglGetError()); goto cleanup;
    }
    context = eglCreateContext(display,config,EGL_NO_CONTEXT,
                                desktop ? desktop_attributes : es_attributes);
    if (context == EGL_NO_CONTEXT) {
        egl_failure("eglCreateContext",eglGetError()); goto cleanup;
    }
    if (!eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,context)) {
        egl_failure("eglMakeCurrent(surfaceless)",eglGetError()); goto cleanup;
    }
    struct gl_functions gl = {
        (PFNGLGETSTRINGPROC)eglGetProcAddress("glGetString"),
        (PFNGLGETSTRINGIPROC)eglGetProcAddress("glGetStringi"),
        (PFNGLGETINTEGERVPROC)eglGetProcAddress("glGetIntegerv"),
        (PFNGLGETINTEGERI_VPROC)eglGetProcAddress("glGetIntegeri_v"),
        (PFNGLGETINTEGER64VPROC)eglGetProcAddress("glGetInteger64v"),
        (PFNGLGETERRORPROC)eglGetProcAddress("glGetError")
    };
    if (!gl.string || !gl.string_index || !gl.integer || !gl.integer_index || !gl.integer64 || !gl.error) {
        fputs(",\"failure\":{\"operation\":\"resolve GL query functions\"}",stdout); goto cleanup;
    }
    GLenum initial_error = gl.error();
    printf(",\"initial_gl_error\":%u",(unsigned)initial_error);
    if (initial_error != GL_NO_ERROR) { query_ok = 0; goto cleanup; }
    const GLenum tokens[] = {GL_VENDOR,GL_RENDERER,GL_VERSION,GL_SHADING_LANGUAGE_VERSION};
    const char *names[] = {"vendor","renderer","version","shading_language_version"};
    for (unsigned index = 0; index < 4; ++index) {
        const char *value = (const char *)gl.string(tokens[index]);
        GLenum error = gl.error();
        putchar(','); json_string(names[index]); fputs(":{\"value\":",stdout);
        json_string(value); printf(",\"gl_error\":%u}",(unsigned)error);
        if (error != GL_NO_ERROR || !value) query_ok = 0;
        if (index == 1) software = software_renderer(value);
    }
    GLint major = 0, minor = 0, extensions = 0;
    gl.integer(GL_MAJOR_VERSION,&major); GLenum major_error = gl.error();
    gl.integer(GL_MINOR_VERSION,&minor); GLenum minor_error = gl.error();
    gl.integer(GL_NUM_EXTENSIONS,&extensions); GLenum extension_error = gl.error();
    printf(",\"version_numbers\":[%d,%d],\"version_query_errors\":[%u,%u],"
           "\"extension_count\":%d,\"extension_count_gl_error\":%u,\"extensions\":[",
           major,minor,(unsigned)major_error,(unsigned)minor_error,extensions,(unsigned)extension_error);
    if (major_error || minor_error || extension_error || extensions < 0 || extensions > 8192) query_ok = 0;
    else for (GLint index = 0; index < extensions; ++index) {
        const char *value = (const char *)gl.string_index(GL_EXTENSIONS,(GLuint)index);
        GLenum error = gl.error();
        if (index) putchar(',');
        fputs("{\"name\":",stdout); json_string(value); printf(",\"gl_error\":%u}",(unsigned)error);
        if (error || !value) query_ok = 0;
        if (value && !strcmp(value,"GL_ARB_gpu_shader_int64") && !error) int64_extension = 1;
    }
    putchar(']');
    compute = version_at_least(major,minor,desktop ? 4 : 3,desktop ? 3 : 1);
    fputs(",\"limits\":{",stdout);
    if (compute && query_ok) {
        query_integer(&gl,"max_compute_work_group_invocations",GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS,0,&query_ok); putchar(',');
        query_integer(&gl,"max_compute_shared_memory_size",GL_MAX_COMPUTE_SHARED_MEMORY_SIZE,0,&query_ok); putchar(',');
        query_integer(&gl,"max_shader_storage_buffer_bindings",GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS,0,&query_ok); putchar(',');
        query_integer(&gl,"max_shader_storage_block_size",GL_MAX_SHADER_STORAGE_BLOCK_SIZE,1,&query_ok); putchar(',');
        query_integer(&gl,"max_compute_shader_storage_blocks",GL_MAX_COMPUTE_SHADER_STORAGE_BLOCKS,0,&query_ok); putchar(',');
        query_indexed(&gl,"max_compute_work_group_count",GL_MAX_COMPUTE_WORK_GROUP_COUNT,&query_ok); putchar(',');
        query_indexed(&gl,"max_compute_work_group_size",GL_MAX_COMPUTE_WORK_GROUP_SIZE,&query_ok);
    }
    putchar('}');
    available = query_ok && compute && !software;
cleanup:
    printf(",\"software_renderer_detected\":%s,\"queries_valid\":%s,"
           "\"compute_ssbo_core_version_advertised\":%s,\"arb_gpu_shader_int64_advertised\":%s",
           software ? "true" : "false",query_ok && available ? "true" : "false",
           available && compute ? "true" : "false",available && int64_extension ? "true" : "false");
    EGLBoolean unbound = eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
    EGLint unbind_error = eglGetError();
    EGLBoolean destroyed = EGL_TRUE;
    EGLint destroy_error = EGL_SUCCESS;
    if (context != EGL_NO_CONTEXT) { destroyed = eglDestroyContext(display,context); destroy_error = eglGetError(); }
    printf(",\"cleanup\":{\"unbound\":%s,\"unbind_egl_error\":%u,\"destroyed\":%s,\"destroy_egl_error\":%u},"
           "\"status\":\"%s\"}",unbound ? "true" : "false",(unsigned)unbind_error,
           destroyed ? "true" : "false",(unsigned)destroy_error,
           available && unbound && destroyed ? "available" : "unavailable");
    return unbound && destroyed;
}

int main(int argc, char **argv)
{
    if (argc != 2 || !valid_node(argv[1])) {
        fputs("usage: native_gpu_caps /dev/dri/renderD<number>=128\n",stderr); return 2;
    }
    int fd = -1, initialized = 0, ok = 0, binding_verified = 0;
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLDeviceEXT selected = EGL_NO_DEVICE_EXT;
    const char *selected_extensions = NULL;
    struct stat requested;
    fputs("{\"schema\":\"yblod.native-gpu-caps.v1\",\"requested_render_node\":",stdout);
    json_string(argv[1]);
    fputs(",\"shader_execution_tested\":false,\"compute_dispatch_tested\":false",stdout);
    fd = open(argv[1],O_RDWR|O_CLOEXEC);
    if (fd < 0 || fstat(fd,&requested) != 0 || !S_ISCHR(requested.st_mode)) {
        fputs(",\"failure\":{\"operation\":\"open/fstat requested render node\"}",stdout); goto done;
    }
    const char *client = eglQueryString(EGL_NO_DISPLAY,EGL_EXTENSIONS);
    EGLint client_error = eglGetError();
    fputs(",\"egl_client_extensions\":",stdout); json_string(client);
    printf(",\"egl_client_extensions_error\":%u",(unsigned)client_error);
    PFNEGLQUERYDEVICESEXTPROC devices = (PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLQUERYDEVICESTRINGEXTPROC device_string = (PFNEGLQUERYDEVICESTRINGEXTPROC)eglGetProcAddress("eglQueryDeviceStringEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform_display = (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    PFNEGLQUERYDISPLAYATTRIBEXTPROC display_attribute = (PFNEGLQUERYDISPLAYATTRIBEXTPROC)eglGetProcAddress("eglQueryDisplayAttribEXT");
    if (client_error != EGL_SUCCESS || !has_extension(client,"EGL_EXT_platform_device") ||
        !(has_extension(client,"EGL_EXT_device_base") ||
          (has_extension(client,"EGL_EXT_device_enumeration") && has_extension(client,"EGL_EXT_device_query"))) ||
        !devices || !device_string || !platform_display || !display_attribute) {
        egl_failure("required EGL device/platform extensions or entrypoints",client_error); goto done;
    }
    EGLint count = 0, returned = 0;
    EGLDeviceEXT listed[32];
    if (!devices(0,NULL,&count) || count < 1 || count > 32 || !devices(count,listed,&returned) || returned != count) {
        egl_failure("eglQueryDevicesEXT bounded enumeration",eglGetError()); goto done;
    }
    unsigned matches = 0;
    fputs(",\"enumerated_devices\":[",stdout);
    for (EGLint index = 0; index < count; ++index) {
        const char *extensions = device_string(listed[index],EGL_EXTENSIONS);
        EGLint extensions_error = eglGetError();
        const char *node = NULL;
        EGLint error = EGL_SUCCESS;
        int node_queried = extensions_error == EGL_SUCCESS && has_extension(extensions,"EGL_EXT_device_drm_render_node");
        if (node_queried) { node = device_string(listed[index],EGL_DRM_RENDER_NODE_FILE_EXT); error = eglGetError(); }
        if (index) putchar(',');
        fputs("{\"extensions\":",stdout); json_string(extensions);
        printf(",\"extensions_egl_error\":%u,\"render_node\":",(unsigned)extensions_error); json_string(node);
        fputs(",\"render_node_egl_error\":",stdout);
        if (node_queried) printf("%u",(unsigned)error); else fputs("null",stdout);
        struct stat candidate;
        int matched = node_queried && error == EGL_SUCCESS && node && stat(node,&candidate) == 0 &&
                      S_ISCHR(candidate.st_mode) && candidate.st_rdev == requested.st_rdev;
        printf(",\"matches_requested_character_device\":%s}",matched ? "true" : "false");
        if (matched) {
            ++matches; selected = listed[index]; selected_extensions = extensions;
        }
    }
    putchar(']');
    if (matches != 1 || has_extension(selected_extensions,"EGL_MESA_device_software")) {
        fputs(",\"failure\":{\"operation\":\"unique nonsoftware render-node device association\"}",stdout); goto done;
    }
    display = platform_display(EGL_PLATFORM_DEVICE_EXT,selected,NULL);
    EGLint major = 0, minor = 0;
    if (display == EGL_NO_DISPLAY || !eglInitialize(display,&major,&minor)) {
        egl_failure("eglGetPlatformDisplayEXT/eglInitialize",eglGetError()); goto done;
    }
    initialized = 1;
    EGLAttrib associated = 0;
    if (!display_attribute(display,EGL_DEVICE_EXT,&associated) || (EGLDeviceEXT)associated != selected) {
        egl_failure("eglQueryDisplayAttribEXT device association",eglGetError()); goto done;
    }
    binding_verified = 1;
    fputs(",\"device_render_node\":",stdout);
    json_string(device_string(selected,EGL_DRM_RENDER_NODE_FILE_EXT));
    EGLint node_error = eglGetError();
    printf(",\"device_render_node_egl_error\":%u",(unsigned)node_error);
    fputs(",\"device_extensions\":",stdout); json_string(selected_extensions);
    printf(",\"egl_version_numbers\":[%d,%d],\"egl_vendor\":",major,minor); json_string(eglQueryString(display,EGL_VENDOR));
    EGLint vendor_error = eglGetError();
    printf(",\"egl_vendor_error\":%u",(unsigned)vendor_error);
    const char *extensions = eglQueryString(display,EGL_EXTENSIONS);
    EGLint display_extensions_error = eglGetError();
    fputs(",\"egl_display_extensions\":",stdout); json_string(extensions);
    printf(",\"egl_display_extensions_error\":%u",(unsigned)display_extensions_error);
    if (node_error != EGL_SUCCESS || vendor_error != EGL_SUCCESS || display_extensions_error != EGL_SUCCESS ||
        !has_extension(extensions,"EGL_KHR_surfaceless_context") ||
        !(version_at_least(major,minor,1,5) || has_extension(extensions,"EGL_KHR_create_context"))) {
        egl_failure("surfaceless/create-context support required",eglGetError()); goto done;
    }
    fputs(",\"contexts\":{\"desktop\":",stdout);
    int desktop_cleanup = inspect_context(display,1);
    fputs(",\"gles\":",stdout);
    int es_cleanup = 0;
    if (desktop_cleanup) es_cleanup = inspect_context(display,0);
    else fputs("{\"status\":\"not-attempted-after-cleanup-failure\"}",stdout);
    putchar('}');
    ok = desktop_cleanup && es_cleanup;
done:
    if (initialized) {
        EGLBoolean terminated = eglTerminate(display);
        EGLint error = eglGetError();
        printf(",\"egl_terminated\":%s,\"terminate_egl_error\":%u",terminated ? "true" : "false",(unsigned)error);
        if (!terminated) ok = 0;
    }
    EGLBoolean released = eglReleaseThread();
    printf(",\"egl_thread_released\":%s",released ? "true" : "false");
    if (!released) ok = 0;
    if (fd >= 0 && close(fd) != 0) ok = 0;
    printf(",\"device_binding_verified\":%s,\"status\":\"%s\"}\n",
           binding_verified ? "true" : "false",ok ? "complete" : "blocked");
    return ok ? 0 : 1;
}
#endif
