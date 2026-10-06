#include "native_vaapi_gl_import.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>
#include <va/va_drmcommon.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
typedef void (APIENTRYP ImageTarget)(GLenum,void *);
struct yb_vaapi_p010_import {
    uintptr_t display,context;
    EGLImageKHR image[2];
    GLuint texture[2];
    PFNEGLDESTROYIMAGEKHRPROC destroy_image;
    PFNGLDELETETEXTURESPROC delete_texture;
    PFNGLGETERRORPROC error;
    int ready;
};
static int extension(const char *list,const char *name)
{
    if (!list) return 0;
    size_t n=strlen(name);
    const char *p=list;
    while ((p=strstr(p,name))) {
        if ((p==list || p[-1]==' ') && (p[n]==' ' || !p[n])) return 1;
        p+=n;
    }
    return 0;
}
static EGLint bits(uint32_t value)
{ EGLint result; memcpy(&result,&value,sizeof(result)); return result; }
static int close_export(VADRMPRIMESurfaceDescriptor *d,int success)
{
    unsigned n=success ? d->num_objects : 0;
    if (n>4) n=4;
    int okay=1;
    for (unsigned i=0;i<n;i++) {
        int duplicate=0;
        for (unsigned j=0;j<i;j++) duplicate |= d->objects[i].fd==d->objects[j].fd;
        if (d->objects[i].fd>=0 && !duplicate && close(d->objects[i].fd)) okay=0;
    }
    return okay;
}
static int descriptor(const VADRMPRIMESurfaceDescriptor *d,uint32_t w,uint32_t h)
{
    if (d->fourcc!=VA_FOURCC_P010 || d->width!=w || d->height!=h ||
        !d->num_objects || d->num_objects>4 || d->num_layers!=2) return 0;
    const uint32_t formats[2]={UINT32_C(0x20363152),UINT32_C(0x32335247)};
    for (unsigned i=0;i<d->num_objects;i++)
        if (d->objects[i].fd<0 || !d->objects[i].size) return 0;
    for (unsigned l=0;l<2;l++) {
        const uint32_t obj=d->layers[l].object_index[0];
        if (d->layers[l].drm_format!=formats[l] || d->layers[l].num_planes!=1 ||
            obj>=d->num_objects || d->layers[l].offset[0]>INT_MAX ||
            d->layers[l].pitch[0]>INT_MAX || d->layers[l].pitch[0]<w*2 ||
            d->layers[l].offset[0]>=d->objects[obj].size) return 0;
        /* Linear storage admits row bounds. Tiled extents cannot be inferred
         * from offset+pitch; exact driver import checks those instead. */
        if (!d->objects[obj].drm_format_modifier) {
            uint64_t rows=l ? h/2 : h;
            uint64_t end=(uint64_t)d->layers[l].offset[0]+(rows-1)*d->layers[l].pitch[0]+w*2;
            if (end>d->objects[obj].size) return 0;
        }
    }
    return 1;
}
int yb_vaapi_p010_import_destroy(yb_vaapi_p010_import **handle)
{
    if (!handle) return YB_VA_IMPORT_ARGUMENT;
    yb_vaapi_p010_import *p=*handle;
    if (!p) return 0;
    if ((uintptr_t)eglGetCurrentDisplay()!=p->display ||
        (uintptr_t)eglGetCurrentContext()!=p->context || eglQueryAPI()!=EGL_OPENGL_API)
        return YB_VA_IMPORT_ARGUMENT;
    p->ready=0;
    for (unsigned i=0;i<2;i++) {
        if (p->texture[i]) {
            if (p->error()!=GL_NO_ERROR) return YB_VA_IMPORT_DRIVER;
            p->delete_texture(1,&p->texture[i]);
            if (p->error()!=GL_NO_ERROR) return YB_VA_IMPORT_DRIVER;
            p->texture[i]=0;
        }
        if (p->image[i]!=EGL_NO_IMAGE_KHR) {
            if (!p->destroy_image((EGLDisplay)p->display,p->image[i])) return YB_VA_IMPORT_DRIVER;
            p->image[i]=EGL_NO_IMAGE_KHR;
        }
    }
    free(p); *handle=NULL; return 0;
}
int yb_vaapi_p010_import_abandon_destroyed_display(yb_vaapi_p010_import **handle,uint32_t dead)
{
    if (!handle || dead!=1 || (*handle && (uintptr_t)eglGetCurrentContext()==(*handle)->context))
        return YB_VA_IMPORT_ARGUMENT;
    /* EGLImages are display resources, not context resources. They must also
     * have been destroyed by display-owner teardown before abandonment. */
    free(*handle); *handle=NULL; return 0;
}
uint32_t yb_vaapi_p010_import_texture(const yb_vaapi_p010_import *p,uint32_t plane)
{ return p && p->ready && plane<2 ? p->texture[plane] : 0; }
int yb_vaapi_p010_import_create(const yb_vaapi_p010_import_info *info,yb_vaapi_p010_import **out)
{
    if (!info || !out || *out || !info->egl_display || !info->desktop_context ||
        !info->va_display || info->surface==VA_INVALID_ID || !info->width || !info->height ||
        ((info->width|info->height)&1U) || info->width>3840 || info->height>2160 ||
        info->allocation_width<info->width || info->allocation_height<info->height ||
        info->allocation_width>8192 || info->allocation_height>8192 ||
        ((info->allocation_width|info->allocation_height)&1U) ||
        !info->producer_timeout_ns || info->producer_timeout_ns>UINT64_C(5000000000) ||
        (uintptr_t)eglGetCurrentDisplay()!=info->egl_display ||
        (uintptr_t)eglGetCurrentContext()!=info->desktop_context || eglQueryAPI()!=EGL_OPENGL_API)
        return YB_VA_IMPORT_ARGUMENT;
    EGLDisplay display=(EGLDisplay)info->egl_display;
    const char *ext=eglQueryString(display,EGL_EXTENSIONS);
    if (!extension(ext,"EGL_EXT_image_dma_buf_import") ||
        !extension(ext,"EGL_EXT_image_dma_buf_import_modifiers")) return YB_VA_IMPORT_UNSUPPORTED;
    PFNEGLQUERYDMABUFFORMATSEXTPROC formats=(PFNEGLQUERYDMABUFFORMATSEXTPROC)eglGetProcAddress("eglQueryDmaBufFormatsEXT");
    PFNEGLQUERYDMABUFMODIFIERSEXTPROC modifiers=(PFNEGLQUERYDMABUFMODIFIERSEXTPROC)eglGetProcAddress("eglQueryDmaBufModifiersEXT");
    PFNEGLCREATEIMAGEKHRPROC image=(PFNEGLCREATEIMAGEKHRPROC)eglGetProcAddress("eglCreateImageKHR");
    PFNEGLDESTROYIMAGEKHRPROC destroy_image=(PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR");
    PFNGLGETERRORPROC error=(PFNGLGETERRORPROC)eglGetProcAddress("glGetError");
    PFNGLGENTEXTURESPROC gen=(PFNGLGENTEXTURESPROC)eglGetProcAddress("glGenTextures");
    PFNGLBINDTEXTUREPROC bind=(PFNGLBINDTEXTUREPROC)eglGetProcAddress("glBindTexture");
    PFNGLTEXPARAMETERIPROC param=(PFNGLTEXPARAMETERIPROC)eglGetProcAddress("glTexParameteri");
    PFNGLGETTEXLEVELPARAMETERIVPROC level=(PFNGLGETTEXLEVELPARAMETERIVPROC)eglGetProcAddress("glGetTexLevelParameteriv");
    PFNGLDELETETEXTURESPROC del=(PFNGLDELETETEXTURESPROC)eglGetProcAddress("glDeleteTextures");
    PFNGLGETSTRINGIPROC string=(PFNGLGETSTRINGIPROC)eglGetProcAddress("glGetStringi");
    PFNGLGETINTEGERVPROC integer=(PFNGLGETINTEGERVPROC)eglGetProcAddress("glGetIntegerv");
    ImageTarget target=(ImageTarget)eglGetProcAddress("glEGLImageTargetTexture2DOES");
    if (!formats || !modifiers || !image || !destroy_image || !error || !gen || !bind ||
        !param || !level || !del || !string || !integer || !target) return YB_VA_IMPORT_UNSUPPORTED;
    if (error()!=GL_NO_ERROR) return YB_VA_IMPORT_DRIVER;
    GLint count=0; integer(GL_NUM_EXTENSIONS,&count);
    if (count<0 || count>4096) return YB_VA_IMPORT_UNSUPPORTED;
    int supported=0;
    for (GLint i=0;i<count;i++) {
        const char *name=(const char *)string(GL_EXTENSIONS,(GLuint)i);
        supported |= name && !strcmp(name,"GL_OES_EGL_image");
    }
    if (!supported || error()!=GL_NO_ERROR) return YB_VA_IMPORT_UNSUPPORTED;
    if (vaSyncSurface2(info->va_display,info->surface,info->producer_timeout_ns)!=VA_STATUS_SUCCESS)
        return YB_VA_IMPORT_DRIVER;
    VADRMPRIMESurfaceDescriptor d={0};
    for (unsigned i=0;i<4;i++) d.objects[i].fd=-1;
    if (vaExportSurfaceHandle(info->va_display,info->surface,VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2,
        VA_EXPORT_SURFACE_READ_ONLY|VA_EXPORT_SURFACE_SEPARATE_LAYERS,&d)!=VA_STATUS_SUCCESS)
        return YB_VA_IMPORT_DRIVER; /* failed-export fields are not owned */
    int status=YB_VA_IMPORT_UNSUPPORTED;
    yb_vaapi_p010_import *p=NULL;
    if (!descriptor(&d,info->allocation_width,info->allocation_height)) goto done;
    EGLint advertised[1024],n=0;
    if (!formats(display,1024,advertised,&n) || n<0 || n>1024) goto done;
    for (unsigned l=0;l<2;l++) {
        int found=0;
        for (EGLint i=0;i<n;i++) found |= (uint32_t)advertised[i]==d.layers[l].drm_format;
        if (!found) goto done;
        EGLuint64KHR mods[1024]; EGLBoolean external[1024]; EGLint m=0;
        if (!modifiers(display,bits(d.layers[l].drm_format),1024,mods,external,&m) || m<0 || m>1024) goto done;
        found=0;
        uint64_t wanted=d.objects[d.layers[l].object_index[0]].drm_format_modifier;
        for (EGLint i=0;i<m;i++) if (mods[i]==wanted && external[i]==EGL_FALSE) found=1;
        if (!found) goto done;
    }
    p=calloc(1,sizeof(*p));
    if (!p) { status=YB_VA_IMPORT_DRIVER; goto done; }
    p->display=info->egl_display; p->context=info->desktop_context;
    p->destroy_image=destroy_image; p->delete_texture=del; p->error=error;
    status=YB_VA_IMPORT_DRIVER;
    for (unsigned l=0;l<2;l++) {
        unsigned object=d.layers[l].object_index[0];
        uint64_t modifier=d.objects[object].drm_format_modifier;
        EGLint attrs[]={EGL_WIDTH,(EGLint)(l?info->width/2:info->width),
            EGL_HEIGHT,(EGLint)(l?info->height/2:info->height),
            EGL_LINUX_DRM_FOURCC_EXT,bits(d.layers[l].drm_format),
            EGL_DMA_BUF_PLANE0_FD_EXT,d.objects[object].fd,
            EGL_DMA_BUF_PLANE0_OFFSET_EXT,(EGLint)d.layers[l].offset[0],
            EGL_DMA_BUF_PLANE0_PITCH_EXT,(EGLint)d.layers[l].pitch[0],
            EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT,bits((uint32_t)modifier),
            EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT,bits((uint32_t)(modifier>>32)),EGL_NONE};
        p->image[l]=image(display,EGL_NO_CONTEXT,EGL_LINUX_DMA_BUF_EXT,NULL,attrs);
        if (p->image[l]==EGL_NO_IMAGE_KHR) goto done;
        gen(1,&p->texture[l]);
        if (!p->texture[l] || error()!=GL_NO_ERROR) goto done;
        bind(GL_TEXTURE_2D,p->texture[l]); target(GL_TEXTURE_2D,(void *)p->image[l]);
        param(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST); param(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        GLint internal=0,width=0,height=0;
        level(GL_TEXTURE_2D,0,GL_TEXTURE_INTERNAL_FORMAT,&internal);
        level(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width); level(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&height);
        if (error()!=GL_NO_ERROR || internal!=(l?GL_RG16:GL_R16) ||
            width!=(GLint)(l?info->width/2:info->width) || height!=(GLint)(l?info->height/2:info->height)) goto done;
    }
    status=YB_VA_IMPORT_OK; p->ready=1;
done:
    if (!close_export(&d,1)) { status=YB_VA_IMPORT_DRIVER; if (p) p->ready=0; }
    if (status!=YB_VA_IMPORT_OK && p) {
        if (yb_vaapi_p010_import_destroy(&p)!=YB_VA_IMPORT_OK) p->ready=0;
    }
    if (p) *out=p;
    return status;
}
