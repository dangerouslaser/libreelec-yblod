/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include "cores/VideoPlayer/Buffers/VideoBuffer.h"
#include <mutex>
extern "C" {
#include <libavutil/frame.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_vaapi.h>
}

struct CQsvMappedGeneration
{
  std::atomic_bool valid{true};
  std::atomic_bool quarantined{false};
  uint64_t identity{};
};

class CQsvMappedBuffer final : public CVideoBuffer
{
public:
  explicit CQsvMappedBuffer(int id) : CVideoBuffer(id) {}
  ~CQsvMappedBuffer() override { av_frame_free(&m_frame); }
  const AVFrame* Frame() const { return m_frame; }
  bool Valid(VADisplay display) const;
private:
  friend class CQsvMappedBufferPool;
  AVFrame* m_frame{};
  std::shared_ptr<CQsvMappedGeneration> m_generation;
};

/* Not registered as a software buffer pool. Only directly mapped frames enter.
 * Quarantine retains this pool permanently; its decoder must remain terminal. */
class CQsvMappedBufferPool final : public IVideoBufferPool
{
public:
  CVideoBuffer* Get() override { return nullptr; }
  CQsvMappedBuffer* GetMapped(const AVFrame* qsv, AVBufferRef* vaapiDevice);
  void Return(int id) override;
  bool Reset();
  void Quarantine();
private:
  static constexpr size_t MAX_BUFFERS = 32;
  std::mutex m_mutex;
  std::vector<std::unique_ptr<CQsvMappedBuffer>> m_buffers;
  std::vector<bool> m_busy;
  std::shared_ptr<CQsvMappedGeneration> m_generation;
  uint64_t m_nextGeneration{};
  bool m_quarantined{};
  std::shared_ptr<IVideoBufferPool> m_quarantineOwner;
};
