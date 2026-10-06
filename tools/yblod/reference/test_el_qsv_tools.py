import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import el_qsv_qualification as accuracy
import el_qsv_telemetry as telemetry
import observe_el_qsv_movie as observer
import run_el_qsv_matrix as matrix
import capture_el_qsv_scene as capture

BASELINE = 'a'*64
CANDIDATE = 'b'*64


def proof(planar=1):
    value = dict(schema='yblod.el-qsv-frame-qualification.v1', baseline_binary_sha256=BASELINE,
        candidate_binary_sha256=CANDIDATE, movie_id=3391, content='Saving Private Ryan',
        seek_seconds=1200, planar_flag=planar, same_candidate_runtime_verified=True,
        target_identity_verified=True,
        retained_to_new_runtime_qsv_off=[], same_candidate_qsv_off_to_on=[])
    for comparison in ('retained_to_new_runtime_qsv_off', 'same_candidate_qsv_off_to_on'):
        for index, pts in enumerate((1210000000, 1220000000, 1230000000), 1):
            frame = dict(source_identity_verified=True, source_timestamps_equal=True,
                source_metadata_equal=True, picture_and_payload_preserved=True,
                transport_crc_valid=True, only_transport_id_crc_variation=True,
                metadata_uses_enhancement_residual=True,
                maximum_absolute_12bit_codes=dict(I=0, P=0, T=0),
                exact_picture_percent=dict(I=100, P=100, T=100))
            for phase in ('before', 'after'):
                qsv = int(comparison == 'same_candidate_qsv_off_to_on' and phase == 'after')
                selected = dict(native=1, direct_packed=1, native_planar=planar, qsv_mode=1,
                    batched_planes=0, immutable_instructions=0)
                legacy = comparison == 'retained_to_new_runtime_qsv_off' and phase == 'before'
                if not legacy:
                    selected.update(el_decoder_qsv=qsv, el_qsv_native_used=qsv,
                                    el_qsv_map_sequence=index if qsv else 0)
                frame[phase] = dict(binary_sha256=BASELINE if legacy else CANDIDATE,
                    pts_microseconds=pts, el_pts_microseconds=pts, route=selected)
            frame['raw_enhancement'] = dict(source_identity_verified=True, target_identity_verified=True,
                active_geometry_equal=True, chroma_location_equal=True, colour_properties_equal=True,
                original_timestamps_equal=True, format='P010', code_bit_depth=10,
                active_width=1920, active_height=1080, before_pts_microseconds=pts,
                after_pts_microseconds=pts, planes={plane: dict(sample_count=count,
                    differing_samples=0, differing_storage_samples=0,
                    maximum_absolute_sample_codes=0, p010_low_bits_zero=True)
                    for plane, count in dict(Y=1920*1080, U=960*540, V=960*540).items()})
            value[comparison].append(frame)
    return value


def lines(enabled):
    result = []
    for paired in (120, 480):
        result.append(f'DV FEL decoder: qsv_selected={enabled} '
            f'qsv_mapped_frames={enabled*(paired+8)} paired_frames={paired}')
    # Independent interval: renderer operations need not equal decoder pairs.
    for prepared in (200, 800):
        result.append(f'DVBridge renderer summary: prepared={prepared} '
            f'el_qsv_prepared={enabled*prepared} el_qsv_native_used={enabled*prepared}')
    return result


