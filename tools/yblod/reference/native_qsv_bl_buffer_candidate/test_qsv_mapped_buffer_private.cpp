/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Real Kodi buffer pool/refcounts and FFmpeg frames; hardware map is mocked. */
#define av_hwframe_ctx_create_derived test_derive
#define av_hwframe_map test_map
#include "QsvMappedBuffer.cpp"
#include <cassert>
#include <cstdio>
extern "C" {
#include <libavutil/mem.h>
}
static bool failMap, resetDuringMap, missingMappedContext;
static unsigned released;
static std::shared_ptr<CQsvMappedBufferPool> active;
static void release_source(void*, uint8_t* p) { ++released; av_free(p); }
static void release_frames(void*, uint8_t* p)
{
  auto* frames = reinterpret_cast<AVHWFramesContext*>(p);
  av_buffer_unref(&frames->device_ref); av_free(p);
}
extern "C" int test_derive(AVBufferRef** out, AVPixelFormat format, AVBufferRef* device,
                            AVBufferRef*, int flags)
{
  assert(format == AV_PIX_FMT_VAAPI && flags == (AV_HWFRAME_MAP_READ | AV_HWFRAME_MAP_DIRECT));
  *out = av_buffer_create(static_cast<uint8_t*>(av_mallocz(sizeof(AVHWFramesContext))),
                         sizeof(AVHWFramesContext), release_frames, nullptr, 0);
  assert(*out);
  auto* frames = reinterpret_cast<AVHWFramesContext*>((*out)->data);
  frames->format = AV_PIX_FMT_VAAPI; frames->sw_format = AV_PIX_FMT_P010;
  frames->width = 3840; frames->height = 2160;
  frames->device_ctx = reinterpret_cast<AVHWDeviceContext*>(device->data);
  frames->device_ref = av_buffer_ref(device); assert(frames->device_ref);
  return 0;
}
extern "C" int test_map(AVFrame* dst, const AVFrame* src, int flags)
{
  assert(flags == (AV_HWFRAME_MAP_READ | AV_HWFRAME_MAP_DIRECT));
  if (resetDuringMap) { resetDuringMap = false; assert(active->Reset()); }
  if (failMap) return AVERROR(ENOSYS);
  if (missingMappedContext) av_buffer_unref(&dst->hw_frames_ctx);
  dst->buf[0] = av_buffer_ref(src->buf[0]);
  dst->width = src->width; dst->height = src->height; dst->data[3] = src->data[3];
  return 0;
}
int main()
{
  AVVAAPIDeviceContext va = {}; va.display = reinterpret_cast<VADisplay>(1);
  AVBufferRef* device = av_buffer_allocz(sizeof(AVHWDeviceContext)); assert(device);
  auto* hw = reinterpret_cast<AVHWDeviceContext*>(device->data);
  hw->type = AV_HWDEVICE_TYPE_VAAPI; hw->hwctx = &va;
  AVFrame* src = av_frame_alloc(); assert(src);
  src->format = AV_PIX_FMT_QSV; src->width = 3840; src->height = 2160;
  src->data[3] = reinterpret_cast<uint8_t*>(2);
  src->buf[0] = av_buffer_create(static_cast<uint8_t*>(av_malloc(1)), 1, release_source, nullptr, 0);
  src->hw_frames_ctx = av_buffer_allocz(sizeof(AVHWFramesContext));
  active = std::make_shared<CQsvMappedBufferPool>();
  assert(active->Reset()); assert(!active->GetMapped(src, device));
  assert(av_frame_new_side_data(src, AV_FRAME_DATA_DOVI_METADATA, 1));
  failMap = true; assert(!active->GetMapped(src, device)); failMap = false;
  missingMappedContext = true; assert(!active->GetMapped(src, device)); missingMappedContext = false;
  resetDuringMap = true; assert(!active->GetMapped(src, device));
  CQsvMappedBuffer* buffer = active->GetMapped(src, device); assert(buffer);
  assert(buffer->Valid(va.display) && !buffer->Valid(reinterpret_cast<VADisplay>(3)));
  buffer->Acquire(); assert(active->Reset()); assert(!buffer->Valid(va.display));
  buffer->Release(); assert(!released); buffer->Release();
  CQsvMappedBuffer* held[32];
  for (auto& item : held) { item = active->GetMapped(src, device); assert(item); }
  assert(!active->GetMapped(src, device));
  for (auto* item : held) item->Release();
  active.reset(); av_frame_free(&src); assert(released == 1);
  src = av_frame_alloc(); assert(src);
  src->format = AV_PIX_FMT_QSV; src->width = 3840; src->height = 2160;
  src->data[3] = reinterpret_cast<uint8_t*>(2);
  src->buf[0] = av_buffer_create(static_cast<uint8_t*>(av_malloc(1)), 1, release_source, nullptr, 0);
  src->hw_frames_ctx = av_buffer_allocz(sizeof(AVHWFramesContext));
  assert(av_frame_new_side_data(src, AV_FRAME_DATA_DOVI_METADATA, 1));
  active = std::make_shared<CQsvMappedBufferPool>(); assert(active->Reset());
  buffer = active->GetMapped(src, device); assert(buffer);
  assert(av_buffer_get_ref_count(device) == 2);
  av_frame_free(&src); assert(released == 1);
  assert(buffer->Valid(va.display) && active->Reset() && !buffer->Valid(va.display));
  assert(released == 1 && av_buffer_get_ref_count(device) == 2);
  buffer->Release(); assert(released == 2 && av_buffer_get_ref_count(device) == 1);
  active.reset();
  src = av_frame_alloc(); assert(src);
  src->format = AV_PIX_FMT_QSV; src->width = 3840; src->height = 2160;
  src->data[3] = reinterpret_cast<uint8_t*>(2);
  src->buf[0] = av_buffer_create(static_cast<uint8_t*>(av_malloc(1)), 1, release_source, nullptr, 0);
  src->hw_frames_ctx = av_buffer_allocz(sizeof(AVHWFramesContext));
  assert(av_frame_new_side_data(src, AV_FRAME_DATA_DOVI_METADATA, 1));
  active = std::make_shared<CQsvMappedBufferPool>(); assert(active->Reset());
  buffer = active->GetMapped(src, device); assert(buffer);
  active->Quarantine(); buffer->Release();
  assert(!active->Reset() && !active->GetMapped(src, device));
  active.reset(); av_frame_free(&src);
  assert(released == 2); /* Deliberate terminal quarantine retains ownership. */
  av_buffer_unref(&device);
  puts("QSV mapped buffer CPU contract PASS: retained references, reset race, capacity, direct-only failure");
}
