"""Host guards for actual image backend diagnostic; no GPU is executed."""
from pathlib import Path
import test_native_gpu_scaled_frame_batch_probe as batch
import test_native_gpu_scaled_frame_probe as base

ROOT = Path(__file__).resolve().parent

class GPUComposerImageHostTests(batch.GPUScaledFrameBatchHostTests):
    source_name = 'native_gpu_composer_image_probe.c'
    report_schema = 'yblod.native-gpu-composer-image-probe.v1'

    def validated(self, result, counts, dispatches):
        report = base.GPUScaledFrameHostTests.validated(self, result, counts, dispatches)
        self.assertEqual(report['timed_crosscheck_scope'], 'frame-error-flag-only')
        self.assertEqual(report['cpu_chunk_samples'], 65536)
        self.assertEqual(report['gpu_oracle_dispatches'], 0)
        return report

    def test_source_keeps_cpu_subchunks_and_suffix_indices(self):
        source = (ROOT/self.source_name).read_text()
        self.assertIn('if(n>CHUNK)n=CHUNK;', source)
        self.assertIn('dispatch(w,c,start,n,&reference,NULL,scratch)', source)
        self.assertIn('image_codes[(size_t)start+i]!=scratch->out[i]', source)
        self.assertIn('yb_gpu_backend_submit(backend,&plan)', source)
        self.assertIn('yb_gpu_backend_finish(backend,UINT64_C(5000000000)', source)
        self.assertIn('if(pass==0){', source)
        self.assertNotIn('gl.DispatchCompute(', source)
        self.assertNotIn('input_words', source)
