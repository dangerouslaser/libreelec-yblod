import unittest
from summarize_el_qsv_canonical_playback import gpu_schema,case_admission


class SummaryContracts(unittest.TestCase):
    def report(self):
        return {'gpu_intervals':[{'elapsed_seconds':2.,'engine_busy_percent':{'render':30.,'video':5.},'capacity':{'render':1,'video':2}} for _ in range(2)]}
    def test_valid(self):
        self.assertEqual(gpu_schema(self.report()),{'render':1,'video':2})
    def test_missing_engine(self):
        raw=self.report();del raw['gpu_intervals'][1]['engine_busy_percent']['video']
        with self.assertRaises(ValueError):gpu_schema(raw)
    def test_capacity_changed(self):
        raw=self.report();raw['gpu_intervals'][1]['capacity']['video']=1
        with self.assertRaises(ValueError):gpu_schema(raw)
        with self.assertRaises(ValueError):gpu_schema(self.report(),{'render':1,'video':1})
    def test_nonfinite(self):
        for key,value in [('elapsed_seconds',float('nan')),('elapsed_seconds',0)]:
            raw=self.report();raw['gpu_intervals'][0][key]=value
            with self.assertRaises(ValueError):gpu_schema(raw)
        raw=self.report();raw['gpu_intervals'][0]['engine_busy_percent']['render']=float('nan')
        with self.assertRaises(ValueError):gpu_schema(raw)
        raw=self.report();raw['gpu_intervals'][0]['capacity']['render']=True
        with self.assertRaises(ValueError):gpu_schema(raw)
    def test_wrong_case_and_runtime_marker(self):
        case_admission({'label':'case-flag0'},{'actual_isolated_runtime_verified':True},'case-flag0')
        with self.assertRaises(ValueError):case_admission({'label':'case-flag1'},{'actual_isolated_runtime_verified':True},'case-flag0')
        for value in (False,1,None):
            with self.assertRaises(ValueError):case_admission({'label':'case-flag0'},{'actual_isolated_runtime_verified':value},'case-flag0')


if __name__=='__main__':unittest.main()
