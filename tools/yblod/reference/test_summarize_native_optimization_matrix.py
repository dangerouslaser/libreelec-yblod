import json
from pathlib import Path
import tempfile
import unittest

from summarize_native_optimization_matrix import aggregate
from test_summarize_native_planar_matrix import write_planar_matrix
from test_native_planar_matrix import planar_report
from test_native_optimization_qualification import proof
from test_native_optimization_telemetry import lines


def write_matrix(root, option):
    write_planar_matrix(root)
    for order, enabled in enumerate((0, 1, 1, 0), 1):
        old = f'native-planar-{order}-flag{enabled}'
        new = f'native-optimization-{option}-{order}-flag{enabled}'
        for path in list(root.glob(old+'.*')):
            path.rename(root/(new+path.name[len(old):]))
        path = root/(new+'.json')
        raw = json.loads(path.read_text())
        raw['label'] = new
        raw['memory_samples'] = [dict(monotonic_ns=stamp, service=f'MemoryCurrent={current}\nMemoryPeak=1000\nMemoryMax=4096\n',
            private_note='do-not-publish-memory') for stamp, current in ((1_000_000_000, 100), (81_000_000_000, 200), (161_000_000_000, 300))]
        for phase in ('runtime_before', 'runtime_after'):
            raw[phase]['service'] = raw[phase]['service'] + '\nMemoryCurrent=100\nMemoryPeak=1000\n'
        correct, _ = planar_report(1)
        raw['selected_log_lines'] = [line for line in raw['selected_log_lines'] if
            'DVBridge renderer summary:' not in line and 'DVBridge native composer:' not in line]
        raw['selected_log_lines'] += [line for line in correct['selected_log_lines']
                                      if 'DVBridge renderer summary:' in line]
        for index, telemetry in enumerate(lines(option, enabled)):
            raw['selected_log_lines'].append(telemetry+
                f' fp32_selected=1 accepted_integer=0 shader_compile_failed=0 generate_failed=0'
                f' nlq_lut_enabled=1 accepted_lut={(120,480)[index]} nlq_builds=1 nlq_uploads=1'
                f' nlq_cache_hits={index*360} nlq_shader_compiles=1 cache_hits={index*240} cache_misses=1')
        path.write_text(json.dumps(raw))
    path = root/'frame-proof.json'
    path.write_text(json.dumps(proof(option)))
    return path


class Tests(unittest.TestCase):
    def test_weighted_routes_actual_use_and_scalar_privacy(self):
        for option in ('batched_planes', 'immutable_instructions'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                frame_proof = write_matrix(root, option)
                result = aggregate(root, '0'*64, option, [frame_proof])
                self.assertEqual(result['matrix'], [0, 1, 1, 0])
                self.assertEqual(result['optimization'], option)
                for phase in ('before', 'after'):
                    self.assertEqual(result[phase]['renderer_preparation_routes']['native_planar_preparation_percent'], 100)
                    self.assertEqual(result[phase]['renderer_preparation_routes']['direct_preparation_percent'], 100)
                self.assertAlmostEqual(result['before']['gpu_engine_busy_percent']['render'], (160*70+175*50)/335)
                self.assertEqual(result['lifecycle']['dv_display_restoration_failure_cases'], 4)
                self.assertEqual(result['before']['memory']['service_current_time_weighted_bytes'], 150)
                self.assertEqual(result['after']['memory']['service_current_max_bytes'], 300)
                self.assertFalse(result['after']['memory']['process_rss_available'])
                self.assertNotIn('do-not-publish', json.dumps(result, allow_nan=False))

    def test_telemetry_pixel_source_and_duration_refused(self):
        for edit in (
            lambda r: r.update(elapsed_seconds=179),
            lambda r: r.update(movie_id=51),
            lambda r: r.update(selected_log_lines=[line.replace('optimization_stats_valid=1', 'optimization_stats_valid=0') for line in r['selected_log_lines']]),
            lambda r: r.update(selected_log_lines=[line.replace('native_planar=480', 'native_planar=479') for line in r['selected_log_lines']]),
        ):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                frame_proof = write_matrix(root, 'batched_planes')
                path = root/'native-optimization-batched_planes-2-flag1.json'
                raw = json.loads(path.read_text())
                edit(raw)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64, 'batched_planes', [frame_proof])

    def test_memory_missing_malformed_regressed_incomplete_or_changed_limits_refused(self):
        for edit in (
            lambda r: r.pop('memory_samples'),
            lambda r: r['memory_samples'][0].update(monotonic_ns=True),
            lambda r: r['memory_samples'][1].update(monotonic_ns=1),
            lambda r: r['memory_samples'][-1].update(monotonic_ns=100_000_000_000),
            lambda r: r['memory_samples'][0].update(service='MemoryCurrent=bad\nMemoryPeak=1000\nMemoryMax=4096'),
            lambda r: r['memory_samples'][0].update(service='MemoryCurrent=100\nMemoryCurrent=100\nMemoryPeak=1000\nMemoryMax=4096'),
            lambda r: r['memory_samples'][0].update(service='MemoryCurrent=1001\nMemoryPeak=1000\nMemoryMax=4096'),
            lambda r: r['memory_samples'][1].update(service='MemoryCurrent=100\nMemoryPeak=999\nMemoryMax=4096'),
            lambda r: r['memory_samples'][1].update(service='MemoryCurrent=100\nMemoryPeak=1000\nMemoryMax=8192'),
            lambda r: r['runtime_after'].update(service='MemoryCurrent=100\nMemoryPeak=false'),
        ):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                frame_proof = write_matrix(root, 'batched_planes')
                path = root/'native-optimization-batched_planes-2-flag1.json'
                raw = json.loads(path.read_text())
                edit(raw)
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    aggregate(root, '0'*64, 'batched_planes', [frame_proof])


if __name__ == '__main__':
    unittest.main()
