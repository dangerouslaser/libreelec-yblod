/* Synthetic diagnostic-helper replay; no EGL/VA/GPU work. Fake monotonic clock
 * proves disabled diagnostics do not read it. Production uses real C clock. */
#define clock_gettime yb_test_clock
#include "native_playback_context.c"
#include <stdio.h>
static unsigned clock_calls;
static uint64_t fake_ns;
static int clock_fails;
int yb_test_clock(clockid_t id,struct timespec *ts)
{
    clock_calls++;
    if (clock_fails || id!=CLOCK_MONOTONIC) return -1;
    ts->tv_sec=(time_t)(fake_ns/UINT64_C(1000000000));
    ts->tv_nsec=(long)(fake_ns%UINT64_C(1000000000)); return 0;
}
int main(void)
{
    unsigned checks=0; yb_native_playback_context p={0};
    yb_native_playback_diagnostics out;
    memset(&out,0x5a,sizeof(out)); yb_native_playback_diagnostics before=out;
#define CHECK(x) do { if (!(x)) return 1; checks++; } while (0)
    CHECK(yb_native_playback_diagnostics_get(NULL,&out)==YB_NATIVE_PLAYBACK_ARGUMENT && !memcmp(&out,&before,sizeof(out)));
    CHECK(yb_native_playback_diagnostics_get(&p,NULL)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_diagnostics_enable(NULL,1)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_diagnostics_enable(&p,2)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_diagnostics_reset(NULL)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(!timing_begin(&p).active && clock_calls==0);
    CHECK(yb_native_playback_diagnostics_get(&p,&out)==0 && out.version==1 && !out.enabled && out.valid && out.completed_frames==0);
    CHECK(yb_native_playback_diagnostics_enable(&p,1)==0);
    fake_ns=10; yb_timing_mark first=timing_begin(&p); CHECK(first.active);
    fake_ns=30; timing_end(&p,YB_NATIVE_TIMING_VA_WAIT,first,0);
    fake_ns=40; first=timing_begin(&p); fake_ns=45; timing_end(&p,YB_NATIVE_TIMING_VA_WAIT,first,1);
    fake_ns=50; first=timing_begin(&p); fake_ns=60; timing_end(&p,YB_NATIVE_TIMING_VA_WAIT,first,2);
    CHECK(yb_native_playback_diagnostics_get(&p,&out)==0 && out.stages[YB_NATIVE_TIMING_VA_WAIT].calls==3 &&
        out.stages[YB_NATIVE_TIMING_VA_WAIT].ok==1 && out.stages[YB_NATIVE_TIMING_VA_WAIT].pending==1 &&
        out.stages[YB_NATIVE_TIMING_VA_WAIT].failed==1 && out.stages[YB_NATIVE_TIMING_VA_WAIT].total_wall_ns==35 &&
        out.stages[YB_NATIVE_TIMING_VA_WAIT].max_wall_ns==20);
    unsigned reads=clock_calls; CHECK(yb_native_playback_diagnostics_enable(&p,0)==0);
    CHECK(!timing_begin(&p).active && clock_calls==reads);
    CHECK(yb_native_playback_diagnostics_reset(&p)==0 && !p.diagnostics.enabled && p.diagnostics.valid && !p.diagnostics.stages[1].calls);
    p.state=VA_PENDING; before=p.diagnostics;
    CHECK(yb_native_playback_diagnostics_reset(&p)==YB_NATIVE_PLAYBACK_ARGUMENT && !memcmp(&p.diagnostics,&before,sizeof(before)));
    CHECK(yb_native_playback_diagnostics_enable(&p,1)==YB_NATIVE_PLAYBACK_ARGUMENT);
    p.state=IDLE; p.quarantined=1; CHECK(yb_native_playback_diagnostics_enable(&p,1)==YB_NATIVE_PLAYBACK_ARGUMENT);
    CHECK(yb_native_playback_diagnostics_get(&p,&out)==0);
    p.quarantined=0; p.closing=1; CHECK(yb_native_playback_diagnostics_reset(&p)==YB_NATIVE_PLAYBACK_ARGUMENT); p.closing=0;
    yb_native_playback_stage_stats entry={0},saved;
    CHECK(timing_accumulate(&entry,10,0)); saved=entry;
    CHECK(!timing_accumulate(&entry,1,3) && !memcmp(&entry,&saved,sizeof(entry)));
    entry.calls=UINT64_MAX; saved=entry; CHECK(!timing_accumulate(&entry,1,0) && !memcmp(&entry,&saved,sizeof(entry)));
    memset(&entry,0,sizeof(entry)); entry.total_wall_ns=UINT64_MAX; saved=entry;
    CHECK(!timing_accumulate(&entry,1,0) && !memcmp(&entry,&saved,sizeof(entry)));
    for (unsigned outcome=0;outcome<3;outcome++) {
        memset(&entry,0,sizeof(entry));
        if (!outcome) entry.ok=UINT64_MAX; else if (outcome==1) entry.pending=UINT64_MAX; else entry.failed=UINT64_MAX;
        saved=entry; CHECK(!timing_accumulate(&entry,1,outcome) && !memcmp(&entry,&saved,sizeof(entry)));
    }
    CHECK(yb_native_playback_diagnostics_enable(&p,1)==0);
    fake_ns=100; first=timing_begin(&p); fake_ns=99; timing_end(&p,0,first,0);
    CHECK(!p.diagnostics.valid && !p.quarantined && p.state==IDLE);
    CHECK(yb_native_playback_diagnostics_reset(&p)==0);
    clock_fails=1; CHECK(!timing_begin(&p).active && !p.diagnostics.valid && !p.quarantined);
    clock_fails=0; CHECK(yb_native_playback_diagnostics_reset(&p)==0);
    int status=0; unsigned executions=0;
    YB_TIMED_CALL(&p,YB_NATIVE_TIMING_SCALER_SUBMIT,status,(executions++,YB_VPP_PENDING),YB_VPP_OK,YB_VPP_PENDING);
    CHECK(status==YB_VPP_PENDING && executions==1 && p.diagnostics.stages[0].pending==1);
    timing_completed(&p); CHECK(p.diagnostics.completed_frames==1);
    p.diagnostics.completed_frames=UINT64_MAX; timing_completed(&p);
    CHECK(!p.diagnostics.valid && p.diagnostics.completed_frames==UINT64_MAX && !p.quarantined);
    CHECK(yb_native_playback_diagnostics_reset(&p)==0 && p.diagnostics.enabled && !p.diagnostics.completed_frames);
    printf("{\"schema\":\"yblod.native-playback-timing-host.v1\",\"checks_passed\":%u,\"gpu_attempted\":false,\"clock_is_synthetic\":true}\n",checks);
    return 0;
}
