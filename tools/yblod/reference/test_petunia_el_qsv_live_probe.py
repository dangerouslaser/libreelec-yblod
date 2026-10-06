import copy
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch
from run_petunia_el_qsv_live_probe import command, literal_raw_pass, cleanup_unit, own_live_unit


def raw_fixture():
    frames = []
    for pts in (1210000000, 1220010000, 1230020000):
        frame = dict(requested_pts_microseconds=pts, format='P010', code_bit_depth=10,
                     active_width=1920, active_height=1080,
                     before={'pts_microseconds':pts}, after={'pts_microseconds':pts})
        frame.update({key:True for key in ('properties_equal','active_geometry_equal',
                     'chroma_location_equal','colour_properties_equal','original_timestamps_equal')})
        frame['planes'] = [dict(plane=name,sample_count=count,differing_samples=0,
                               maximum_absolute_sample_codes=0,p010_low_bits_zero=True)
                           for name,count in zip(('Y','U','V'),(2073600,518400,518400))]
        frames.append(frame)
    return dict(pass_=True, **{'pass':True,'qsv_mapped_frames':3,'frames':frames})


class TargetProbeTests(unittest.TestCase):
    def test_exact_raw(self):
        self.assertTrue(literal_raw_pass(raw_fixture()))

    def test_no_tolerance_or_boolean_integer(self):
        for key,value in (('differing_samples',1),('maximum_absolute_sample_codes',1),
                          ('differing_samples',False),('sample_count',True),('p010_low_bits_zero',1)):
            raw=raw_fixture();raw['frames'][0]['planes'][0][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):literal_raw_pass(raw)

    def test_timestamp_and_properties(self):
        for mutate in (lambda r:r['frames'][0].update(requested_pts_microseconds=1210000001),
                       lambda r:r['frames'][0]['after'].update(pts_microseconds=1210000001),
                       lambda r:r['frames'][0].update(properties_equal=1),
                       lambda r:r.update(qsv_mapped_frames=True)):
            raw=raw_fixture();mutate(raw)
            with self.assertRaises(ValueError):literal_raw_pass(raw)

    def test_controller_boundaries(self):
        names=('observer','binary','loader','runtime','driver','runtime_identity','private_prefix')
        args=SimpleNamespace(**{name:Path('/private/'+name) for name in names},
            unit='yblod-qsv-target-live-test',binary_sha256='a'*64,driver_sha256='b'*64)
        argv=command(args,Path('/private/input'))
        for value in ('MemoryMax=536870912','MemorySwapMax=0','CPUQuota=100%',
                      'PrivateNetwork=yes','RuntimeMaxSec=180','KillMode=control-group'):
            self.assertIn(value,argv)
        self.assertNotIn('kodi',argv)
        self.assertEqual(argv.count('--pts-us'),3)

    def test_terminal_failed_launcher_still_checked(self):
        args=SimpleNamespace(unit='yblod-qsv-target-live-test',expected_observer_argv=['python','/observer.py'])
        with patch('run_petunia_el_qsv_live_probe.unit_state',return_value=dict(ActiveState='failed',MainPID='0',InvocationID='owned')):
            self.assertTrue(cleanup_unit(args,'owned',None))
            with self.assertRaises(ValueError):cleanup_unit(args,'other',None)

    def test_start_uncertainty_owned_cleanup(self):
        args=SimpleNamespace(unit='yblod-qsv-target-live-test',expected_observer_argv=['python','/observer.py'])
        states=[dict(ActiveState='active',MainPID='12',InvocationID='owned',ControlGroup='/owned'),
                dict(ActiveState='inactive',MainPID='0',InvocationID='owned')]
        with patch('run_petunia_el_qsv_live_probe.unit_state',side_effect=states),patch('run_petunia_el_qsv_live_probe.own_live_unit',return_value=('owned',(12,1))) as ownership,patch('run_petunia_el_qsv_live_probe.subprocess.run') as stop:
            self.assertTrue(cleanup_unit(args,None,None))
            ownership.assert_called_once();stop.assert_called_once()

    def test_unknown_owner_never_stopped(self):
        args=SimpleNamespace(unit='yblod-qsv-target-live-test',expected_observer_argv=['python','/observer.py'])
        with (patch('run_petunia_el_qsv_live_probe.unit_state',return_value=dict(ActiveState='active',MainPID='12')),
             patch('run_petunia_el_qsv_live_probe.own_live_unit',side_effect=ValueError),patch('run_petunia_el_qsv_live_probe.subprocess.run') as stop):
            with self.assertRaises(ValueError):cleanup_unit(args,None,None)
            stop.assert_not_called()

    def test_generation_mismatch(self):
        state=dict(InvocationID='owned',ControlGroup='/owned',MainPID='12')
        with patch('run_petunia_el_qsv_live_probe.process_record',return_value=dict(argv=['python','/observer.py'],start_ticks=2)),patch.object(Path,'resolve',lambda p,strict=True:p):
            with self.assertRaises(ValueError):own_live_unit(state,['python','/observer.py'],'owned',(12,1))

    def test_wrong_arguments_rejected(self):
        state=dict(InvocationID='owned',ControlGroup='/owned',MainPID='12')
        with patch('run_petunia_el_qsv_live_probe.process_record',return_value=dict(argv=['python','/observer.py','--wrong'],start_ticks=1)):
            with self.assertRaises(ValueError):own_live_unit(state,['python','/observer.py','--expected'],'owned',(12,1))

    def test_dead_unit_no_restart(self):
        args=SimpleNamespace(unit='yblod-qsv-target-live-test',expected_observer_argv=[])
        with (patch('run_petunia_el_qsv_live_probe.unit_state',return_value=dict(ActiveState='inactive',MainPID='0',InvocationID='')),
             patch('run_petunia_el_qsv_live_probe.subprocess.run') as call):
            self.assertTrue(cleanup_unit(args,None,None))
            call.assert_not_called()


if __name__=='__main__':unittest.main()
