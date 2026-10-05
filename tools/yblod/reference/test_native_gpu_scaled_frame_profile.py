"""Reuse every host-only input/width guard for the isolated phase profiler."""
import test_native_gpu_scaled_frame_probe as base


class GPUScaledFrameProfileHostTests(base.GPUScaledFrameHostTests):
    source_name = "native_gpu_scaled_frame_profile.c"
    report_schema = "yblod.native-gpu-scaled-frame-profile.v1"
