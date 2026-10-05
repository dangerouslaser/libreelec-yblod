"""Query-order control host guards; no GPU or driver timer validation."""
from pathlib import Path

import test_native_gpu_scaled_frame_device_probe as base

ROOT = Path(__file__).resolve().parent


class GPUScaledFrameQueryControlHostTests(base.GPUScaledFrameDeviceHostTests):
    source_name = "native_gpu_scaled_frame_query_control.c"
    report_schema = "yblod.native-gpu-scaled-frame-query-control.v1"

    def test_source_query_width_order_availability_and_cleanup(self):
        # This replaces the unsynchronized device probe's ordering audit.
        # It remains a source-only check, not GL driver/timer validation.
        source = (ROOT / self.source_name).read_text()
        width = source.index("gl.GetQueryiv(GL_TIME_ELAPSED,GL_QUERY_COUNTER_BITS")
        allocation = source.index("gl.GenQueries(1,&timer_query)", width)
        self.assertIn("timer_bits<33||timer_bits>64", source[width:allocation])
        begin = source.index("gl.BeginQuery(GL_TIME_ELAPSED,timer_query)")
        start_fence = source.index('operation="query start completion fence";', begin)
        start_wait = source.index("GLenum started=gl.ClientWaitSync", start_fence)
        dispatch = source.index("gl.DispatchCompute", start_wait)
        self.assertIn("started!=GL_CONDITION_SATISFIED", source[start_wait:dispatch])
        barrier = source.index("gl.MemoryBarrier", dispatch)
        compute_wait = source.index("GLenum waited=gl.ClientWaitSync", barrier)
        end = source.index("gl.EndQuery(GL_TIME_ELAPSED)", compute_wait)
        self.assertIn("waited!=GL_CONDITION_SATISFIED", source[compute_wait:end])
        end_fence = source.index('operation="query end completion fence";', end)
        end_wait = source.index("GLenum ended=gl.ClientWaitSync", end_fence)
        available = source.index("gl.GetQueryObjectiv(timer_query,GL_QUERY_RESULT_AVAILABLE",
                                 end_wait)
        self.assertIn("ended!=GL_CONDITION_SATISFIED", source[end_wait:available])
        result = source.index("gl.GetQueryObjectui64v(timer_query,GL_QUERY_RESULT", available)
        self.assertIn("available!=GL_TRUE", source[available:result])
        for wait, boundary in ((start_wait, dispatch), (compute_wait, end),
                               (end_wait, available)):
            self.assertIn("UINT64_C(5000000000)", source[wait:boundary])
        self.assertIn("if(query_active){", source)
        self.assertIn("if(gl.EndQuery)gl.EndQuery(GL_TIME_ELAPSED)", source)
        self.assertIn("gl.DeleteQueries(1,&timer_query)", source)
        self.assertIn('\\"device_timing_is_alu_busy\\":false', source)
