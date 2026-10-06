/* Production argument guards and mode selection only; never EGL/VA execution. */
#include "native_playback_context.c"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    yb_native_playback_options options={1,0,{0,0}};
    for(uint32_t flags=0;flags<64;flags++){
        options.flags=flags;
        int valid=flags<32&&
            (!(flags&30)||(flags&YB_NATIVE_PLAYBACK_FP32))&&
            (!(flags&YB_NATIVE_PLAYBACK_BATCHED_PLANES)||(flags&YB_NATIVE_PLAYBACK_PLANAR_OUTPUT));
        assert((yb_native_playback_options_validate(&options)==YB_NATIVE_PLAYBACK_OK)==valid);
    }
    options.flags=7;
    for(unsigned field=0;field<3;field++){
        yb_native_playback_options invalid=options;
        if(field==0)invalid.version=0;
        else invalid.reserved[field-1]=1;
        assert(yb_native_playback_options_validate(&invalid)==YB_NATIVE_PLAYBACK_ARGUMENT);
    }
    yb_native_playback_context context={0};
    context.planar_output=1;
    yb_native_playback_output floating,before;
    memset(&floating,0x6d,sizeof(floating));before=floating;
    assert(yb_native_playback_finish(&context,1,&floating)==YB_NATIVE_PLAYBACK_ARGUMENT);
    assert(!memcmp(&floating,&before,sizeof(floating)));
    yb_native_playback_planar_output planar,saved;
    memset(&planar,0x6d,sizeof(planar));saved=planar;
    assert(yb_native_playback_finish_planar(&context,1,&planar)==YB_NATIVE_PLAYBACK_ARGUMENT);
    assert(!memcmp(&planar,&saved,sizeof(planar)));
    planar.version=1;saved=planar;
    assert(yb_native_playback_finish_planar(&context,1,&planar)==YB_NATIVE_PLAYBACK_ARGUMENT);
    context.planar_output=0;
    assert(yb_native_playback_finish_planar(&context,1,&planar)==YB_NATIVE_PLAYBACK_ARGUMENT);
    assert(!memcmp(&planar,&saved,sizeof(planar)));
    assert(yb_native_playback_finish_planar(NULL,1,&planar)==YB_NATIVE_PLAYBACK_ARGUMENT);
    assert(!memcmp(&planar,&saved,sizeof(planar)));
    assert(yb_native_playback_finish_planar(NULL,UINT64_C(5000000001),&planar)==YB_NATIVE_PLAYBACK_ARGUMENT);
    assert(!memcmp(&planar,&saved,sizeof(planar)));
    puts("Planar options, cross-mode/version guards and atomic invalid outputs PASS; no GPU/VA execution");
    return 0;
}
