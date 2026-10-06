#include "native_playback_context.c"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    for(uint32_t flags=0;flags<64;flags++) {
        yb_native_playback_options options={1,flags,{0,0}};
        int valid=flags<32&&(!(flags&30)||(flags&YB_NATIVE_PLAYBACK_FP32))&&
            (!(flags&YB_NATIVE_PLAYBACK_BATCHED_PLANES)||(flags&YB_NATIVE_PLAYBACK_PLANAR_OUTPUT));
        assert((yb_native_playback_options_validate(&options)==YB_NATIVE_PLAYBACK_OK)==valid);
    }
    yb_native_playback_context p={0};yb_native_playback_batch_stats s={0};
    assert(!yb_native_playback_batched_planes_selected(&p));
    assert(!yb_native_playback_get_batch_stats(&p,&s)&&!s.selected&&!s.imports&&!s.releases);
    p.batched_planes=1;p.batch_imports=3;p.batch_releases=2;
    assert(yb_native_playback_batched_planes_selected(&p));
    assert(!yb_native_playback_get_batch_stats(&p,&s)&&s.selected==1&&s.imports==3&&s.releases==2);
    assert(yb_native_playback_get_batch_stats(NULL,&s)==YB_NATIVE_PLAYBACK_ARGUMENT);
    puts("Explicit option matrix64/default-OFF/batch counters PASS; no GPU/VA execution");
    return 0;
}
