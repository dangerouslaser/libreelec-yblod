import copy
import json
from pathlib import Path
import tempfile
import unittest

from run_colour_import_matrix import parser, SCOPE
from run_native_packed_matrix import (packed_summary, preservation_report,
                                      validate_packed_args, validate_packed_report)


def renderer_line(prepared, direct):
    return ('DVBridge renderer summary: '
            f'prepared={prepared} direct={direct} composed={prepared-direct} presented={prepared} '
            'presentation_failures=0 stage_failures=0')


def route_lines(flag):
    return [renderer_line(120, 100 if flag else 0),
            renderer_line(480, 460 if flag else 0)]


def frame_qualification():
    return dict(schema='yblod.renderer-output-comparison.v1',
                identical_source_layer_timestamps=True, identical_source_metadata=True,
                output_preserved=True, picture_and_payload_preservation=None,
                before=dict(native=1, direct_packed=0, valid_leading_packets=3),
                after=dict(native=1, direct_packed=1, valid_leading_packets=3),
                planes={name: dict(max_absolute_codes=0, exact_percent=100)
                        for name in ('I', 'P', 'T')})


def full_report(flag):
    lines = route_lines(flag)
    for count in (120, 480):
        lines += [
            f'DVBridge native reconstruction: presented={count} colour=inherited-release colour_imports=metadata-only',
            f'DVBridge native colour handoff: calls={count} valid=true imports=metadata-only '
            f'wall_ms_per_call=1.000 thread_cpu_ms_per_call=0.200 scope={SCOPE}',
            f'DVBridge native composer: nlq_lut_enabled=1 accepted_lut={count} '
            f'fp32_selected=1 accepted_fp32={count} accepted_integer=0 nlq_builds=1 '
            f'nlq_uploads=1 nlq_cache_hits={count-1} nlq_shader_compiles=1 '
            'shader_compile_failed=0 generate_failed=0',
        ]
    service = 'MainPID=1\nActiveEnterTimestampMonotonic=100\n'
    runtime = dict(binary_sha256='0'*64, service=service)
    samples = [dict(pid=1, process_start_ticks=100, clock_ticks_per_second=100,
                    process_cpu_ticks=10, monotonic_ns=1_000_000_000),
               dict(pid=1, process_start_ticks=100, clock_ticks_per_second=100,
                    process_cpu_ticks=30, monotonic_ns=2_000_000_000)]
    report = dict(failure_marker=False, log_rotated_or_truncated=False,
                  kodi_before=service, kodi_after=service, runtime_before=runtime,
                  runtime_after=runtime, selected_log_lines=lines, gpu_samples=samples,
                  route_log_lines=['DVBridge conversion: requested=true active=release-rgb packed=false'])
    return report, dict(active_players=[], runtime=runtime)


