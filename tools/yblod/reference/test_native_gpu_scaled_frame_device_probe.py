"""Device-query companion host gates; no GPU or timer execution here."""
from pathlib import Path
import os
import shlex
import subprocess

import test_native_gpu_scaled_frame_preloaded_probe as base

ROOT = Path(__file__).resolve().parent


class GPUScaledFrameDeviceHostTests(base.GPUScaledFramePreloadedHostTests):
    source_name = "native_gpu_scaled_frame_device_probe.c"
    report_schema = "yblod.native-gpu-scaled-frame-device-probe.v1"

    def validated(self, result, counts, dispatches):
        report = super().validated(result, counts, dispatches)
        self.assertIs(report["device_timer_attempted"], False)
        self.assertEqual(report["timer_counter_bits"], 0)
        self.assertEqual(report["device_query_counts"], [0, 0, 0])
        self.assertNotIn("device_elapsed_ns", report)
        return report

    def test_source_query_width_order_availability_and_cleanup(self):
        # Offline structural audit; no simulated or actual GL calls execute.
        source = (ROOT / self.source_name).read_text()
        width = source.index("gl.GetQueryiv(GL_TIME_ELAPSED,GL_QUERY_COUNTER_BITS")
        allocation = source.index("gl.GenQueries(1,&timer_query)", width)
        self.assertIn("timer_bits<33||timer_bits>64", source[width:allocation])
        begin = source.index("gl.BeginQuery(GL_TIME_ELAPSED,timer_query)")
        dispatch = source.index("gl.DispatchCompute", begin)
        barrier = source.index("gl.MemoryBarrier", dispatch)
        end = source.index("gl.EndQuery(GL_TIME_ELAPSED)", barrier)
        fence = source.index("fence=gl.FenceSync", end)
        wait = source.index("GLenum waited=gl.ClientWaitSync", fence)
        available = source.index("gl.GetQueryObjectiv(timer_query,GL_QUERY_RESULT_AVAILABLE",
                                 wait)
        result = source.index("gl.GetQueryObjectui64v(timer_query,GL_QUERY_RESULT", available)
        self.assertIn("available!=GL_TRUE", source[available:result])
        self.assertIn("UINT64_C(5000000000)", source[wait:available])
        self.assertIn("if(query_active){", source)
        self.assertIn("if(gl.EndQuery)gl.EndQuery(GL_TIME_ELAPSED)", source)
        self.assertIn("gl.DeleteQueries(1,&timer_query)", source)
        self.assertIn('\\"device_timing_is_alu_busy\\":false', source)

    def test_counter_accumulator_boundaries_and_atomic_rejection(self):
        directory = Path(self.directory.name)
        harness = directory / "device-counter-helper.c"
        harness.write_text('#define main yb_device_original_main\n#include "'
            + str(ROOT / self.source_name) + '"\n#undef main\n'
            'int main(void) {\n'
            ' uint64_t sum=7;\n'
            ' if(!device_elapsed_add(33,1,&sum)||sum!=8)return 1;\n'
            ' if(!device_elapsed_add(64,UINT64_C(5000000000),&sum)||sum!=UINT64_C(5000000008))return 2;\n'
            ' const uint32_t bits[]={0,30,32,65};\n'
            ' for(unsigned i=0;i<4;i++){sum=77;'
            ' if(device_elapsed_add(bits[i],1,&sum)||sum!=77)return 3;}\n'
            ' const uint64_t bad[]={0,UINT64_C(5000000001),UINT64_MAX};\n'
            ' for(unsigned i=0;i<3;i++){sum=77;'
            ' if(device_elapsed_add(64,bad[i],&sum)||sum!=77)return 4;}\n'
            ' sum=UINT64_MAX;'
            ' if(device_elapsed_add(64,1,&sum)||sum!=UINT64_MAX)return 5;\n'
            ' sum=UINT64_MAX-1;'
            ' if(!device_elapsed_add(64,1,&sum)||sum!=UINT64_MAX)return 6;\n'
            ' if(device_elapsed_add(64,1,NULL))return 7;\n'
            ' return 0;\n}\n')
        binary = directory / "device-counter-helper"
        compiled = subprocess.run(["cc", "-std=c11", "-O2", "-fno-lto",
            "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
            "-DYB_GPU_PROBE_HOST_ONLY", "-I", str(ROOT),
            *shlex.split(os.environ.get("YB_GPU_FRAME_TEST_CFLAGS", "")),
            str(harness), *(str(ROOT / name) for name in (
                "native_gpu_guard.c", "native_gpu_probe_fixture.c",
                "native_mmr_composer.c", "native_scaled_surface.c",
                "native_decoder_frame_bridge.c", "native_integration_probe.c",
                "native_composer.c", "native_sampling_probe.c")),
            "-o", str(binary)], capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        result = subprocess.run([str(binary)], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
