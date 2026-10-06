from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import run_petunia_bl_picture_v2 as c

class TargetBL(unittest.TestCase):
    def test_every_required_import_is_actually_loaded_from_pinned_path(self):
        import sys
        root=Path(c.__file__).resolve().parent
        actual={p.name for m in sys.modules.values() if getattr(m,'__file__',None)
                and (p:=Path(m.__file__).resolve()).parent==root}
        self.assertEqual(c.PIN_NAMES & actual,c.PIN_NAMES)
        self.assertNotIn('observe_subtitle_fixture.py',c.PIN_NAMES)
        values=[str(root/n)+'='+'a'*64 for n in c.PIN_NAMES]
        with patch.object(c,'code_fingerprint',return_value=(None,'a'*64)):
            self.assertEqual(set(c.verify_source_pins(values)),c.PIN_NAMES)

    def test_command_limits(self):
        args=SimpleNamespace(**{n:Path('/private/'+n) for n in ('observer','binary','loader','runtime','driver','runtime_identity','private_prefix','vpl_runtime','barrier','launch_ready','launch_ack')},unit='yblod-bl-picture-v2-test',binary_sha256=c.PROBE_SHA,driver_sha256='a'*64,launch_nonce='a'*64)
        argv=c.command(args,Path('/private/input'))
        for item in ('MemoryMax=1610612736','MemorySwapMax=0','CPUQuota=100%','PrivateNetwork=yes','RuntimeMaxSec=180','KillMode=control-group'):
            self.assertIn(item,argv)
        self.assertEqual(argv.count('--pts-us'),3)
        self.assertEqual(argv[-2:],[ '--extra-library-dir','/private/vpl_runtime'])
        self.assertNotIn('kodi',argv)

    def test_exact_count_after_unchanged_validator(self):
        with patch.object(c,'validate_raw') as check:
            self.assertTrue(c.literal_raw_pass({'controlled_packet_window':{'event_count':725}}))
            check.assert_called_once()
            with self.assertRaises(ValueError):c.literal_raw_pass({'controlled_packet_window':{'event_count':724}})

    def test_validator_failure_not_waived(self):
        with patch.object(c,'validate_raw',side_effect=ValueError):
            with self.assertRaises(ValueError):c.literal_raw_pass({})

    def test_memory_reserves(self):
        with patch.object(Path,'read_text',return_value='MemAvailable: 2359296 kB\n'):
            self.assertEqual(c.host_reserves(True),2415919104)
        with patch.object(Path,'read_text',return_value='MemAvailable: 2359295 kB\n'):
            with self.assertRaises(ValueError):c.host_reserves(True)
        with patch.object(Path,'read_text',return_value='MemAvailable: 786431 kB\n'):
            with self.assertRaises(ValueError):c.host_reserves(False)

    def test_unknown_owner_never_stopped(self):
        args=SimpleNamespace(unit='yblod-bl-picture-v2-test',expected_observer_argv=[])
        with patch.object(c,'unit_state',return_value={'ActiveState':'active','MainPID':'123'}),patch.object(c,'own_live_unit',side_effect=ValueError),patch.object(c.subprocess,'run') as stop:
            with self.assertRaises(ValueError):c.cleanup_unit(args,None,None)
            stop.assert_not_called()

    def test_matching_argv_without_launch_generation_never_adopted(self):
        args=SimpleNamespace(unit='yblod-bl-picture-v2-test',expected_observer_argv=['same'])
        with patch.object(c,'unit_state',return_value={'ActiveState':'active','MainPID':'123','InvocationID':'same'}),patch.object(c,'own_live_unit') as own,patch.object(c.subprocess,'run') as stop:
            with self.assertRaises(ValueError):c.cleanup_unit(args,None,None)
            own.assert_not_called();stop.assert_not_called()

    def test_owned_exited_unit_needs_no_live_cgroup(self):
        args=SimpleNamespace(unit='yblod-bl-picture-v2-test',expected_observer_argv=[])
        states=[{'ActiveState':'active','SubState':'exited','MainPID':'0','InvocationID':'owned','ControlGroup':''},
                {'ActiveState':'inactive','MainPID':'0'}]
        with patch.object(c,'unit_state',side_effect=states),patch.object(c,'own_live_unit') as live,patch.object(c.subprocess,'run') as stop:
            self.assertTrue(c.cleanup_unit(args,'owned',(123,1)))
            live.assert_not_called();stop.assert_called_once()

    def test_exited_wrong_invocation_or_unknown_generation_never_stopped(self):
        args=SimpleNamespace(unit='yblod-bl-picture-v2-test',expected_observer_argv=[])
        state={'ActiveState':'active','SubState':'exited','MainPID':'0','InvocationID':'other','ControlGroup':''}
        with patch.object(c,'unit_state',return_value=state),patch.object(c.subprocess,'run') as stop:
            with self.assertRaises(ValueError):c.cleanup_unit(args,'owned',(123,1))
            with self.assertRaises(ValueError):c.cleanup_unit(args,'other',None)
            stop.assert_not_called()

    def test_terminal_generation_guard(self):
        args=SimpleNamespace(unit='yblod-bl-picture-v2-test',expected_observer_argv=[])
        with patch.object(c,'unit_state',return_value={'ActiveState':'failed','MainPID':'0','InvocationID':'owned'}):
            self.assertTrue(c.cleanup_unit(args,'owned',None))
            with self.assertRaises(ValueError):c.cleanup_unit(args,'other',None)

    def test_process_generation_guard(self):
        state={'InvocationID':'owned','ControlGroup':'/owned','MainPID':'123'}
        with patch.object(c,'process_record',return_value={'argv':['observer'],'start_ticks':2}):
            with self.assertRaises(ValueError):c.own_live_unit(state,['observer'],'owned',(123,1))

if __name__=='__main__':unittest.main()
