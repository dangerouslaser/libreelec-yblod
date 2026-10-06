import unittest
from unittest.mock import patch
import collect_el_qsv_target_manifest as producer


class Manifest(unittest.TestCase):
    def test_idle_guard_runs_before_any_observation(self):
        def fail(): raise ValueError('active')
        with patch.object(producer, 'observe_target') as observe:
            with self.assertRaises(ValueError): producer.collect([], 'driver', 'sha', 'node', fail)
            observe.assert_not_called()

    def test_target_is_actually_observed_and_unsafe_sonames_rejected(self):
        observed = dict(host='private-fixture-host', gpu={'device':'private-fixture-device'})
        with patch.object(producer, 'observe_target', return_value=observed) as observe:
            with self.assertRaises(ValueError):
                producer.collect(['/tmp/not-a-soname'], 'driver', 'sha', 'node', lambda:None)
            observe.assert_called_once_with('node')


if __name__ == '__main__': unittest.main()
