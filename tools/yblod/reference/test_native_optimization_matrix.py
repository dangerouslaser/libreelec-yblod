import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import run_native_optimization_matrix as module
from test_native_optimization_qualification import proof
from test_native_planar_matrix import planar_report


class Tests(unittest.TestCase):
    def args(self, root, option='batched_planes'):
        path = root/'proof.json'
        path.write_text(json.dumps(proof(option)))
        args = SimpleNamespace(optimization=option, seconds=180, movie_id=3391,
            expected_title='Saving Private Ryan', seek_seconds=1200, subtitles_off=True,
            config_dir=root, preservation_report=[path], binary_sha256='0'*64)
        base = Path(__file__).parent
        for name in ('baseline', option.replace('_', '-')):
            target = root/f'native-optimization-{name}.conf'
            target.write_text((base/target.name).read_text())
        return args

    def test_only_chosen_option_differs_and_both_planar(self):
        for option in module.OPTIONS:
            with tempfile.TemporaryDirectory() as directory, patch.object(module, 'validate_request'):
                args = self.args(Path(directory), option)
                self.assertTrue(module.validate_args(args)[0]['native_packed_planar_both'])

    def test_scene_duration_subtitle_and_capture_changes_refused(self):
        for key, value in (('seconds', 120), ('movie_id', 3955), ('seek_seconds', 1199),
                           ('subtitles_off', False), ('expected_title', '1917')):
            with tempfile.TemporaryDirectory() as directory, patch.object(module, 'validate_request'):
                args = self.args(Path(directory))
                setattr(args, key, value)
                with self.assertRaises(ValueError):
                    module.validate_args(args)
        for old, new in (('IMMUTABLE_INSTRUCTIONS=0', 'IMMUTABLE_INSTRUCTIONS=1'),
                         ('PLANAR_OUTPUT=1', 'PLANAR_OUTPUT=0'),
                         ('CAPTURE_OUTPUTS=0', 'CAPTURE_OUTPUTS=1'),
                         ('BATCHED_PLANES=1', 'BATCHED_PLANES=0')):
            with tempfile.TemporaryDirectory() as directory, patch.object(module, 'validate_request'):
                args = self.args(Path(directory))
                target = module.config_paths(args)[1]
                target.write_text(target.read_text().replace(old, new))
                with self.assertRaises(ValueError):
                    module.validate_args(args)

    def test_actual_use_and_original_subtitle_fixture_required(self):
        report, stopped = planar_report(1)
        original = dict(enabled=True, index=0)
        disabled = dict(enabled=False, index=0)
        report['subtitle_fixture'] = dict(movie_id=3391, player_id=1, requested_enabled=False,
            before=original.copy(), disabled=disabled.copy(), disabled_at_end=disabled.copy(),
            restored=original.copy())
        actual = unittest.mock.Mock(return_value={'actual_use_verified': True})
        validator = module.make_validator('batched_planes', actual)
        result = validator(report, stopped, 1, '0'*64)
        self.assertTrue(result['native_optimization']['actual_use_verified'])
        actual.assert_called_once_with(report['selected_log_lines'], 'batched_planes', 1)
        report['subtitle_fixture']['before']['enabled'] = False
        report['subtitle_fixture']['restored']['enabled'] = False
        with self.assertRaises(ValueError):
            validator(report, stopped, 0, '0'*64)


if __name__ == '__main__':
    unittest.main()
