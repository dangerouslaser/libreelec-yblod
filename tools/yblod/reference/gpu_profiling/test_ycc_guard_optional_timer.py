import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

GUARD = Path(__file__).with_name('run_ycc_timer_guard.sh')
VALIDATE = GUARD.read_text().split("python3 - <<'PY'\n", 1)[1].split('\nPY', 1)[0]


def result(timer):
    record = dict(schema='yblod.gpu-ycc-frame-timer-probe.v1', complete=True,
                  cleanup_complete=True, independent_dyadic_integer_oracle=True,
                  width=3840, height=2160, full_image_oracle_checks=2,
                  float_values_bit_compared=66355200, warmups=8, samples=12,
                  gpu_timer_query_requested=timer, linked_workgroup=[8,8,1],
                  host_submit_finish_wall_ns=[10]*12, host_submit_finish_cpu_ns=[1]*12)
    if timer:
        record.update(gpu_timer_extra_fences=0, gpu_timer_extra_waits=0,
                      gpu_elapsed_ns=[5]*12)
    return record


class OptionalTimerGuard(unittest.TestCase):
    def validate(self, record, timer):
        with patch.object(Path, 'read_text', return_value=json.dumps(record)), \
                patch.dict(os.environ, YB_GPU_DIAG_TIMER=timer), \
                contextlib.redirect_stdout(io.StringIO()):
            exec(compile(VALIDATE, str(GUARD), 'exec'), {})

    def test_default_disabled(self):
        self.assertIn('timer=${YB_GPU_DIAG_TIMER:-0}', GUARD.read_text())
        self.validate(result(False), '0')

    def test_enabled(self):
        self.validate(result(True), '1')

    def test_disabled_rejects_fake_gpu_array(self):
        record = result(False)
        record['gpu_elapsed_ns'] = [5]*12
        with self.assertRaises(AssertionError):
            self.validate(record, '0')

    def test_enabled_rejects_zero_gpu_results(self):
        record = result(True)
        record['gpu_elapsed_ns'] = [0]*12
        with self.assertRaises(AssertionError):
            self.validate(record, '1')

    def test_rejects_mode_mismatch(self):
        with self.assertRaises(AssertionError):
            self.validate(result(False), '1')

    def test_rejects_invalid_mode_before_artifact_access(self):
        env = dict(os.environ, YB_GPU_DIAG_TIMER='invalid')
        completed = subprocess.run(['sh', str(GUARD), *(['unused']*7)], env=env,
                                   capture_output=True)
        self.assertEqual(completed.returncode, 2)

    def test_rejects_incomplete_oracle(self):
        record = result(False)
        record['float_values_bit_compared'] -= 1
        with self.assertRaises(AssertionError):
            self.validate(record, '0')


if __name__ == '__main__':
    unittest.main()
