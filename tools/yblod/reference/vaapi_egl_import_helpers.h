#ifndef YB_VAAPI_EGL_IMPORT_HELPERS_H
#define YB_VAAPI_EGL_IMPORT_HELPERS_H
#include <stdint.h>
#include <string.h>
static uint32_t yb_import_expected_word(unsigned plane,unsigned x,unsigned y)
{
    return ((64u+x*47u+y*83u+plane*127u)&1023u)<<6;
}
static int yb_import_extension(const char *extensions,const char *wanted)
{
    if(!extensions||!wanted||!*wanted||strchr(wanted,' ')) return 0;
    size_t n=strlen(wanted);const char *p=extensions;
    while((p=strstr(p,wanted))) {
        if((p==extensions||p[-1]==' ')&&(p[n]==' '||p[n]=='\0')) return 1;
        p+=n;
    }
    return 0;
}
#endif
