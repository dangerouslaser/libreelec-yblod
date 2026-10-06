"""Single completion-wait host guards; no GPU timing proof."""
from pathlib import Path
import test_native_gpu_scaled_frame_output_probe as base

ROOT = Path(__file__).resolve().parent

class GPUScaledFrameSingleWaitHostTests(base.GPUScaledFrameOutputHostTests):
    source_name = "native_gpu_scaled_frame_single_wait_probe.c"
    report_schema = "yblod.native-gpu-scaled-frame-single-wait-probe.v1"

    def test_one_finite_completion_wait_after_ordered_upload_dispatch(self):
        source = (ROOT / self.source_name).read_text()
        upload = source.index('operation="chunk SSBO upload";')
        dispatch = source.index('operation="bounded compute dispatch";', upload)
        barrier = source.index('gl.MemoryBarrier', dispatch)
        fence = source.index('fence=gl.FenceSync', barrier)
        wait = source.index('GLenum waited=gl.ClientWaitSync', fence)
        readback = source.index('operation="complete gate readback";', wait)
        self.assertLess(upload, dispatch)
        self.assertLess(dispatch, barrier)
        self.assertLess(barrier, fence)
        self.assertLess(wait, readback)
        self.assertEqual(source.count("gl.ClientWaitSync("), 1)
        self.assertEqual(source.count("gl.FenceSync("), 1)
        self.assertIn("UINT64_C(5000000000)", source)
        self.assertNotIn('operation="preload completion fence";', source)
        self.assertIn("may include pending upload work", source)
