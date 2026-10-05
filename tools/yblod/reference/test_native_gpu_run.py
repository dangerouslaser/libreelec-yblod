import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import native_gpu_run as runner
from native_gpu_vectors import expected_stages, vector_fixtures, width_oracle


def cpu_report(vector):
    width=width_oracle(vector.mapping)
    polynomial=all(s.method=="polynomial" for c in vector.mapping.mappings for s in c.segments)
    accepted=polynomial and width["supported"]
    return dict(schema="yblod.native-gpu-probe.v1",accepted=accepted,polynomial_only=polynomial,
        samples=len(vector.triplets),component=vector.component,gpu_attempted=False,
        status="validated" if accepted else "unsupported",cpu_stages=[list(r) for r in zip(*expected_stages(vector))],
        width_report=dict(supported=width["supported"],mmr_segment_count=width["mmr_segment_count"],
        worst_l1_bound=width["worst_l1_bound"],first_unsupported_component=width["first_unsupported"][0],
        first_unsupported_segment=width["first_unsupported"][1]))


def gpu_report(vector):
    report=cpu_report(vector)
    report.pop("cpu_stages")
    report.update(status="exact",gpu_attempted=True,device_binding_verified=True,cleanup_succeeded=True,
        observed_gl_error=0,observed_egl_error=12288,stage_mismatch_counts=[0]*4,fence_wait_result=37148)
    return report


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.binary=self.root/"probe";self.binary.write_bytes(b"synthetic mock binary");self.binary.chmod(0o700)
        self.shader=Path(runner.__file__).with_name("native_gpu_probe.comp")
        self.vectors=vector_fixtures();self.by_name={v.name:v for v in self.vectors}

    def invoke(self,argv,**kwargs):
        vector=self.by_name[Path(argv[-1]).stem]
        result=cpu_report(vector) if argv[1]=="--validate" else gpu_report(vector)
        code=0 if result["accepted"] else 3
        return subprocess.CompletedProcess(argv,code,json.dumps(result).encode(),b"")

    def test_complete_all_cpu_gates_precede_gpu_and_unsupported_not_dispatched(self):
        with patch.object(runner.subprocess,"run",side_effect=self.invoke) as call:
            report=runner.run(self.binary,self.shader,self.root/"run")
        self.assertEqual(report["status"],"complete")
        self.assertEqual((report["fixture_count"],report["gpu_case_count"],report["unsupported_case_count"]),(27,21,6))
        args=[c.args[0] for c in call.call_args_list]
        self.assertTrue(all(a[1]=="--validate" for a in args[:27]))
        self.assertTrue(all(a[1]=="/dev/dri/renderD128" for a in args[27:]))
        self.assertEqual(len(args),48)

    def test_cpu_failure_blocks_all_gpu_and_records_logs(self):
        def wrong(argv,**kwargs):
            result=cpu_report(self.by_name[Path(argv[-1]).stem]);result["cpu_stages"][0][0]+=1
            return subprocess.CompletedProcess(argv,0,json.dumps(result).encode(),b"diagnostic")
        with patch.object(runner.subprocess,"run",side_effect=wrong) as call:
            report=runner.run(self.binary,self.shader,self.root/"run")
        self.assertEqual(report["status"],"failed");self.assertEqual(call.call_count,1)
        self.assertNotIn("all_cpu_gates_complete",report)
        self.assertEqual((self.root/"run"/(self.vectors[0].name+"-validation.stderr.log")).read_bytes(),b"diagnostic")

    def test_gpu_error_stops_next_case_and_never_silently_falls_back(self):
        def wrong(argv,**kwargs):
            if argv[1]=="--validate":return self.invoke(argv,**kwargs)
            result=gpu_report(self.by_name[Path(argv[-1]).stem]);result["stage_mismatch_counts"][1]=1
            return subprocess.CompletedProcess(argv,0,json.dumps(result).encode(),b"")
        with patch.object(runner.subprocess,"run",side_effect=wrong) as call:
            report=runner.run(self.binary,self.shader,self.root/"run")
        self.assertEqual(report["status"],"failed");self.assertEqual(call.call_count,28)

    def test_mutation_timeout_and_ambiguous_json_fail_closed(self):
        def mutate(argv,**kwargs):
            result=self.invoke(argv,**kwargs);Path(argv[-1]).write_bytes(b"changed");return result
        for name,callback in (("mutation",mutate),
            ("timeout",subprocess.TimeoutExpired("probe",30,output=b"partial",stderr=b"timeout")),
            ("duplicate",lambda argv,**kw:subprocess.CompletedProcess(argv,0,b'{"status":"x","status":"y"}',b""))):
            with self.subTest(name=name),patch.object(runner.subprocess,"run",side_effect=callback) as call:
                report=runner.run(self.binary,self.shader,self.root/name)
            self.assertEqual(report["status"],"failed");self.assertEqual(call.call_count,1)
            self.assertTrue((self.root/name/"gpu-run-report.json").exists())

    def test_existing_destination_and_unreviewed_shader_rejected_without_execution(self):
        with patch.object(runner.subprocess,"run") as call:
            with self.assertRaises(FileExistsError):runner.run(self.binary,self.shader,self.root)
            shader=self.root/"other.comp";shader.write_text("unreviewed")
            with self.assertRaises(ValueError):runner.run(self.binary,shader,self.root/"new")
            for node in ("/dev/dri/card0","/dev/dri/renderD127","/dev/dri/renderD128/extra"):
                with self.assertRaises(ValueError):runner.run(self.binary,self.shader,self.root/"new",node)
        call.assert_not_called()

    def test_report_field_failures(self):
        vector=self.vectors[0]
        for key,value in (("cleanup_succeeded",False),("device_binding_verified",False),
                          ("gpu_attempted",False),("observed_gl_error",1),("observed_egl_error",0),
                          ("status","failed"),("stage_mismatch_counts",[False]*4),
                          ("observed_gl_error",0.0),("component",False),("fence_wait_result",37147)):
            report=gpu_report(vector);report[key]=value
            with self.assertRaises(ValueError):runner.validate_gpu(report,vector)
        report=cpu_report(vector);report["width_report"]["worst_l1_bound"]=1
        with self.assertRaises(ValueError):runner.validate_cpu(report,vector)
        report=cpu_report(vector);report["cpu_stages"][0][0]=False
        with self.assertRaises(ValueError):runner.validate_cpu(report,vector)


if __name__=="__main__":unittest.main()
