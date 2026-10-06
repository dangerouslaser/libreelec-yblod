import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_native_packed_long_matrix as module
from run_native_packed_matrix import validate_packed_report
from test_native_packed_matrix import frame_qualification


class Tests(unittest.TestCase):
    def make_args(self, directory, movie=3391):
        root = Path(directory) / 'output'
        root.mkdir()
        proof = Path(directory) / 'preserved.json'
        proof.write_text(json.dumps(frame_qualification()))
        argv = ['--binary-sha256', '0'*64, '--root', str(root),
                '--observer', str(Path(__file__).with_name('observe_native_movie.py')),
                '--movie-id', str(movie), '--expected-title', {51: '1917', 3391: 'Saving Private Ryan'}[movie],
                '--preservation-report', str(proof)]
        return module.argument_parser().parse_args(argv), argv

    def test_defaults_both_titles_and_original_request_unchanged(self):
        for movie in (51, 3391):
            with tempfile.TemporaryDirectory() as directory:
                args, _ = self.make_args(directory, movie)
                before = vars(args).copy()
                self.assertEqual((args.seconds, args.seek_seconds), (600, 1200))
                self.assertTrue(module.validate_long_args(args)[0]['all_tunnel_rgb_bytes_identical'])
                self.assertEqual(vars(args), before)
                for seconds in (300, 900):
                    changed = copy.copy(args)
                    changed.seconds = seconds
                    module.validate_long_args(changed)

    def test_invalid_bounds_title_identity_and_missing_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _ = self.make_args(directory)
            for key, value in (('seconds', 299), ('seconds', 901), ('movie_id', 999),
                               ('movie_id', 51), ('expected_title', '1917'), ('seek_seconds', -1),
                               ('preservation_report', []), ('binary_sha256', 'bad')):
                changed = copy.copy(args)
                setattr(changed, key, value)
                with self.assertRaises(ValueError):
                    module.validate_long_args(changed)

    def test_changed_output_qualification_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _ = self.make_args(directory)
            proof = frame_qualification()
            proof['planes']['I']['max_absolute_codes'] = 1
            args.preservation_report[0].write_text(json.dumps(proof))
            with self.assertRaises(ValueError):
                module.validate_long_args(args)

    def test_long_wrapper_delegates_unchanged_args_and_existing_validator(self):
        with tempfile.TemporaryDirectory() as directory:
            args, argv = self.make_args(directory, 51)
            with patch('sys.argv', ['run_native_packed_long_matrix.py', *argv]), \
                 patch.object(module, 'run_configured_matrix') as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                module.main()
            actual, configs, label, describe, validator = run.call_args.args
            self.assertEqual(actual.seconds, 600)
            self.assertEqual((actual.movie_id, actual.expected_title), (51, '1917'))
            self.assertEqual(configs, [args.config_dir / f'native-packed-{flag}.conf' for flag in (0, 1)])
            self.assertEqual(label, 'native-packed-long-movie51')
            self.assertIs(validator, validate_packed_report)
            self.assertEqual(describe(1), 'native-fp32-lut release-rgb packed_output=1')


if __name__ == '__main__':
    unittest.main()