class Accuracy(unittest.TestCase):
    def test_both_planar_routes_pass(self):
        for planar in (0, 1):
            got = accuracy.qualify_document(proof(planar), BASELINE, CANDIDATE, planar)
            self.assertEqual(got['frame_count'], 3)
            self.assertTrue(got['raw_active_EL_samples_equal'])

    def test_top_identity_and_runtime_refused(self):
        for key, value in (('schema', 'wrong'), ('movie_id', True), ('content', '1917'),
                           ('candidate_binary_sha256', BASELINE), ('planar_flag', True),
                           ('same_candidate_runtime_verified', 1), ('target_identity_verified', 1)):
            report = proof()
            report[key] = value
            with self.assertRaises(ValueError):
                accuracy.qualify_document(report, BASELINE, CANDIDATE, 1)

    def test_every_source_accuracy_metadata_bool_required(self):
        for key in ('source_identity_verified', 'source_timestamps_equal', 'source_metadata_equal',
                    'picture_and_payload_preserved', 'transport_crc_valid',
                    'only_transport_id_crc_variation', 'metadata_uses_enhancement_residual'):
            report = proof()
            report['same_candidate_qsv_off_to_on'][0][key] = 1
            with self.assertRaises(ValueError):
                accuracy.qualify_document(report, BASELINE, CANDIDATE, 1)

    def test_pixels_and_actual_route_cannot_be_tolerated(self):
        changes = [('maximum_absolute_12bit_codes', 'I', 1), ('exact_picture_percent', 'P', 99.999)]
        for key, plane, value in changes:
            report = proof()
            report['same_candidate_qsv_off_to_on'][0][key][plane] = value
            with self.assertRaises(ValueError):
                accuracy.qualify_document(report, BASELINE, CANDIDATE, 1)
        for key, value in (('el_decoder_qsv', 0), ('el_qsv_native_used', 0),
                           ('el_qsv_map_sequence', 0), ('el_qsv_map_sequence', True),
                           ('batched_planes', 1), ('qsv_mode', 0), ('native_planar', 0)):
            report = proof()
            report['same_candidate_qsv_off_to_on'][0]['after']['route'][key] = value
            with self.assertRaises(ValueError):
                accuracy.qualify_document(report, BASELINE, CANDIDATE, 1)

    def test_raw_sample_and_properties_strict(self):
        for key, value in (('active_geometry_equal', False), ('chroma_location_equal', False),
                           ('colour_properties_equal', False), ('original_timestamps_equal', False),
                           ('source_identity_verified', False), ('active_height', 1088),
                           ('before_pts_microseconds', 1210000001), ('code_bit_depth', 12)):
            report = proof()
            report['same_candidate_qsv_off_to_on'][0]['raw_enhancement'][key] = value
            with self.assertRaises(ValueError):
                accuracy.qualify_document(report, BASELINE, CANDIDATE, 1)
        for key, value in (('sample_count', 1), ('differing_samples', 1),
                           ('differing_storage_samples', 1), ('maximum_absolute_sample_codes', 1),
                           ('p010_low_bits_zero', 1)):
            report = proof()
            report['same_candidate_qsv_off_to_on'][0]['raw_enhancement']['planes']['Y'][key] = value
            with self.assertRaises(ValueError):
                accuracy.qualify_document(report, BASELINE, CANDIDATE, 1)

    def test_frame_order_and_association_strict(self):
        for mutation in ('short', 'duplicate', 'pts', 'sequence', 'different_sets'):
            report = proof()
            frames = report['same_candidate_qsv_off_to_on']
            if mutation == 'short':
                frames.pop()
            elif mutation == 'duplicate':
                frames[1] = copy.deepcopy(frames[0])
            elif mutation == 'pts':
                frames[0]['after']['el_pts_microseconds'] += 1
            elif mutation == 'sequence':
                frames[1]['after']['route']['el_qsv_map_sequence'] = 1
            else:
                report['retained_to_new_runtime_qsv_off'][0]['before']['pts_microseconds'] += 1
            with self.assertRaises(ValueError):
                accuracy.qualify_document(report, BASELINE, CANDIDATE, 1)


class Telemetry(unittest.TestCase):
    def test_independent_intervals_not_equated(self):
        for enabled in (0, 1):
            got = telemetry.qualify_actual_el_use(lines(enabled), enabled)
            self.assertEqual(got['decoder_interval_deltas']['paired_frames'], 360)
            self.assertEqual(got['renderer_interval_deltas']['prepared'], 600)

    def test_missing_wrong_reset_or_non_native_rejected(self):
        invalid = [lines(1)[1:], [], lines(0),
            [line.replace('qsv_selected=1', 'qsv_selected=0') for line in lines(1)],
            [line.replace('el_qsv_native_used=800', 'el_qsv_native_used=799') for line in lines(1)],
            [line.replace('qsv_mapped_frames=488', 'qsv_mapped_frames=2') for line in lines(1)],
            [line.replace('paired_frames=480', 'paired_frames=True') for line in lines(1)]]
        for value in invalid:
            with self.assertRaises(ValueError):
                telemetry.qualify_actual_el_use(value, 1)

    def test_control_must_have_no_actual_qsv_work(self):
        value = [line.replace('el_qsv_prepared=0', 'el_qsv_prepared=1') for line in lines(0)]
        with self.assertRaises(ValueError):
            telemetry.qualify_actual_el_use(value, 0)


