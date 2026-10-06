import copy
import unittest
from observe_el_qsv_active_movie import verify_measured_generation


def fixture():
    return dict(active_el_runtime=dict(active_before_measurement=True,identity=dict(binary_sha256='1'*64,pid=77,start_ticks=99,service_pid=66)),
        gpu_samples=[dict(pid=77,process_start_ticks=99)]*2,kodi_before='MainPID=66\nActiveEnterTimestampMonotonic=1',kodi_after='MainPID=66\nActiveEnterTimestampMonotonic=1')


class Tests(unittest.TestCase):
    def test_matching_active_and_measured_generation(self):verify_measured_generation(fixture(),'1'*64)
    def test_changed_gpu_pid_or_generation(self):
        for field,value in [('pid',78),('process_start_ticks',100),('pid',True)]:
            record=fixture();record['gpu_samples']=copy.deepcopy(record['gpu_samples']);record['gpu_samples'][1][field]=value
            with self.assertRaises(ValueError):verify_measured_generation(record,'1'*64)
    def test_service_pid_changed(self):
        record=fixture();record['kodi_after']='MainPID=67'
        with self.assertRaises(ValueError):verify_measured_generation(record,'1'*64)
    def test_snapshot_binary_changed_or_not_active(self):
        for field,value in [('active_before_measurement',False)]:
            record=fixture();record['active_el_runtime'][field]=value
            with self.assertRaises(ValueError):verify_measured_generation(record,'1'*64)
        with self.assertRaises(ValueError):verify_measured_generation(fixture(),'2'*64)

if __name__=='__main__':unittest.main()
