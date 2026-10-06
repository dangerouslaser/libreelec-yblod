/* SPDX-License-Identifier: GPL-3.0-or-later */
#define dlsym test_resolve
#include "native_qsv_mfx_init_trace.c"
#undef dlsym
#include <assert.h>
#include <string.h>
#include <sys/wait.h>
static int init_calls, query_calls;
static mfxStatus MFX_CDECL fake_init(mfxSession s, mfxVideoParam *p)
{ (void)s; ++init_calls; p->mfx.FrameInfo.Width = 999; return MFX_WRN_IN_EXECUTION; }
static mfxStatus MFX_CDECL fake_query(mfxSession s, mfxVideoParam *p, mfxFrameAllocRequest *r)
{ (void)s; (void)p; ++query_calls; r->NumFrameMin = 3; r->NumFrameSuggested = 7; return getenv("TEST_QUERY_ERROR") ? MFX_ERR_UNKNOWN : MFX_ERR_NONE; }
void *test_resolve(void *handle, const char *name)
{
    assert(handle == RTLD_NEXT);
    return !strcmp(name, "MFXVideoDECODE_Init") ? (void *)fake_init : (void *)fake_query;
}
int main(void)
{
    /* Fork before pthread_once: each fault has a fresh resolver/output lifetime. */
    for (int fault = 0; fault < 5; ++fault) {
        pid_t child = fork(); assert(child >= 0);
        if (!child) {
            char dir[] = "/tmp/yblod-mfx-fault-XXXXXX", file[256];
            assert(mkdtemp(dir)); snprintf(file, sizeof(file), "%s/output", dir);
            if (fault) assert(!setenv("PRIVATE_MFX_INIT_TRACE_PATH", file, 1));
            else assert(!unsetenv("PRIVATE_MFX_INIT_TRACE_PATH"));
            if (fault == 1) { int fd = open(file,O_CREAT|O_WRONLY,0600); assert(fd >= 0); close(fd); }
            if (fault == 2) assert(!symlink("/dev/null", file));
            mfxVideoParam p = {0}; mfxFrameAllocRequest r = {0};
            if (fault < 3) {
                assert(MFXVideoDECODE_Init(NULL,&p) == MFX_ERR_UNKNOWN && !init_calls);
            } else if (fault == 3) {
                pthread_once(&resolve_once,resolve); assert(trace_fd >= 0);
                close(trace_fd);
                assert(MFXVideoDECODE_Init(NULL,&p) == MFX_ERR_UNKNOWN && !init_calls);
            } else {
                assert(!setenv("TEST_QUERY_ERROR","1",1));
                assert(MFXVideoDECODE_QueryIOSurf(NULL,&p,&r) == MFX_ERR_UNKNOWN && query_calls == 1);
                char out[1024]; int fd=open(file,O_RDONLY); assert(fd >= 0);
                ssize_t n=read(fd,out,sizeof(out)-1); assert(n > 0); out[n]=0; close(fd);
                assert(strstr(out,"\"surface_counts_valid\":false") && strstr(out,"\"prior_successful_query_valid\":false"));
            }
            if (trace_fd >= 0 && fault != 3) close(trace_fd);
            if (fault) unlink(file);
            assert(!rmdir(dir)); _exit(0);
        }
        int status; assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    }
    char directory[] = "/tmp/yblod-mfx-trace-XXXXXX", path[256], text[1024];
    assert(mkdtemp(directory));
    assert(snprintf(path, sizeof(path), "%s/scalars.json", directory) > 0);
    assert(!setenv("PRIVATE_MFX_INIT_TRACE_PATH", path, 1));
    mfxVideoParam p = {0}; mfxFrameAllocRequest r = {0};
    p.mfx.FrameInfo.Width = 1920; p.mfx.FrameInfo.Height = 1088;
    assert(MFXVideoDECODE_Init(NULL, &p) == MFX_WRN_IN_EXECUTION && init_calls == 1);
    int fd = open(path, O_RDONLY); assert(fd >= 0);
    ssize_t n = read(fd, text, sizeof(text)-1); assert(n > 0); text[n] = 0; close(fd);
    assert(strstr(text, "\"width\":1920") && !strstr(text, "\"width\":999"));
    assert(MFXVideoDECODE_QueryIOSurf(NULL, &p, &r) == MFX_ERR_NONE && query_calls == 1);
    fd = open(path, O_RDONLY); assert(fd >= 0);
    n = read(fd, text, sizeof(text)-1); assert(n > 0); text[n] = 0; close(fd);
    assert(strstr(text, "\"surface_counts_valid\":true") && strstr(text, "\"surface_suggested\":7"));
    assert(!strstr(text, "pointer") && !strstr(text, "hash") && !strstr(text, "buffer"));
    assert(close(trace_fd) == 0); trace_fd = -1;
    assert(unlink(path) == 0 && rmdir(directory) == 0);
    puts("CPU-only MFX interposer delegation/copy/private-output contracts PASS");
    return 0;
}
