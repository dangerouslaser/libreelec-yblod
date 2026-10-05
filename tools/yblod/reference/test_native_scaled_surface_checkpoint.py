"""Strict report replay and synthetic privacy/failure checks, not GPU runs."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import native_scaled_surface_checkpoint as checkpoint


class CheckpointTests(unittest.TestCase):
    def report(self):
        return json.loads((Path(__file__).resolve().parent /
            "results/native-scaled-surface-frame-2296-20261005a.json").read_bytes())

    def test_actual_report_replay_and_source_pins(self):
        report=self.report()
        self.assertEqual(checkpoint.replay_json(json.dumps(report).encode()), report)
        root=Path(__file__).resolve().parent
        for group in ("engine_sources", "consumer_source"):
            for name, expected in report["pins"][group].items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), expected, name)
        for key,name in {'packer_source':'native_p010_fixture.c',
                         'probe_source':'vaapi_scaler_probe.c',
                         'probe_accounting_header':'drm_engine_accounting.h',
                         'wrapper_source':'run_native_p010_private.sh'}.items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),
                             report['pins']['scaler_artifacts'][key], name)
        self.assertFalse(report["hardware"]["driver_binary_prepost_verified"])
        self.assertFalse(report["consumer"]["old_linear_baseline_compared"])

    def test_false_or_expanded_claims_rejected(self):
        for path,value in [(('consumer','raw_words_byte_exact'),12441599),
            (('consumer','independent_arithmetic_reference'),True),
            (('hardware','driver_binary_prepost_verified'),True),
            (('association','verified_by_consumer_runner'),True),
            (('resources','observed_swap_bytes'),1),
            (('resources','peak_snapshot_bytes'),True),
            (('resources','scaler_peak_snapshot_bytes'),[245694464,245694464]),
            (('submitted_request','pipeline_flags'),2),
            (('limitations','playback_benchmark'),True),
            (('consumer','complete_component_counts'),[8294400,2073600,2073599])]:
            report=self.report()
            report[path[0]][path[1]]=value
            with self.subTest(path=path), self.assertRaises(ValueError):
                checkpoint.replay(report)
        report=self.report(); report['private_pixels']='secret'
        with self.assertRaises(ValueError): checkpoint.replay(report)
        report=self.report(); report['pins']['engine_sources']['private_rpu']='a'*64
        with self.assertRaises(ValueError): checkpoint.replay(report)

    def test_bounded_strict_json(self):
        for raw in (b'[]',b'{"a":1,"a":2}',b'{"x":NaN}',b'{"x":1.0}',
                    b' '*(1024**2+1)):
            with self.assertRaises(ValueError): checkpoint.replay_json(raw)
        report=self.report(); report['pins']['sdk_library']['native_scaled_surface_chain.so']='bad'
        with self.assertRaises(ValueError): checkpoint.replay(report)

    def synthetic_private(self):
        report=self.report(); p=report['pins']
        gpu=dict(status='complete',copy_byte_exact=True,submitted_native_size_byte_exact=True,
            scaled_repeats=2,scaled_repeat_byte_exact=True,output_words=12441600,
            output_nonzero_low_six_bit_words=0,
            original_el_plane_hashes_match_extraction_and_successful_decoder_expected_planes=True,
            independent_packed_input_word_comparisons=3110400,independent_packed_input_words_exact=True,
            executed_packer_source_and_binary_and_original_planes_unchanged=True,
            executed_probe_and_input_and_wrapper_and_libva_libva_drm_libdrm_unchanged=True,
            hardware_engine_verified=False,fractional_quantizer_selected=False,
            production_precision_changed=False,amd_measurement=False,
            input_size=[1920,1080],output_size=[3840,2160],
            submitted_request=copy.deepcopy(checkpoint.FIXED['submitted_request']),
            scaled_own_client_vpp_engine_delta_ns=[
                {'render':0,'copy':0,'video':0,'video-enhance':9263956},
                {'render':0,'copy':0,'video':0,'video-enhance':6725784}],
            resources=dict(memory_max_bytes=536870912,memory_swap_max_bytes=0,
                scaled_memory_peak_snapshot_bytes=[107167744,106897408],
                all_observed_swap_current_bytes=0,all_observed_memory_limit_events=0,
                all_observed_oom_events=0,all_observed_oom_kill_events=0),
            driver_identity_after_only=dict(driver_binary_prepost_pin_established=False,
                driver_sha256=p['driver_after_only']['intel_ihd_driver']))
        gpu['public_artifact_pins']={k+'_sha256':v for group in
            ('scaler_artifacts','system_libraries') for k,v in p[group].items()}
        memory={'memory.max':'536870912','memory.swap.max':'0',
                'memory.swap.current':'0','memory.peak':'245694464',
                'memory.events':'high 0\nmax 0\noom 0\noom_kill 0'}
        consumer=dict(status='complete',raw_samples_exact=12441600,fractional_chunks=0,
            arithmetic_dispatches=191,route='exact-whole-code',
            hardware_source_association_verified_by_this_runner=False,
            independent_arithmetic_reference=False,old_linear_baseline_compared=False,
            completion=dict(kind='arithmetic-frame-complete',counts=[8294400,2073600,2073600],
                diagnostic_queries=0),memory_before=copy.deepcopy(memory),memory_after=copy.deepcopy(memory),
            source_sha256=dict(p['engine_sources']),
            runner_sha256=p['consumer_source']['native_scaled_surface_frame.py'],
            private_input_sha256={'library':p['sdk_library']['native_scaled_surface_chain.so'],
                                 'rpu':'private-rpu-secret'})
        consumer['private_runtime_sha256']={path:p['consumer_runtime'][name] for name,path in (
            ('python3.12','/usr/bin/python3.12'),
            ('ld-linux-x86-64.so.2','/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'),
            ('libc.so.6','/usr/lib/x86_64-linux-gnu/libc.so.6'))}
        gpu['private_pixels']='/secret/film.mkv'
        consumer['private_stage_sha256']={'pixels':'private-pixels-secret'}
        return gpu,consumer

    def test_private_artifacts_are_not_exported(self):
        gpu,consumer=self.synthetic_private()
        result=checkpoint.summarize(gpu,consumer)
        self.assertEqual(result,self.report())
        raw=json.dumps(result)
        for value in ('/secret/film.mkv','private-rpu-secret','private-pixels-secret'):
            self.assertNotIn(value,raw)

    def test_failed_evidence_cannot_produce_success(self):
        for section,key,value in [('gpu','copy_byte_exact',False),
                ('gpu','output_words',True),('gpu','scaled_repeats',1),
                ('consumer','raw_samples_exact',12441599),
                ('consumer','old_linear_baseline_compared',True)]:
            gpu,consumer=self.synthetic_private()
            (gpu if section=='gpu' else consumer)[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                checkpoint.summarize(gpu,consumer)
        gpu,consumer=self.synthetic_private()
        consumer['memory_after']['memory.events']='high 0\nmax 0\noom 1\noom_kill 0'
        with self.assertRaises(ValueError): checkpoint.summarize(gpu,consumer)


if __name__ == '__main__': unittest.main()
