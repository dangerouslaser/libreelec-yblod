/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Diagnostic-only interposition; not a production decoder optimization. */
#define _GNU_SOURCE
#include <vpl/mfxvideo.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

typedef mfxStatus (MFX_CDECL *init_fn)(mfxSession, mfxVideoParam *);
typedef mfxStatus (MFX_CDECL *query_fn)(mfxSession, mfxVideoParam *, mfxFrameAllocRequest *);
static pthread_mutex_t trace_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t resolve_once = PTHREAD_ONCE_INIT;
static init_fn next_init;
static query_fn next_query;
static int trace_fd = -1, trace_failed;
static int last_query_valid;
static mfxU16 last_query_min, last_query_suggested;
static mfxSession last_query_session;
static mfxVideoParam last_query_parameters;
static int same_parameters(const mfxVideoParam *a, const mfxVideoParam *b)
{
#define SAME(field) (a->field == b->field)
    return SAME(mfx.FrameInfo.Width) && SAME(mfx.FrameInfo.Height) &&
        SAME(mfx.FrameInfo.CropX) && SAME(mfx.FrameInfo.CropY) &&
        SAME(mfx.FrameInfo.CropW) && SAME(mfx.FrameInfo.CropH) &&
        SAME(mfx.FrameInfo.FourCC) && SAME(mfx.FrameInfo.BitDepthLuma) &&
        SAME(mfx.FrameInfo.BitDepthChroma) && SAME(mfx.CodecId) &&
        SAME(mfx.CodecProfile) && SAME(mfx.CodecLevel) && SAME(IOPattern) && SAME(AsyncDepth);
#undef SAME
}
static unsigned long sequence;

static void resolve(void)
{
    next_init = (init_fn)dlsym(RTLD_NEXT, "MFXVideoDECODE_Init");
    next_query = (query_fn)dlsym(RTLD_NEXT, "MFXVideoDECODE_QueryIOSurf");
    if (next_init == MFXVideoDECODE_Init || next_query == MFXVideoDECODE_QueryIOSurf)
        next_init = NULL, next_query = NULL;
    const char *path = getenv("PRIVATE_MFX_INIT_TRACE_PATH");
    if (!path || path[0] != '/') return;
    trace_fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    struct stat st;
    if (trace_fd < 0 || fstat(trace_fd, &st) || !S_ISREG(st.st_mode) ||
        (st.st_mode & 0777) != 0600) trace_failed = 1;
}

static int checkpoint(const char *stage, mfxSession session, const mfxVideoParam *p,
                      mfxStatus status, const mfxFrameAllocRequest *request)
{
    char text[1024];
    pthread_mutex_lock(&trace_lock);
    if (trace_fd < 0 || trace_failed || !p) {
        pthread_mutex_unlock(&trace_lock);
        return 0;
    }
    if (request) {
        last_query_valid = 1;
        last_query_session = session;
        last_query_parameters = *p;
        last_query_min = request->NumFrameMin;
        last_query_suggested = request->NumFrameSuggested;
    }
    unsigned long seq = ++sequence;
    int prior_valid = last_query_valid && last_query_session == session &&
        same_parameters(&last_query_parameters, p);
    int n = snprintf(text, sizeof(text),
        "{\"sequence\":%lu,\"stage\":\"%s\",\"width\":%u,\"height\":%u,"
        "\"crop_x\":%u,\"crop_y\":%u,\"crop_w\":%u,\"crop_h\":%u,"
        "\"fourcc\":%u,\"bit_depth_luma\":%u,\"bit_depth_chroma\":%u,"
        "\"profile\":%u,\"level\":%u,\"io_pattern\":%u,\"async_depth\":%u,"
        "\"status\":%d,\"surface_counts_valid\":%s,\"surface_min\":%u,\"surface_suggested\":%u,"
        "\"prior_successful_query_valid\":%s,\"prior_surface_min\":%u,\"prior_surface_suggested\":%u}\n",
        seq, stage, p->mfx.FrameInfo.Width, p->mfx.FrameInfo.Height,
        p->mfx.FrameInfo.CropX, p->mfx.FrameInfo.CropY, p->mfx.FrameInfo.CropW,
        p->mfx.FrameInfo.CropH, p->mfx.FrameInfo.FourCC, p->mfx.FrameInfo.BitDepthLuma,
        p->mfx.FrameInfo.BitDepthChroma, p->mfx.CodecProfile, p->mfx.CodecLevel,
        p->IOPattern, p->AsyncDepth, status, request ? "true" : "false",
        request ? request->NumFrameMin : 0, request ? request->NumFrameSuggested : 0,
        prior_valid ? "true" : "false", prior_valid ? last_query_min : 0,
        prior_valid ? last_query_suggested : 0);
    int ok = n > 0 && (size_t)n < sizeof(text) &&
        pwrite(trace_fd, text, n, 0) == n && !ftruncate(trace_fd, n);
    if (!ok) trace_failed = 1;
    pthread_mutex_unlock(&trace_lock);
    return ok;
}

mfxStatus MFX_CDECL MFXVideoDECODE_Init(mfxSession session, mfxVideoParam *par)
{
    pthread_once(&resolve_once, resolve);
    if (!next_init || !par) return MFX_ERR_UNSUPPORTED;
    mfxVideoParam copied = *par;
    if (!checkpoint("before_decode_init", session, &copied, 0, NULL)) return MFX_ERR_UNKNOWN;
    mfxStatus result = next_init(session, par);
    if (!checkpoint("after_decode_init", session, &copied, result, NULL)) return MFX_ERR_UNKNOWN;
    return result;
}

mfxStatus MFX_CDECL MFXVideoDECODE_QueryIOSurf(mfxSession session, mfxVideoParam *par,
                                             mfxFrameAllocRequest *request)
{
    pthread_once(&resolve_once, resolve);
    if (!next_query || !par) return MFX_ERR_UNSUPPORTED;
    mfxVideoParam copied = *par;
    if (!checkpoint("before_query_io_surf", session, &copied, 0, NULL)) return MFX_ERR_UNKNOWN;
    mfxStatus result = next_query(session, par, request);
    if (!checkpoint("after_query_io_surf", session, &copied, result,
                    result == MFX_ERR_NONE ? request : NULL)) return MFX_ERR_UNKNOWN;
    return result;
}