class Tests(unittest.TestCase):
    def test_actual_route_for_both_flags(self):
        for flag in (0, 1):
            summary = packed_summary(route_lines(flag), flag)
            self.assertEqual(summary['packed_preparation_percent'], 100*flag)
            report, stopped = full_report(flag)
            self.assertEqual(validate_packed_report(report, stopped, flag, '0'*64)
                             ['packed_output']['requested_flag'], flag)

    def test_flag_request_cannot_substitute_for_route(self):
        for flag in (0, 1):
            with self.assertRaises(ValueError):
                packed_summary(route_lines(1-flag), flag)
        with self.assertRaises(ValueError):
            packed_summary([renderer_line(120, 100), renderer_line(480, 459)], 1)

    def test_counter_failures_missing_or_reset_rejected(self):
        for lines in ([], [renderer_line(120, 100)],
                      [renderer_line(480, 460), renderer_line(120, 100)],
                      [renderer_line(120, 100), renderer_line(240, 220)],
                      [line.replace('stage_failures=0', 'stage_failures=1') for line in route_lines(1)],
                      [line.replace('presentation_failures=0', 'presentation_failures=1') for line in route_lines(1)],
                      [line.replace('composed=20', 'composed=21') for line in route_lines(1)]):
            with self.assertRaises(ValueError):
                packed_summary(lines, 1)

    def test_colour_math_native_lut_identity_and_stop_gates(self):
        for mutate in (
            lambda r, s: r['route_log_lines'].append('DVBridge conversion: active=direct-lms'),
            lambda r, s: r['selected_log_lines'].append('DVBridge native reconstruction: fallback=release'),
            lambda r, s: r['selected_log_lines'].append('DVBridge native packed output failed; using composition'),
            lambda r, s: r['runtime_after'].update(binary_sha256='1'*64),
            lambda r, s: s.update(active_players=[1]),
            lambda r, s: r.update(selected_log_lines=[line.replace('accepted_lut=480', 'accepted_lut=479')
                                                      for line in r['selected_log_lines']]),
        ):
            report, stopped = full_report(1)
            mutate(report, stopped)
            with self.assertRaises(ValueError):
                validate_packed_report(report, stopped, 1, '0'*64)

    def test_exact_and_validated_transport_id_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'preserved.json'
            report = frame_qualification()
            path.write_text(json.dumps(report))
            self.assertTrue(preservation_report(path)['all_tunnel_rgb_bytes_identical'])
            report['output_preserved'] = False
            report['picture_and_payload_preservation'] = dict(picture_and_payload_preserved=True)
            path.write_text(json.dumps(report))
            self.assertTrue(preservation_report(path)['picture_and_payload_preserved'])

    def test_changed_picture_wrong_source_or_route_rejected(self):
        edits = [lambda r: r.update(output_preserved=False),
                 lambda r: r.update(identical_source_metadata=False),
                 lambda r: r.update(identical_source_layer_timestamps=False),
                 lambda r: r['before'].update(native=0),
                 lambda r: r['after'].update(direct_packed=0),
                 lambda r: r['after'].update(valid_leading_packets=0),
                 lambda r: r['planes']['P'].update(max_absolute_codes=1),
                 lambda r: r['planes']['I'].update(exact_percent=99),
                 lambda r: r['planes'].pop('T')]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'preserved.json'
            for edit in edits:
                report = frame_qualification()
                edit(report)
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    preservation_report(path)

    def test_exact_flags_fixed_scene_and_preservation_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'out'
            root.mkdir()
            proof = Path(temp)/'preserved.json'
            proof.write_text(json.dumps(frame_qualification()))
            args = parser().parse_args(['--binary-sha256', '0'*64, '--root', str(root),
                '--observer', str(Path(__file__).with_name('observe_native_movie.py')),
                '--config-dir', str(Path(__file__).parent), '--movie-id', '3391',
                '--expected-title', 'Saving Private Ryan', '--seek-seconds', '1200', '--seconds', '180'])
            args.preservation_report = [proof]
            validate_packed_args(args)
            for key, value in (('seconds', 300), ('movie_id', 51), ('seek_seconds', 1210),
                               ('expected_title', '1917'), ('preservation_report', [])):
                changed = copy.copy(args)
                setattr(changed, key, value)
                with self.assertRaises(ValueError):
                    validate_packed_args(changed)

    def test_configuration_variance_and_capture_override_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'out'
            root.mkdir()
            proof = Path(temp)/'preserved.json'
            proof.write_text(json.dumps(frame_qualification()))
            args = parser().parse_args(['--binary-sha256', '0'*64, '--root', str(root),
                '--observer', str(Path(__file__).with_name('observe_native_movie.py')),
                '--config-dir', temp, '--movie-id', '3391', '--expected-title', 'Saving Private Ryan',
                '--seek-seconds', '1200', '--seconds', '180'])
            args.preservation_report = [proof]
            configs = [(Path(__file__).with_name(f'native-packed-{flag}.conf')).read_text()
                       for flag in (0, 1)]
            for addition in ('Environment=DVBRIDGE_CAPTURE_OUTPUTS=1\n',
                             'Environment=DVBRIDGE_NATIVE_FP32=0\n',
                             'Environment=DVBRIDGE_NATIVE_PACKED_OUTPUT=0\n',
                             'Environment=UNRELATED_DIFFERENCE=1\n'):
                for flag in (0, 1):
                    (Path(temp)/f'native-packed-{flag}.conf').write_text(
                        configs[flag] + (addition if flag else ''))
                with self.assertRaises(ValueError):
                    validate_packed_args(args)


if __name__ == '__main__':
    unittest.main()