class Integration(unittest.TestCase):
    def test_controller_source_and_subtitle_fixture_gates(self):
        original = dict(enabled=True, index=0)
        disabled = dict(enabled=False, index=0)
        report = dict(movie_id=3391, media='Saving Private Ryan', requested_seconds=180,
            seek_seconds=1200, expected_route='fp32', selected_log_lines=lines(1),
            elapsed_seconds=181, gpu_intervals=[dict(elapsed_seconds=151,
                engine_busy_percent={'drm-engine-render': 30})],
            subtitle_fixture=dict(movie_id=3391, player_id=1, requested_enabled=False,
                before=original.copy(), disabled=disabled.copy(), disabled_at_end=disabled.copy(),
                restored=original.copy()))
        validator = matrix.make_validator(1)
        with patch.object(matrix, 'validate_planar_report', return_value={'whole_process_cpu': {'elapsed_seconds':151}}), \
                patch.object(matrix, 'qualify_actual_use', return_value={'actual_use_verified': True}):
            self.assertTrue(validator(report, {}, 1, CANDIDATE)['EL_decoder']['actual_EL_use_verified'])
            for key, value in (('movie_id', 51), ('media', '1917'), ('requested_seconds', 120),
                               ('seek_seconds', 0), ('expected_route', 'integer')):
                bad = copy.deepcopy(report)
                bad[key] = value
                with self.assertRaises(ValueError):
                    validator(bad, {}, 1, CANDIDATE)
            bad = copy.deepcopy(report)
            bad['subtitle_fixture']['before']['enabled'] = False
            bad['subtitle_fixture']['restored']['enabled'] = False
            with self.assertRaises(ValueError):
                validator(bad, {}, 1, CANDIDATE)
            bad = copy.deepcopy(report)
            bad['subtitle_fixture']['disabled_at_end']['enabled'] = True
            with self.assertRaises(ValueError):
                validator(bad, {}, 1, CANDIDATE)

    def test_performance_interval_coverage_not_requested_seconds_alone(self):
        report = dict(elapsed_seconds=181, gpu_intervals=[dict(elapsed_seconds=151,
                      engine_busy_percent={'drm-engine-render': 30})])
        qualification = dict(whole_process_cpu=dict(elapsed_seconds=151))
        matrix.validate_intervals(report, qualification)
        for changed in (dict(elapsed_seconds=179, gpu_intervals=report['gpu_intervals']),
                        dict(elapsed_seconds=True, gpu_intervals=report['gpu_intervals']),
                        dict(elapsed_seconds=181, gpu_intervals=[]),
                        dict(elapsed_seconds=181, gpu_intervals=[dict(unavailable='changed')]),
                        dict(elapsed_seconds=181, gpu_intervals=[dict(elapsed_seconds=150,
                             engine_busy_percent={'drm-engine-render': float('nan')})])):
            with self.assertRaises(ValueError):
                matrix.validate_intervals(changed, qualification)
        with self.assertRaises(ValueError):
            matrix.validate_intervals(report, dict(whole_process_cpu=dict(elapsed_seconds=149)))

    def test_configs_only_decoder_changes_for_both_planar_modes(self):
        root = Path(__file__).parent
        for planar in (0, 1):
            for capture_mode in (False, True):
                paths = [root/f'{"capture" if capture_mode else "native"}-el-qsv-planar{planar}-flag{flag}.conf'
                         for flag in (0, 1)]
                matrix.validate_configs(paths, planar, capture_mode)

    def test_config_capture_and_other_flags_refused(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(__file__).with_name('native-el-qsv-planar1-flag0.conf').read_text()
            paths = [Path(name)/f'{flag}.conf' for flag in (0, 1)]
            for original, changed in (('CAPTURE_OUTPUTS=0', 'CAPTURE_OUTPUTS=1'),
                ('IMMUTABLE_INSTRUCTIONS=0', 'IMMUTABLE_INSTRUCTIONS=1'),
                ('DVBRIDGE_FEL_QSV=1', 'DVBRIDGE_FEL_QSV=true'),
                ('PLANAR_OUTPUT=1', 'PLANAR_OUTPUT=0')):
                paths[0].write_text(base)
                paths[1].write_text(base.replace('FEL_QSV=0', 'FEL_QSV=1').replace(original, changed))
                with self.assertRaises(ValueError):
                    matrix.validate_configs(paths, 1)

    def test_observer_addition_is_source_bound_and_only_markers(self):
        source = Path(__file__).with_name('observe_native_movie.py').read_text()
        changed = observer.with_el_markers(source)
        self.assertEqual(changed.count("'DV FEL decoder:',"), 2)
        self.assertEqual(changed.replace(" 'DV FEL decoder:',", ''), source)
        compile(changed, '<observer-mock>', 'exec')
        with self.assertRaises(ValueError):
            observer.with_el_markers("'DVBridge native composer:',")

    def test_capture_wrapper_restores_functions_and_actual_route_checks(self):
        args = SimpleNamespace()
        selected = SimpleNamespace(el_qsv_flag=1, planar_flag=1)
        old_parser, old_route = capture.capture_scene.parse_args, capture.capture_scene.verify_capture_route
        good = proof()['same_candidate_qsv_off_to_on'][0]['after']['route']
        def run_capture():
            capture.capture_scene.verify_capture_route(good, args)
        with patch.object(capture, 'request', return_value=(selected, args)), \
                patch.object(capture.capture_scene, 'main', side_effect=run_capture), \
                patch.object(capture.capture_scene, 'verify_capture_route') as original:
            mocked = capture.capture_scene.verify_capture_route
            capture.main([])
            self.assertIs(capture.capture_scene.verify_capture_route, mocked)
            original.assert_called_once_with(good, args)
        self.assertIs(capture.capture_scene.parse_args, old_parser)
        self.assertIs(capture.capture_scene.verify_capture_route, old_route)

    def test_capture_wrapper_restores_after_bad_actual_route(self):
        selected = SimpleNamespace(el_qsv_flag=1, planar_flag=1)
        args = SimpleNamespace()
        before_parser, before_route = capture.capture_scene.parse_args, capture.capture_scene.verify_capture_route
        bad = proof()['same_candidate_qsv_off_to_on'][0]['after']['route']
        bad['el_qsv_native_used'] = 0
        def failed_capture():
            capture.capture_scene.verify_capture_route(bad, args)
        with patch.object(capture, 'request', return_value=(selected, args)), \
                patch.object(capture.capture_scene, 'main', side_effect=failed_capture), \
                patch.object(capture.capture_scene, 'verify_capture_route'):
            with self.assertRaises(ValueError):
                capture.main([])
        self.assertIs(capture.capture_scene.parse_args, before_parser)
        self.assertIs(capture.capture_scene.verify_capture_route, before_route)

    def test_capture_request_requires_binary_scene_fixture_and_known_config(self):
        root = Path(__file__).parent
        args = SimpleNamespace(binary_sha256=CANDIDATE, movie_id=3391,
            expected_title='Saving Private Ryan', file=None, seek_seconds=1200,
            subtitles_off=True, view_zoom=None, expected_native=1, expected_direct_packed=1,
            expected_native_planar=1, expected_batched_planes=0, expected_immutable_instructions=0,
            config=root/'capture-el-qsv-planar1-flag1.conf')
        argv = ['--el-qsv-flag', '1', '--planar-flag', '1']
        with patch.object(capture.capture_scene, 'parse_args', return_value=args):
            capture.request(argv)
        for key, value in (('binary_sha256', None), ('movie_id', 51), ('subtitles_off', False),
                           ('view_zoom', .9), ('expected_native_planar', 0),
                           ('expected_immutable_instructions', 1)):
            bad = copy.copy(args)
            setattr(bad, key, value)
            with patch.object(capture.capture_scene, 'parse_args', return_value=bad), \
                    self.assertRaises(ValueError):
                capture.request(argv)


if __name__ == '__main__':
    unittest.main()
