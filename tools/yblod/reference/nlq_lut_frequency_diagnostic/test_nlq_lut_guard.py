import copy
import unittest
from unittest.mock import patch
from run_nlq_lut_guard import validate_result, check_kodi_state, player_state

def fixture(lut, sequence):
    counts = [8294400, 2073600, 2073600]; n = 3 if sequence else 1
    r = {"schema": "yblod.native-gpu-composer-compare-probe.v1", "status": "complete",
         "observed_gl_error": 0, "observed_egl_error": 12288,
         "backend_route": "actual-playback-fp32-wrapper", "counts": counts, "output_depth": 12,
         "nlq_lut_metadata_sequence": sequence, "nlq_lut_gpu_full_frame_oracles": n,
         "gpu_verified_output_planes": 3*n, "gpu_verified_reconstructed_values": sum(counts)*n,
         "gpu_oracle_dispatches": 191*n, "cpu_chunk_samples": 65536, "nlq_lut_restored_a_bit_exact": sequence,
         "nlq_lut_restored_a_values": sum(counts) if sequence else 0,
         "raw_dump_scope": "original-A-only", "warmups": 8, "samples": 12,
         "route_stats": {"accepted_fp32": 21, "accepted_integer": 0, "cache_misses": 1,
                         "cache_hits": 20, "shader_compile_failed": 0, "generate_failed": 0},
         "nlq_lut_requested": bool(lut), "nlq_lut_compiled_shaders": int(bool(lut)),
         "nlq_lut_builds": n if lut else 0, "nlq_lut_uploads": n if lut else 0,
         "nlq_lut_cache_hits": 21-n if lut else 0, "nlq_lut_bytes_per_table": 12288,
         "nlq_lut_entries_per_table": 3072,
         "difference_metrics": [{"plane": c, "count": count*n, "over_one": 0, "max_abs": 1} for c,count in enumerate(counts)],
         "wall_ns": [1]*12, "cpu_ns": [1]*12, "dispatch_timing_is_device_kernel_time": False,
         "raw_dump_requested": True, "raw_dump_format": "u16le-native-grid-Y-then-Cb-then-Cr-no-padding"}
    for key in ("gpu_attempted", "cpu_full_frame_gate", "device_binding_verified", "cleanup_succeeded",
                "fp32_selected", "all_output_codes_compared", "whole_frame_resident"):
        r[key] = True
    return r

class GuardTests(unittest.TestCase):
    def test_valid_modes(self):
        for lut in (0,1):
            for sequence in (False,True): validate_result(fixture(lut,sequence),lut,sequence)
    def test_reject_diagnostic_lies(self):
        for key,value in (("gpu_oracle_dispatches",576), ("nlq_lut_restored_a_bit_exact",False),
                          ("nlq_lut_uploads",1), ("nlq_lut_cache_hits",20),
                          ("nlq_lut_requested",False), ("cleanup_succeeded",False),
                          ("dispatch_timing_is_device_kernel_time",True)):
            record=copy.deepcopy(fixture(1,True)); record[key]=value
            with self.assertRaises(ValueError): validate_result(record,1,True)
    def test_reject_fallback(self):
        record=fixture(1,True); record["route_stats"]["accepted_integer"]=1
        with self.assertRaises(ValueError): validate_result(record,1,True)
    def test_extended_iterations(self):
        for lut in (0,1):
            for sequence in (False,True):
                r=fixture(lut,sequence); n=3 if sequence else 1
                r.update(warmups=32,samples=32,wall_ns=[1]*32,cpu_ns=[1]*32)
                r["route_stats"].update(accepted_fp32=65,cache_hits=64)
                r["nlq_lut_cache_hits"]=65-n if lut else 0
                validate_result(r,lut,sequence,32,32)
                with self.assertRaises(ValueError): validate_result(r,lut,sequence,32,64)
    def test_frequency(self):
        r=fixture(1,False); r.update(gpu_frequency_requested=True,gpu_frequency_device_verified=True,
            gpu_frequency_samples=[dict(before_act_mhz=-1,before_cur_mhz=300,after_act_mhz=800,after_cur_mhz=800) for _ in range(12)])
        validate_result(r,1,False,frequency=True)
        r["gpu_frequency_device_verified"]=False
        with self.assertRaises(ValueError): validate_result(r,1,False,frequency=True)
    def test_inactive_kodi(self):
        check_kodi_state("inactive",0,[],"inactive")
        check_kodi_state("active",5,[{}],"active")
        for service,pid,processes,mode in (("active",5,[{}],"inactive"),
            ("inactive",0,[],"active"),("inactive",5,[],"inactive"),
            ("inactive",0,[{}],"inactive"),("failed",0,[],"inactive")):
            with self.assertRaises(ValueError): check_kodi_state(service,pid,processes,mode)
        with patch("run_nlq_lut_guard.idle_players",side_effect=AssertionError("unexpected RPC")):
            self.assertEqual(player_state("inactive")["queried"],False)

if __name__ == "__main__": unittest.main()
