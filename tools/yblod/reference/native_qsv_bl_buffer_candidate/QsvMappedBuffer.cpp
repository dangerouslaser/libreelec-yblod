/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "QsvMappedBuffer.h"
#include <limits>

bool CQsvMappedBuffer::Valid(VADisplay display) const
{
  if (!m_generation || !m_generation->valid || m_generation->quarantined || !m_frame ||
      m_frame->format != AV_PIX_FMT_VAAPI || !m_frame->buf[0] || !m_frame->hw_frames_ctx ||
      m_frame->width <= 0 || m_frame->height <= 0 || m_frame->width > 8192 || m_frame->height > 8192 ||
      (m_frame->flags & AV_FRAME_FLAG_INTERLACED) ||
      m_frame->crop_top || m_frame->crop_bottom || m_frame->crop_left || m_frame->crop_right)
    return false;
  const auto* frames = reinterpret_cast<const AVHWFramesContext*>(m_frame->hw_frames_ctx->data);
  if (!frames || frames->format != AV_PIX_FMT_VAAPI || frames->sw_format != AV_PIX_FMT_P010 ||
      !frames->device_ctx || frames->device_ctx->type != AV_HWDEVICE_TYPE_VAAPI ||
      !frames->device_ctx->hwctx || frames->width < m_frame->width || frames->height < m_frame->height)
    return false;
  const auto* device = static_cast<const AVVAAPIDeviceContext*>(frames->device_ctx->hwctx);
  const auto* metadata = av_frame_get_side_data(m_frame, AV_FRAME_DATA_DOVI_METADATA);
  return device->display == display && reinterpret_cast<uintptr_t>(m_frame->data[3]) != VA_INVALID_ID &&
         metadata && metadata->data && metadata->size > 0 && metadata->size <= 1048576;
}

CQsvMappedBuffer* CQsvMappedBufferPool::GetMapped(const AVFrame* qsv, AVBufferRef* vaapiDevice)
{
  if (!qsv || qsv->format != AV_PIX_FMT_QSV || !qsv->buf[0] || !qsv->hw_frames_ctx ||
      !vaapiDevice || !vaapiDevice->data)
    return nullptr;
  const auto* device = reinterpret_cast<const AVHWDeviceContext*>(vaapiDevice->data);
  if (device->type != AV_HWDEVICE_TYPE_VAAPI || !device->hwctx)
    return nullptr;
  std::shared_ptr<CQsvMappedGeneration> generation;
  {
    std::lock_guard lock(m_mutex);
    if (m_quarantined || !m_generation || !m_generation->valid) return nullptr;
    generation = m_generation;
  }
  AVBufferRef* derived = nullptr;
  if (av_hwframe_ctx_create_derived(&derived, AV_PIX_FMT_VAAPI, vaapiDevice,
      qsv->hw_frames_ctx, AV_HWFRAME_MAP_READ | AV_HWFRAME_MAP_DIRECT) < 0)
    return nullptr;
  AVFrame* mapped = av_frame_alloc();
  if (!mapped) { av_buffer_unref(&derived); return nullptr; }
  mapped->format = AV_PIX_FMT_VAAPI;
  mapped->hw_frames_ctx = derived;
  if (av_hwframe_map(mapped, qsv, AV_HWFRAME_MAP_READ | AV_HWFRAME_MAP_DIRECT) < 0 ||
      av_frame_copy_props(mapped, qsv) < 0) { av_frame_free(&mapped); return nullptr; }
  if (mapped->format != AV_PIX_FMT_VAAPI || !mapped->hw_frames_ctx ||
      !mapped->hw_frames_ctx->data) { av_frame_free(&mapped); return nullptr; }
  std::lock_guard lock(m_mutex);
  const auto* mappedFrames = reinterpret_cast<const AVHWFramesContext*>(mapped->hw_frames_ctx->data);
  if (m_quarantined || generation != m_generation || !generation->valid ||
      !mappedFrames || mappedFrames->device_ctx != device) {
    av_frame_free(&mapped); return nullptr;
  }
  size_t index = 0;
  while (index < m_busy.size() && m_busy[index]) ++index;
  if (index == MAX_BUFFERS) { av_frame_free(&mapped); return nullptr; }
  if (index == m_busy.size()) {
    try {
      m_buffers.reserve(MAX_BUFFERS); m_busy.reserve(MAX_BUFFERS);
      auto buffer = std::make_unique<CQsvMappedBuffer>(static_cast<int>(index));
      m_buffers.push_back(std::move(buffer)); m_busy.push_back(false);
    } catch (const std::bad_alloc&) { av_frame_free(&mapped); return nullptr; }
  }
  auto* buffer = m_buffers[index].get();
  buffer->m_frame = mapped;
  buffer->m_generation = m_generation;
  buffer->m_pixFormat = AV_PIX_FMT_VAAPI;
  const auto display = static_cast<const AVVAAPIDeviceContext*>(device->hwctx)->display;
  if (!buffer->Valid(display)) {
    av_frame_free(&buffer->m_frame); buffer->m_generation.reset(); return nullptr;
  }
  m_busy[index] = true;
  buffer->Acquire(GetPtr());
  return buffer;
}

void CQsvMappedBufferPool::Return(int id)
{
  std::lock_guard lock(m_mutex);
  if (id < 0 || static_cast<size_t>(id) >= m_buffers.size() || !m_busy[id]) return;
  if (m_quarantined) return;
  auto& buffer = m_buffers[id];
  av_frame_free(&buffer->m_frame);
  buffer->m_generation.reset();
  m_busy[id] = false;
}

bool CQsvMappedBufferPool::Reset()
{
  std::lock_guard lock(m_mutex);
  if (m_generation) m_generation->valid = false;
  if (m_quarantined || m_nextGeneration == std::numeric_limits<uint64_t>::max()) return false;
  try { m_generation = std::make_shared<CQsvMappedGeneration>(); }
  catch (const std::bad_alloc&) { return false; }
  m_generation->identity = ++m_nextGeneration;
  return true;
}

void CQsvMappedBufferPool::Quarantine()
{
  std::lock_guard lock(m_mutex);
  m_quarantined = true;
  m_quarantineOwner = GetPtr();
  if (m_generation) { m_generation->quarantined = true; m_generation->valid = false; }
}
