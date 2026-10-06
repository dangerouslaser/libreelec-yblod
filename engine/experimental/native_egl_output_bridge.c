#include "native_egl_output_bridge.h"
#include <stdlib.h>
#include <string.h>
struct yb_egl_output_bridge {
    yb_egl_bridge_ops ops;
    yb_egl_binding consumer;
    uintptr_t image;
    uint32_t texture;
    int ready;
    int (*wait_timed)(void *,uint64_t);
};
static int valid_ops(const yb_egl_bridge_ops *o)
{
    return o && o->snapshot && o->validate && o->bind && o->wait_current &&
        o->image_create && o->texture_create && o->texture_delete && o->image_delete;
}
int yb_egl_output_bridge_create_with_ops(const yb_egl_bridge_ops *ops,
    uintptr_t producer,uint32_t texture,yb_egl_output_bridge **output)
{
    if (!output || *output) return YB_EGL_BRIDGE_ARGUMENT;
    if (!valid_ops(ops) || !producer || !texture) return YB_EGL_BRIDGE_ARGUMENT;
    yb_egl_output_bridge *b=calloc(1,sizeof(*b));
    if (!b) return YB_EGL_BRIDGE_ARGUMENT;
    b->ops=*ops;
    if (!ops->snapshot(ops->user,&b->consumer) || !b->consumer.display ||
        !b->consumer.context || !ops->validate(ops->user,&b->consumer,producer)) {
        free(b); return YB_EGL_BRIDGE_UNSUPPORTED;
    }
    yb_egl_binding producer_binding={b->consumer.display,producer,0,0,0x30A2};
    int status=YB_EGL_BRIDGE_PRODUCER;
    if (ops->bind(ops->user,&producer_binding) && ops->wait_current(ops->user)) {
        status=YB_EGL_BRIDGE_IMPORT;
        if (ops->image_create(ops->user,b->consumer.display,producer,texture,&b->image) &&
            b->image && ops->bind(ops->user,&b->consumer) &&
            ops->texture_create(ops->user,b->image,&b->texture) && b->texture)
            status=YB_EGL_BRIDGE_OK;
    }
    if (!ops->bind(ops->user,&b->consumer)) status=YB_EGL_BRIDGE_RESTORE;
    b->ready=status==YB_EGL_BRIDGE_OK;
    if (status==YB_EGL_BRIDGE_OK || b->image || b->texture) *output=b;
    else free(b);
    return status;
}
uint32_t yb_egl_output_bridge_texture(const yb_egl_output_bridge *b)
{
    return b && b->ready ? b->texture : 0;
}
int yb_egl_output_bridge_create_with_timed_ops(const yb_egl_bridge_ops *ops,
    int (*wait_timed)(void *,uint64_t),uintptr_t producer,uint32_t texture,
    yb_egl_output_bridge **output)
{
    if (!output || *output || !wait_timed) return YB_EGL_BRIDGE_ARGUMENT;
    int status=yb_egl_output_bridge_create_with_ops(ops,producer,texture,output);
    if (output && *output) (*output)->wait_timed=wait_timed;
    return status;
}
static int release_common(yb_egl_output_bridge **handle,int timed,uint64_t timeout)
{
    if (!handle) return YB_EGL_BRIDGE_ARGUMENT;
    yb_egl_output_bridge *b=*handle;
    if (!b) return YB_EGL_BRIDGE_OK;
    if (timed && !b->wait_timed) return YB_EGL_BRIDGE_UNSUPPORTED;
    yb_egl_binding previous;
    if (!b->ops.snapshot(b->ops.user,&previous)) return YB_EGL_BRIDGE_RESTORE;
    int status=YB_EGL_BRIDGE_CONSUMER;
    if (b->ops.bind(b->ops.user,&b->consumer) &&
        (timed ? b->wait_timed(b->ops.user,timeout) : b->ops.wait_current(b->ops.user))) {
        status=YB_EGL_BRIDGE_OK;
        if (b->texture) {
            if (b->ops.texture_delete(b->ops.user,b->texture)) b->texture=0;
            else status=YB_EGL_BRIDGE_CLEANUP;
        }
        if (!b->texture && b->image) {
            if (b->ops.image_delete(b->ops.user,b->consumer.display,b->image)) b->image=0;
            else status=YB_EGL_BRIDGE_CLEANUP;
        }
    }
    if (!b->ops.bind(b->ops.user,&previous)) status=YB_EGL_BRIDGE_RESTORE;
    if (status==YB_EGL_BRIDGE_OK) { free(b); *handle=NULL; }
    return status;
}
int yb_egl_output_bridge_release(yb_egl_output_bridge **handle)
{
    return release_common(handle,0,0);
}
int yb_egl_output_bridge_release_timed(yb_egl_output_bridge **handle,uint64_t timeout)
{
    if (timeout>UINT64_C(5000000000)) return YB_EGL_BRIDGE_ARGUMENT;
    return release_common(handle,1,timeout);
}
int yb_egl_output_bridge_abandon_destroyed_display(yb_egl_output_bridge **handle,uint32_t dead)
{
    if (!handle || dead!=1) return YB_EGL_BRIDGE_ARGUMENT;
    free(*handle); *handle=NULL; return YB_EGL_BRIDGE_OK;
}
#ifndef YB_EGL_BRIDGE_HOST_ONLY
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
typedef void (APIENTRYP ImageTextureProc)(GLenum,void *);
static int extension(const char *list,const char *name)
{
    if (!list) return 0;
    size_t n=strlen(name);
    const char *p=list;
    while ((p=strstr(p,name))) {
        if ((p==list || p[-1]==' ') && (p[n]==' ' || p[n]==0)) return 1;
        p+=n;
    }
    return 0;
}
static int snapshot(void *unused,yb_egl_binding *b)
{
    (void)unused;
    b->display=(uintptr_t)eglGetCurrentDisplay(); b->context=(uintptr_t)eglGetCurrentContext();
    b->draw=(uintptr_t)eglGetCurrentSurface(EGL_DRAW); b->read=(uintptr_t)eglGetCurrentSurface(EGL_READ);
    b->api=(uint32_t)eglQueryAPI(); return b->display && b->context;
}
static int validate(void *unused,const yb_egl_binding *b,uintptr_t producer)
{
    (void)unused;
    EGLint ct=0,pt=0;
    EGLDisplay d=(EGLDisplay)b->display;
    const char *ext=eglQueryString(d,EGL_EXTENSIONS);
    return b->api==EGL_OPENGL_ES_API && producer!=b->context &&
        eglQueryContext(d,(EGLContext)b->context,EGL_CONTEXT_CLIENT_TYPE,&ct) && ct==EGL_OPENGL_ES_API &&
        eglQueryContext(d,(EGLContext)producer,EGL_CONTEXT_CLIENT_TYPE,&pt) && pt==EGL_OPENGL_API &&
        extension(ext,"EGL_KHR_surfaceless_context") && extension(ext,"EGL_KHR_image_base") &&
        extension(ext,"EGL_KHR_gl_texture_2D_image");
}
static int bind(void *unused,const yb_egl_binding *b)
{
    (void)unused;
    return eglBindAPI((EGLenum)b->api) && eglMakeCurrent((EGLDisplay)b->display,
        (EGLSurface)b->draw,(EGLSurface)b->read,(EGLContext)b->context);
}
static int wait_current(void *unused)
{
    (void)unused;
    PFNGLFENCESYNCPROC fence=(PFNGLFENCESYNCPROC)eglGetProcAddress("glFenceSync");
    PFNGLCLIENTWAITSYNCPROC wait=(PFNGLCLIENTWAITSYNCPROC)eglGetProcAddress("glClientWaitSync");
    PFNGLDELETESYNCPROC destroy=(PFNGLDELETESYNCPROC)eglGetProcAddress("glDeleteSync");
    PFNGLGETERRORPROC error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");
    if (!fence || !wait || !destroy || !error || error()!=GL_NO_ERROR) return 0;
    GLsync s=fence(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
    if (!s) return 0;
    GLenum status=GL_TIMEOUT_EXPIRED;
    for (unsigned i=0;i<5 && status==GL_TIMEOUT_EXPIRED;++i)
        status=wait(s,GL_SYNC_FLUSH_COMMANDS_BIT,UINT64_C(1000000000));
    destroy(s);
    return (status==GL_ALREADY_SIGNALED || status==GL_CONDITION_SATISFIED) && error()==GL_NO_ERROR;
}
static int wait_timed(void *unused,uint64_t timeout)
{
    (void)unused;
    PFNGLFENCESYNCPROC fence=(PFNGLFENCESYNCPROC)eglGetProcAddress("glFenceSync");
    PFNGLCLIENTWAITSYNCPROC wait=(PFNGLCLIENTWAITSYNCPROC)eglGetProcAddress("glClientWaitSync");
    PFNGLDELETESYNCPROC destroy=(PFNGLDELETESYNCPROC)eglGetProcAddress("glDeleteSync");
    PFNGLGETERRORPROC error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");
    if (!fence || !wait || !destroy || !error || error()!=GL_NO_ERROR) return 0;
    GLsync sync=fence(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
    if (!sync) return 0;
    GLenum status=wait(sync,GL_SYNC_FLUSH_COMMANDS_BIT,timeout);
    destroy(sync);
    return (status==GL_ALREADY_SIGNALED || status==GL_CONDITION_SATISFIED) && error()==GL_NO_ERROR;
}
static int image_create(void *unused,uintptr_t display,uintptr_t context,uint32_t texture,uintptr_t *out)
{
    (void)unused;
    PFNEGLCREATEIMAGEKHRPROC create=(PFNEGLCREATEIMAGEKHRPROC)eglGetProcAddress("eglCreateImageKHR");
    if (!create) return 0;
    const EGLint attrs[]={EGL_GL_TEXTURE_LEVEL_KHR,0,EGL_IMAGE_PRESERVED_KHR,EGL_TRUE,EGL_NONE};
    EGLImageKHR image=create((EGLDisplay)display,(EGLContext)context,EGL_GL_TEXTURE_2D_KHR,
                             (EGLClientBuffer)(uintptr_t)texture,attrs);
    *out=(uintptr_t)image; return image!=EGL_NO_IMAGE_KHR;
}
static int texture_create(void *unused,uintptr_t image,uint32_t *out)
{
    (void)unused;
    PFNGLGETSTRINGPROC string=(PFNGLGETSTRINGPROC)eglGetProcAddress("glGetString");
    PFNGLGETINTEGERVPROC integer=(PFNGLGETINTEGERVPROC)eglGetProcAddress("glGetIntegerv");
    PFNGLGENTEXTURESPROC gen=(PFNGLGENTEXTURESPROC)eglGetProcAddress("glGenTextures");
    PFNGLBINDTEXTUREPROC texture_bind=(PFNGLBINDTEXTUREPROC)eglGetProcAddress("glBindTexture");
    ImageTextureProc target=(ImageTextureProc)eglGetProcAddress("glEGLImageTargetTexture2DOES");
    PFNGLTEXPARAMETERIPROC param=(PFNGLTEXPARAMETERIPROC)eglGetProcAddress("glTexParameteri");
    PFNGLGETERRORPROC error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");
    if (!string || !integer || !gen || !texture_bind || !target || !param || !error ||
        !extension((const char *)string(GL_EXTENSIONS),"GL_OES_EGL_image")) return 0;
    GLint previous=0; integer(GL_TEXTURE_BINDING_2D,&previous);
    GLuint texture=0; gen(1,&texture); *out=texture;
    texture_bind(GL_TEXTURE_2D,texture); target(GL_TEXTURE_2D,(void *)image);
    param(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);param(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    texture_bind(GL_TEXTURE_2D,(GLuint)previous);
    return texture && error()==GL_NO_ERROR;
}
static int texture_delete(void *unused,uint32_t texture)
{
    (void)unused;
    PFNGLDELETETEXTURESPROC destroy=(PFNGLDELETETEXTURESPROC)eglGetProcAddress("glDeleteTextures");
    PFNGLGETERRORPROC error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");
    if (!destroy || !error || error()!=GL_NO_ERROR) return 0;
    GLuint value=texture;destroy(1,&value);return error()==GL_NO_ERROR;
}
static int image_delete(void *unused,uintptr_t display,uintptr_t image)
{
    (void)unused;
    PFNEGLDESTROYIMAGEKHRPROC destroy=(PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR");
    return destroy && destroy((EGLDisplay)display,(EGLImageKHR)image);
}
int yb_egl_output_bridge_create(uintptr_t context,uint32_t texture,yb_egl_output_bridge **out)
{
    const yb_egl_bridge_ops ops={NULL,snapshot,validate,bind,wait_current,image_create,texture_create,texture_delete,image_delete};
    return yb_egl_output_bridge_create_with_timed_ops(&ops,wait_timed,context,texture,out);
}
#else
int yb_egl_output_bridge_create(uintptr_t context,uint32_t texture,yb_egl_output_bridge **out)
{
    (void)context;(void)texture;
    if (!out || *out) return YB_EGL_BRIDGE_ARGUMENT;
    return YB_EGL_BRIDGE_UNSUPPORTED;
}
#endif
