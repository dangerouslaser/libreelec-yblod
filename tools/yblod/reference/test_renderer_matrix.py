import copy
import unittest
from run_renderer_matrix import legacy_route, validate_renderer_report


def logs():
    return [
        'DVBridge: Quick Sync on the Intel media engine: enhancement layer upscale',
        'DVBridge first frame: source=3840x2160 output=3840x2160 enhancement=true fel=true direct=true',
        'DVBridge conversion: requested=true active=direct-lms packed=true source=3840x2160 rotation=0',
        'DVBridge renderer summary: prepared=720 direct=720 composed=0 presented=720 presentation_failures=0 stage_failures=0',
    ]


class Tests(unittest.TestCase):
    def test_affirmative_legacy_route(self):
        self.assertTrue(legacy_route(logs())['el_only_media_scaling'])

    def test_missing_or_wrong_scaling_rejected(self):
        for changed in (logs()[1:], [line.replace('enhancement layer upscale', 'base layer colour') for line in logs()]):
            with self.assertRaises(ValueError):
                legacy_route(changed)

    def test_native_work_and_fallback_rejected(self):
        for line in ('DVBridge native composer: accepted_fp32=240',
                     'DVBridge native reconstruction: presented=240',
                     'DVBridge: Quick Sync scaling unavailable (driver)',
                     'DVBridge renderer: stage=render-prepare failures=1'):
            with self.assertRaises(ValueError):
                legacy_route(logs() + [line])

    def test_wrong_fel_or_failed_presentations_rejected(self):
        for old, new in (('fel=true', 'fel=false'), ('enhancement=true', 'enhancement=false'),
                         ('presented=720', 'presented=0'), ('stage_failures=0', 'stage_failures=1')):
            with self.assertRaises(ValueError):
                legacy_route([line.replace(old, new) for line in logs()])

    def test_identity_stop_and_cpu_gates(self):
        service = 'MainPID=1\nActiveEnterTimestampMonotonic=100\n'
        runtime = dict(binary_sha256='0'*64, service=service)
        samples = [dict(pid=1, process_start_ticks=100, clock_ticks_per_second=100,
                        process_cpu_ticks=10, monotonic_ns=1_000_000_000),
                   dict(pid=1, process_start_ticks=100, clock_ticks_per_second=100,
                        process_cpu_ticks=30, monotonic_ns=2_000_000_000)]
        report = dict(failure_marker=False, log_rotated_or_truncated=False,
            kodi_before=service, kodi_after=service, runtime_before=runtime,
            runtime_after=runtime, route_log_lines=logs(), gpu_samples=samples)
        stopped = dict(active_players=[], runtime=runtime)
        self.assertTrue(validate_renderer_report(report, stopped, 0, '0'*64)
                        ['observer_and_player_stop_integrity_passed'])
        for changed in (dict(active_players=[1], runtime=runtime),
                        dict(active_players=[], runtime=dict(runtime,binary_sha256='1'*64))):
            with self.assertRaises(ValueError):
                validate_renderer_report(report, changed, 0, '0'*64)


if __name__ == '__main__':
    unittest.main()
