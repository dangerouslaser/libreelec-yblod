/* CPU-only real dynamic-loader fixture for LIBVPL_2.0 symbol interposition. */
#include <vpl/mfxvideo.h>
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(void)
{
    mfxVideoParam p={0};mfxFrameAllocRequest r={0};p.mfx.FrameInfo.Width=1920;
    assert(MFXVideoDECODE_QueryIOSurf(NULL,&p,&r)==MFX_ERR_NONE);
    assert(MFXVideoDECODE_Init(NULL,&p)==MFX_WRN_IN_EXECUTION && p.mfx.FrameInfo.Width==999);
    int fd=open(getenv("PRIVATE_MFX_INIT_TRACE_PATH"),O_RDONLY);assert(fd>=0);
    char text[1024];ssize_t n=read(fd,text,sizeof(text)-1);assert(n>0);text[n]=0;close(fd);
    assert(strstr(text,"after_decode_init") && strstr(text,"\"width\":1920"));
    assert(strstr(text,"\"prior_successful_query_valid\":true") && strstr(text,"\"prior_surface_suggested\":7"));
    puts("Actual SDK loader/versioned LIBVPL_2.0 interposition fixture PASS; CPU only");
    return 0;
}
