import unittest

from native_optimization_telemetry import qualify_actual_use


def lines(option, enabled):
    batch = enabled if option == 'batched_planes' else 0
    immutable = enabled if option == 'immutable_instructions' else 0
    return [f'DVBridge native composer: optimization_stats_valid=1 batched_planes_selected={batch} '
            f'immutable_instructions_selected={immutable} accepted_fp32={n} '
            f'batched_plane_imports={n*batch} batched_plane_releases={n*batch} '
            f'immutable_accepted_frames={n} immutable_metadata_uploads={n*(1 if immutable else 3)} '
            f'immutable_range_bindings={n*3*immutable} immutable_dispatches={n*3}'
            for n in (120, 480)]


class Tests(unittest.TestCase):
    def test_each_option_on_off_actual_success_counts(self):
        for option in ('batched_planes', 'immutable_instructions'):
            for enabled in (0, 1):
                result = qualify_actual_use(lines(option, enabled), option, enabled)
                self.assertTrue(result['actual_use_verified'])
                self.assertEqual(result['successful_operation_deltas']['accepted_fp32'], 360)

    def test_missing_invalid_selected_and_regressed_counts_rejected(self):
        original = lines('batched_planes', 1)
        edits = (
            lambda x: x.replace('optimization_stats_valid=1', 'optimization_stats_valid=0'),
            lambda x: x.replace('immutable_instructions_selected=0', 'immutable_instructions_selected=1'),
            lambda x: x.replace('batched_planes_selected=1', 'batched_planes_selected=0'),
            lambda x: x.replace(' batched_plane_imports=480', ''),
            lambda x: x.replace('batched_plane_imports=480', 'batched_plane_imports=479'),
            lambda x: x.replace('batched_plane_releases=480', 'batched_plane_releases=119'),
            lambda x: x.replace('immutable_accepted_frames=480', 'immutable_accepted_frames=479'),
            lambda x: x.replace('immutable_metadata_uploads=1440', 'immutable_metadata_uploads=1439'),
            lambda x: x.replace('immutable_range_bindings=0', 'immutable_range_bindings=1'),
            lambda x: x.replace('immutable_dispatches=1440', 'immutable_dispatches=1439'),
        )
        for edit in edits:
            with self.assertRaises(ValueError):
                qualify_actual_use([original[0], edit(original[1])], 'batched_planes', 1)

    def test_single_row_and_disabled_but_used_rejected(self):
        with self.assertRaises(ValueError):
            qualify_actual_use(lines('immutable_instructions', 1)[:1], 'immutable_instructions', 1)
        rows = [row.replace('batched_plane_imports=0', 'batched_plane_imports=1')
                for row in lines('batched_planes', 0)]
        with self.assertRaises(ValueError):
            qualify_actual_use(rows, 'batched_planes', 0)


if __name__ == '__main__':
    unittest.main()
