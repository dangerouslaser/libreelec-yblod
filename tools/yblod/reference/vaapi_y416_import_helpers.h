#ifndef YB_VAAPI_Y416_IMPORT_HELPERS_H
#define YB_VAAPI_Y416_IMPORT_HELPERS_H
#include <stdint.h>
#include <string.h>
static uint32_t yb_y416_pattern(unsigned packed_x,unsigned y)
{
    return (packed_x*997u+y*1231u+17u)&65535u;
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
