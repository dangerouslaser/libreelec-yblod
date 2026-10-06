import copy
import json
from pathlib import Path
import tempfile
import unittest

from run_colour_import_matrix import parser
from run_native_planar_matrix import (planar_preservation_report, planar_summary,
                                      validate_planar_args, validate_planar_report)
from test_native_packed_matrix import frame_qualification, full_report


def planar_frame():
    report = frame_qualification()
    report['before'].update(direct_packed=1, native_planar=0)
    report['after'].update(direct_packed=1, native_planar=1)
    return report


def planar_report(flag):
    report, stopped = full_report(1)
    lines = []
    for line in report['selected_log_lines']:
        if 'DVBridge renderer summary:' in line:
            prepared = int(line.split('prepared=', 1)[1].split()[0])
            line += f' native_planar={prepared if flag else 0}'
        lines.append(line)
    report['selected_log_lines'] = lines
    return report, stopped


class Tests(unittest.TestCase):
    def test_actual_planar_and_packed_work_matches_both_flags(self):
        for flag in (0, 1):
            report, stopped = planar_report(flag)
            result = validate_planar_report(report, stopped, flag, '0'*64)
            self.assertEqual(result['native_planar']['planar_preparation_percent'], flag*100)
            self.assertEqual(result['packed_output']['packed_preparation_percent'], 100)

    def test_missing_wrong_partial_regressed_planar_or_composed_work_refused(self):
        edits = (lambda line: line.replace(' native_planar=480', ''),
                 lambda line: line.replace('native_planar=480', 'native_planar=479'),
                 lambda line: line.replace('native_planar=480', 'native_planar=119'),
                 lambda line: line.replace('native_planar=480', 'native_planar=481'),
                 lambda line: line.replace('direct=460 composed=20', 'direct=400 composed=80'))
        for edit in edits:
            report, _ = planar_report(1)
            with self.assertRaises(ValueError):
                planar_summary([edit(line) for line in report['selected_log_lines']], 1)
        report, _ = planar_report(1)
        with self.assertRaises(ValueError):
            planar_summary(report['selected_log_lines'], 0)

    def test_fallback_failure_binary_and_stage_errors_refused(self):
        for mutate in (lambda r: r['selected_log_lines'].append('DVBridge native reconstruction: stage=finish fallback=release'),
                       lambda r: r['selected_log_lines'].append('DVBridge native packed output failed; using composition'),
                       lambda r: r['runtime_after'].update(binary_sha256='1'*64),
                       lambda r: r.update(selected_log_lines=[line.replace('stage_failures=0', 'stage_failures=1')
                                                              for line in r['selected_log_lines']])):
            report, stopped = planar_report(1)
            mutate(report)
            with self.assertRaises(ValueError):
                validate_planar_report(report, stopped, 1, '0'*64)

    def test_exact_planar_preservation_and_metadata_id_allowance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'proof.json'
            report = planar_frame()
            path.write_text(json.dumps(report))
            self.assertTrue(planar_preservation_report(path)['all_tunnel_rgb_bytes_identical'])
            report['output_preserved'] = False
            report['picture_and_payload_preservation'] = dict(picture_and_payload_preserved=True)
            path.write_text(json.dumps(report))
            self.assertTrue(planar_preservation_report(path)['picture_and_payload_preserved'])

    def test_missing_or_wrong_planar_route_and_changed_pixels_refused(self):
        edits = (lambda r: r['before'].pop('native_planar'),
                 lambda r: r['after'].update(native_planar=0),
                 lambda r: r['before'].update(direct_packed=0),
                 lambda r: r['after'].update(valid_leading_packets=0),
                 lambda r: r.update(identical_source_metadata=False),
                 lambda r: r['planes']['T'].update(max_absolute_codes=1),
                 lambda r: r.update(output_preserved=False))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'proof.json'
            for edit in edits:
                report = planar_frame()
                edit(report)
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    planar_preservation_report(path)

    def make_args(self, directory, configs=None):
        root = Path(directory)/'output'
        root.mkdir()
        proof = Path(directory)/'proof.json'
        proof.write_text(json.dumps(planar_frame()))
        args = parser().parse_args(['--binary-sha256', '0'*64, '--root', str(root),
            '--observer', str(Path(__file__).with_name('observe_native_movie.py')),
            '--config-dir', str(configs or Path(__file__).parent), '--movie-id', '3391',
            '--expected-title', 'Saving Private Ryan', '--seconds', '180', '--seek-seconds', '1200'])
        args.preservation_report = [proof]
        return args

    def test_fixed_scene_duration_and_preservation_required(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.make_args(directory)
            validate_planar_args(args)
            for key, value in (('seconds', 600), ('movie_id', 51), ('seek_seconds', 0),
                               ('expected_title', '1917'), ('preservation_report', [])):
                changed = copy.copy(args)
                setattr(changed, key, value)
                with self.assertRaises(ValueError):
                    validate_planar_args(changed)

    def test_only_planar_flag_may_differ_and_capture_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.make_args(directory, directory)
            originals = [Path(__file__).with_name(f'native-planar-{flag}.conf').read_text() for flag in (0, 1)]
            for addition in ('Environment=DVBRIDGE_NATIVE_PACKED_OUTPUT=0\n',
                             'Environment=DVBRIDGE_NATIVE_PLANAR_OUTPUT=0\n',
                             'Environment=DVBRIDGE_CAPTURE_OUTPUTS=1\n',
                             'Environment=UNRELATED=1\n'):
                for flag in (0, 1):
                    (Path(directory)/f'native-planar-{flag}.conf').write_text(originals[flag]+(addition if flag else ''))
                with self.assertRaises(ValueError):
                    validate_planar_args(args)

    def test_capture_configs_preserve_packed_or_composed_mode(self):
        for mode, packed in (('packed', 1), ('composed', 0)):
            normalized = []
            for flag in (0, 1):
                lines = Path(__file__).with_name(f'capture-native-planar-{mode}-{flag}.conf').read_text().splitlines()
                marker = f'Environment=DVBRIDGE_NATIVE_PLANAR_OUTPUT={flag}'
                self.assertEqual(lines.count(marker), 1)
                self.assertIn(f'Environment=DVBRIDGE_NATIVE_PACKED_OUTPUT={packed}', lines)
                self.assertIn('Environment=DVBRIDGE_CAPTURE_OUTPUTS=1', lines)
                self.assertIn('Environment=DVBRIDGE_CAPTURE_PAIRS=0', lines)
                normalized.append([line for line in lines if line != marker])
            self.assertEqual(normalized[0], normalized[1])


if __name__ == '__main__':
    unittest.main()
