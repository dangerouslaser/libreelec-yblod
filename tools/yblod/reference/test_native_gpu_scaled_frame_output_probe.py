"""Reduced diagnostic transfer guards; host tests do not execute GPU work."""
from pathlib import Path
import test_native_gpu_scaled_frame_batch_probe as base

ROOT = Path(__file__).resolve().parent

class GPUScaledFrameOutputHostTests(base.GPUScaledFrameBatchHostTests):
    source_name = "native_gpu_scaled_frame_output_probe.c"
    report_schema = "yblod.native-gpu-scaled-frame-output-probe.v1"

    def test_complete_gate_retained_and_warm_readback_bounded(self):
        source = (ROOT / self.source_name).read_text()
        self.assertIn('for(GLuint i=0;i<(pass==0?3U:2U);i++)', source)
        gate = source.index('operation="complete gate readback";')
        tail = source.index('operation="final suffix readback";', gate)
        oracle = source.index('operation="complete four stage oracle comparison";', tail)
        self.assertLess(gate, tail)
        self.assertLess(tail, oracle)
        self.assertIn('}else if(c==2 && start+n==w->counts[c])', source)
        self.assertIn('suffix_offset(n,last_count,&tail)', source)
        self.assertIn('(GLintptr)((size_t)tail*16)', source)
        self.assertIn('(GLsizeiptr)((size_t)last_count*16),actual+(size_t)tail*4)', source)
        self.assertIn('GLenum waited=gl.ClientWaitSync', source)
        self.assertIn('waited!=GL_CONDITION_SATISFIED', source)
        self.assertEqual(source.count('gl.GetBufferSubData(GL_SHADER_STORAGE_BUFFER,'), 2)
