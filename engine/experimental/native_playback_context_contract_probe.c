/* Actual production C entry points, invalid arguments only: no VA/GPU work. */
#include "native_playback_context.h"
#include <stdio.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"failed line %d\n",__LINE__); return 1; } } while (0)
int main(void)
{
    yb_native_playback_context *context=NULL;
    CHECK(yb_native_playback_create(NULL,&context)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(context==NULL);
    yb_native_playback_create_info info={0};
    CHECK(yb_native_playback_create(&info,&context)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(context==NULL);
    CHECK(yb_native_playback_create(&info,NULL)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_submit(NULL,NULL,0)==YB_NATIVE_PLAYBACK_ARGUMENT);
    yb_native_playback_frame frame={0};
    CHECK(yb_native_playback_submit(NULL,&frame,UINT64_C(5000000001))==YB_NATIVE_PLAYBACK_ARGUMENT);
    yb_native_playback_output output,before;
    memset(&output,0x6d,sizeof(output)); before=output;
    CHECK(yb_native_playback_finish(NULL,1,&output)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(!memcmp(&output,&before,sizeof(output)));
    CHECK(yb_native_playback_finish(NULL,UINT64_C(5000000001),&output)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(!memcmp(&output,&before,sizeof(output)));
    CHECK(yb_native_playback_release(NULL,0)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_release(NULL,UINT64_C(5000000001))==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_destroy(NULL)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_destroy(&context)==YB_NATIVE_PLAYBACK_OK);
    CHECK(context==NULL);
    CHECK(yb_native_playback_abandon_after_display_teardown(NULL,1)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_abandon_after_display_teardown(&context,0)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_abandon_after_display_teardown(&context,1)==YB_NATIVE_PLAYBACK_OK);
    puts("{\"checks\":19,\"passed\":true,\"gpu_attempted\":false}");
    return 0;
}
