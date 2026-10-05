"""Preloaded-batch synthetic guards; no GPU execution or device timing test."""
from pathlib import Path

import test_native_gpu_scaled_frame_batch_probe as base

ROOT = Path(__file__).resolve().parent


class GPUScaledFramePreloadedHostTests(base.GPUScaledFrameBatchHostTests):
    source_name = "native_gpu_scaled_frame_preloaded_probe.c"
    report_schema = "yblod.native-gpu-scaled-frame-preloaded-probe.v1"

    def test_source_timing_starts_after_preload_and_ends_before_readback(self):
        # This is an offline structural gate, not a driver synchronization test.
        source = (ROOT / self.source_name).read_text()
        upload = source.index('operation="chunk SSBO upload";')
        preload_fence = source.index('operation="preload completion fence";', upload)
        preload_wait = source.index("GLenum uploaded=gl.ClientWaitSync", preload_fence)
        preload_check = source.index("uploaded!=GL_CONDITION_SATISFIED", preload_wait)
        timing_start = source.index("clock_gettime(CLOCK_MONOTONIC,&dispatch_begin)",
                                    preload_check)
        dispatch = source.index("gl.DispatchCompute", timing_start)
        wait = source.index("GLenum waited=gl.ClientWaitSync", dispatch)
        wait_check = source.index("waited!=GL_CONDITION_SATISFIED", wait)
        timing_end = source.index("clock_gettime(CLOCK_MONOTONIC,&dispatch_end)",
                                  wait_check)
        readback = source.index('operation="bounded readback";', timing_end)
        self.assertLess(upload, preload_fence)
        self.assertLess(preload_check, timing_start)
        self.assertLess(timing_start, dispatch)
        self.assertLess(wait_check, timing_end)
        self.assertLess(timing_end, readback)
        self.assertIn('\\"whole_frame_resident\\":false', source)
        self.assertIn('\\"dispatch_timing_is_device_kernel_time\\":false', source)

