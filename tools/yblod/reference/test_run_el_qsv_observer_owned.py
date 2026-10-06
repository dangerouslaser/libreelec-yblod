from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch
import run_el_qsv_observer_owned as module


class Tests(unittest.TestCase):
    def run_case(self,child,path):
        return module.run_observer(['python3','observer.py','--output-dir',str(path),'--label','case'],
            stdout=None,stderr=None,check=True,timeout=1,manifest=Path('/manifest'),movie_id=3391)

    def test_success_no_termination(self):
        child=Mock();child.wait.return_value=0;child.poll.return_value=0
        with tempfile.TemporaryDirectory() as directory,patch.object(module.subprocess,'Popen',return_value=child):
            self.run_case(child,Path(directory))
        child.terminate.assert_not_called();child.kill.assert_not_called()

    def test_timeout_gracefully_terminates_then_waits(self):
        child=Mock();child.wait.side_effect=[subprocess.TimeoutExpired('owned',1),0];child.poll.return_value=None
        with tempfile.TemporaryDirectory() as directory,patch.object(module.subprocess,'Popen',return_value=child):
            with self.assertRaises(subprocess.TimeoutExpired):self.run_case(child,Path(directory))
        child.terminate.assert_called_once();child.kill.assert_not_called()

    def test_parent_interruption_terminates_then_recovers(self):
        child=Mock();child.wait.side_effect=[RuntimeError('interrupted'),0];child.poll.return_value=None
        with tempfile.TemporaryDirectory() as directory,patch.object(module.subprocess,'Popen',return_value=child),patch.object(module,'recover') as recover:
            (Path(directory)/'case.subtitle-recovery-private.json').write_text('{}')
            with self.assertRaises(RuntimeError):self.run_case(child,Path(directory))
            recover.assert_called_once()
        child.terminate.assert_called_once()

    def test_hung_owned_child_killed_reaped_before_recovery(self):
        child=Mock();child.wait.side_effect=[subprocess.TimeoutExpired('owned',1),subprocess.TimeoutExpired('owned',20),0];child.poll.return_value=None
        with tempfile.TemporaryDirectory() as directory,patch.object(module.subprocess,'Popen',return_value=child):
            with self.assertRaises(subprocess.TimeoutExpired):self.run_case(child,Path(directory))
        child.kill.assert_called_once();self.assertEqual(child.wait.call_count,3)

if __name__=='__main__':unittest.main()
