"""Saved-evidence/source-patch tests; no compiler, GPU or canonical edits."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REFERENCE = Path(__file__).parent
PATCH = Path(os.environ.get('YB_COMPONENT_PATCH', str(REFERENCE / 'experiments/native-gpu-component-buffers.patch')))
RESULT = Path(os.environ.get('YB_COMPONENT_RESULT', str(REFERENCE / 'results/native-gpu-component-buffers-abba-20261006.json')))
SOURCE = Path(os.environ.get('YB_COMPONENT_SOURCE', str(REFERENCE.parents[2] / 'engine/experimental/native_gpu_composer_backend.c')))

class Experiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'engine/experimental/native_gpu_composer_backend.c'
            target.parent.mkdir(parents=True)
            target.write_text(SOURCE.read_text())
            subprocess.run(['patch', '-p1', '-i', str(PATCH.resolve())], cwd=directory,
                           check=True, capture_output=True)
            cls.candidate = target.read_text()

    def test_allocation_and_partial_create_cleanup(self):
        c = self.candidate
        self.assertIn('calloc(1,sizeof(*b))', c)
        self.assertIn('g->GenBuffers(4,b->buffers)', c)
        self.assertIn('if(!b->buffers[i]){delete_owned(b);free(b);return YB_GPU_BACKEND_GL_FAILURE;}', c)
        self.assertIn('b->gl.DeleteBuffers(4,b->buffers)', c)
        self.assertIn('i==1?4:(GLsizeiptr)(BACKEND_WORDS*sizeof(int64_t))', c)

    def test_delete_failure_retains_remaining_and_busy_guard(self):
        c = self.candidate
        self.assertIn('if(b->pending)return YB_GPU_BACKEND_BUSY', c)
        self.assertIn('for(unsigned i=0;i<4;i++)if(b->buffers[i])', c)
        self.assertIn('if(b->pending||b->closing)return YB_GPU_BACKEND_BUSY', c)
        delete = c.index('g->DeleteBuffers(1,&b->buffers[i]);')
        failure = c.index('if(g->GetError()!=GL_NO_ERROR)return YB_GPU_BACKEND_GL_FAILURE;', delete)
        zero = c.index('b->buffers[i]=0;', delete)
        self.assertLess(failure, zero)

    def test_upload_dispatch_separation_and_error_slot(self):
        c = self.candidate
        loops = c[c.index('static const unsigned component_buffer_slots'):c.index('g->MemoryBarrier(')]
        self.assertEqual(loops.count('for(uint32_t c=0;c<3;c++)'), 2)
        upload, dispatch = loops.split('for(uint32_t c=0;c<3;c++)')[1:]
        self.assertIn('pack_metadata(p,c,words)', upload)
        self.assertNotIn('DispatchCompute', upload)
        self.assertNotIn('BufferSubData', dispatch)
        self.assertIn('BindBufferBase(GL_SHADER_STORAGE_BUFFER,0,b->buffers[component_buffer_slots[c]])', dispatch)
        self.assertEqual(SOURCE.read_text().count('b->buffers[1]'), c.count('b->buffers[1]'))

    def test_patch_isolated_and_preserves_math(self):
        original = SOURCE.read_text()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'engine/experimental/native_gpu_composer_backend.c'
            target.parent.mkdir(parents=True)
            target.write_text(original)
            subprocess.run(['patch', '-p1', '-i', str(PATCH.resolve())], cwd=directory,
                           check=True, capture_output=True)
            candidate = target.read_text()
        split = 'struct yb_gpu_composer_backend {'
        self.assertEqual(original.split(split)[0], candidate.split(split)[0])
        self.assertIn('component_buffer_slots[3]={0,2,3}', candidate)
        self.assertIn('DeleteBuffers(4,b->buffers)', candidate)
        self.assertIn('for(unsigned i=0;i<4;i++)if(b->buffers[i])', candidate)
        upload = candidate.index('static const unsigned component_buffer_slots')
        dispatch = candidate.index('g->DispatchCompute(', upload)
        self.assertLess(candidate.index('g->BufferSubData(', upload), dispatch)
        self.assertNotIn('BufferSubData', candidate[dispatch:candidate.index('g->MemoryBarrier(', dispatch)])
        self.assertEqual(original[original.index('g->MemoryBarrier('):original.index('int yb_gpu_backend_destroy(')],
                         candidate[candidate.index('g->MemoryBarrier('):candidate.index('int yb_gpu_backend_destroy(')])

    def test_all_saved_runs_and_nonwin_preserved(self):
        report = json.loads(RESULT.read_text())
        self.assertFalse(report['adopted'])
        self.assertTrue(report['canonical_backend_unchanged'])
        self.assertFalse(report['cpu_stat_throttling_recorded'])
        self.assertFalse(report['gpu_frequency_recorded'])
        self.assertEqual([run['label'] for run in report['runs']], ['A1','B1','B2','A2'])
        for run in report['runs']:
            result = run['result']
            self.assertEqual(result['status'], 'complete')
            self.assertTrue(result['full_frame_reconstructed_exact'])
            self.assertEqual(result['cpu_stage_values'], 49766400)
            self.assertEqual(result['gpu_verified_reconstructed_values'], 12441600)
            self.assertEqual(result['gpu_verified_output_planes'], 3)
            self.assertEqual(len(result['wall_ns']), 3)
            self.assertEqual(len(result['cpu_ns']), 3)
            self.assertLess(run['memory_peak_bytes'], report['memory_limit_bytes'])
            self.assertTrue(run['memory_events_all_zero'])
            self.assertEqual(run['swap_bytes'], 0)
        runs = report['runs']
        self.assertTrue(all(b > a for b, a in zip(runs[2]['result']['wall_ns'], runs[3]['result']['wall_ns'])))
        self.assertEqual(len(report['initial_failed_attempts']), 2)

if __name__ == '__main__':
    unittest.main()
