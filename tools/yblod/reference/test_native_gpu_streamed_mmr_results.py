"""Saved public corpus/compiler evidence checks; does not access a GPU."""
import hashlib
import json
from pathlib import Path
import unittest
from native_gpu_shader_inspection import parse
from native_gpu_run import validate_cpu,validate_gpu
from native_gpu_vectors import vector_fixtures

HERE=Path(__file__).resolve().parent
RESULTS=HERE/'results'
REPORT=RESULTS/'native-gpu-streamed-mmr-synthetic-20261005a.json'

class StreamedResultsTests(unittest.TestCase):
    def test_pins_and_counts(self):
        report=json.loads(REPORT.read_text())
        self.assertEqual(report['status'],'complete')
        self.assertEqual((len(report['cases']),report['gpu_case_count'],report['unsupported_case_count'],report['checked_stage_values']),(32,31,1,8512))
        shader=HERE.parents[2]/'engine'/'experimental'/'native_gpu_streamed_mmr_probe.comp'
        self.assertEqual(hashlib.sha256(shader.read_bytes()).hexdigest(),report['candidate_sha256'])
        self.assertEqual(hashlib.sha256((HERE/'native_gpu_streamed_mmr_run.py').read_bytes()).hexdigest(),report['runner_sha256'])
        self.assertTrue(report['all_independent_cpu_gates_complete'])
    def test_all_saved_cases_against_independent_oracle(self):
        report=json.loads(REPORT.read_text());vectors={v.name:v for v in vector_fixtures()}
        self.assertEqual({c['name'] for c in report['cases']},vectors.keys())
        count=0
        for case in report['cases']:
            v=vectors[case['name']]
            eligible=validate_cpu(case['cpu'],v)
            self.assertEqual(eligible,case['gpu_eligible'])
            if eligible:validate_gpu(case['gpu'],v);count+=len(v.triplets)*4
            else:self.assertNotIn('gpu',case)
        self.assertEqual(count,8512)
    def test_compiler_evidence(self):
        log=(RESULTS/'native-gpu-streamed-mmr-compiler-20261005a.log').read_bytes()
        stats=json.loads((RESULTS/'native-gpu-streamed-mmr-compiler-stats-20261005a.json').read_text())
        self.assertEqual(parse(log),stats)
        self.assertEqual((stats['statistics']['simd_width'],stats['statistics']['spill_count'],stats['statistics']['fill_count']),(16,0,0))
        self.assertFalse(stats['statistics_are_measured_runtime'])
    def test_resource_and_identity_limits(self):
        report=json.loads(REPORT.read_text())
        self.assertEqual(report['kodi_before'],report['kodi_after'])
        self.assertEqual(report['runtime_library_sha256_before'],report['runtime_library_sha256_after'])
        for phase in ('cgroup_before','cgroup_after'):
            values=report[phase]['values']
            self.assertEqual(values['memory.max'],'536870912')
            self.assertEqual(values['memory.swap.max'],'0');self.assertEqual(values['memory.swap.current'],'0')
            self.assertTrue(all(int(line.split()[1])==0 for line in values['memory.events'].splitlines()))
            self.assertLessEqual(int(values['memory.peak']),536870912)

if __name__=='__main__':unittest.main()
