"""Strict public checkpoint replay; not a benchmark execution or media export."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parent
SOURCES=('native_scaled_frame_cached_benchmark.c','native_cached_composer.c',
    'native_cached_composer.h','native_scaled_surface.c','native_scaled_surface.h',
    'native_decoder_frame_bridge.c','native_decoder_frame_bridge.h',
    'native_integration_probe.c','native_integration_probe.h',
    'native_sampling_probe.c','native_sampling_probe.h','native_dovi_adapter.h',
    'native_composer.c','native_composer.h')
PIN=re.compile(r'[0-9a-f]{64}\Z')


def replay(raw):
    if type(raw) is not bytes or len(raw)>1024**2:
        raise ValueError('bounded bytes required')
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: raise ValueError('duplicate key')
            d[k]=v
        return d
    def forbidden(_): raise ValueError('noninteger JSON number')
    d=json.loads(raw,object_pairs_hook=pairs,parse_float=forbidden,parse_constant=forbidden)
    expected_keys={'schema','status','abi','execution_target','compiler','build','benchmark',
        'resources','identities','source_sha256','artifact_sha256','runtime_sha256','scope'}
    if type(d) is not dict or set(d)!=expected_keys: raise ValueError('incorrect inventory')
    def exact(value,expected):
        if type(value) is not type(expected): raise ValueError('incorrect type')
        if type(expected) is dict:
            if set(value)!=set(expected): raise ValueError('incorrect nested inventory')
            for k,v in expected.items(): exact(value[k],v)
        elif type(expected) is list:
            if len(value)!=len(expected): raise ValueError('incorrect list size')
            for a,b in zip(value,expected): exact(a,b)
        elif value!=expected: raise ValueError('incorrect checkpoint claim')
    for k,v in dict(schema='yblod.native-cached-frame-results.v1',status='complete',
                   execution_target='libreelec-vm-cpu',compiler='GCC 16.2.0').items(): exact(d[k],v)
    exact(d['abi'],dict(cached=1,scaled_surface=1,decoder_bridge=1,integration=1,composer=1,
                       instructions_bytes=9216,declared_header_layouts_verified=True))
    exact(d['build'],dict(strict_c11=True,no_lto=True,fast_math=False,fp_contract=False,
        network=False,cpus=1,memory_max_bytes=536870912,memory_plus_swap_max_bytes=536870912))
    exact(d['resources'],dict(memory_max_bytes=536870912,memory_swap_max_bytes=0,
        before_peak_snapshot_bytes=2347008,after_peak_snapshot_bytes=57438208,
        observed_swap_bytes=0,observed_high_events=0,observed_limit_events=0,
        observed_oom_events=0,observed_oom_kill_events=0,
        snapshot_scope='before-wrapper-exit-not-final-lifetime-or-total-gpu-memory',
        runtime_cpu_quota='controller-unavailable'))
    exact(d['identities'],dict(compile_sources_prepost_identical=True,
        binary_wrapper_six_inputs_libc_loader_prepost_identical=True,kodi_active_before_after=True,
        input_association='externally-checked-caller-assertion-not-established-by-this-benchmark'))
    exact(d['scope'],dict(shared_input_loading_and_scratch_allocation_timed=False,
        gpu_timed=False,io_timed=False,decode_timed=False,colour_timed=False,display_timed=False,
        fractional_policy_selected=False,production_playback_changed=False,
        independent_arithmetic_reference=False,sk4_accuracy_improvement=False,
        playback_fps_measured=False,amd_measured=False))
    benchmark=dict(schema='yblod.native-cached-paired-benchmark.v1',status='complete',
        all_four_stages_full_frame_byte_exact=True,verification_scope='untimed-full-frame-before-timing',
        verified_dispatches=191,verified_stage_values=49766400,plan_bytes=27632,frame_bytes=9384,
        warmups_per_backend=1,paired_repeats=3,
        orders=['reference,cached','cached,reference','reference,cached'],
        preparation_and_teardown_included=True,timed_last_chunk_crosschecks=8,
        timed_crosscheck_scope='last-chunk-only-external-kernels-no-lto',
        counts=[8294400,2073600,2073600],component_routes=[1,0,0],
        reference=dict(wall_ns=[603654637,602395958,656125244],
            cpu_ns=[603615547,602355383,650766414],preparation_wall_ns=[2889,2596,2960],
            preparation_cpu_ns=[2743,2343,2752]),
        cached=dict(wall_ns=[402644576,404596163,434256184],
            cpu_ns=[402629843,403998957,431407340],preparation_wall_ns=[679024,701311,729376],
            preparation_cpu_ns=[678825,701205,729041]))
    exact(d['benchmark'],benchmark)
    for field,names in [('source_sha256',SOURCES),
            ('artifact_sha256',('native_scaled_frame_cached_benchmark','private_execution_wrapper')),
            ('runtime_sha256',('libc.so.6','ld-linux-x86-64.so.2'))]:
        pins=d[field]
        if type(pins) is not dict or set(pins)!=set(names): raise ValueError('incorrect pin inventory')
        if any(type(v) is not str or not PIN.fullmatch(v) for v in pins.values()):
            raise ValueError('invalid pin')
    exact(d['artifact_sha256'],{
        'native_scaled_frame_cached_benchmark':'c672954f2b338786b0ef45b0adda8a7ab5b03f2aadf7d4b727aef98f998b7c96',
        'private_execution_wrapper':'e99889d4f37e75f653cae097940e6ed63a7fa69614d2a85220d3984edbebc90d'})
    exact(d['runtime_sha256'],{
        'libc.so.6':'d16d617f8f3d8b18bd933ab259d50c8e829650c1d0da4d5c1b1815acd9d5f5e8',
        'ld-linux-x86-64.so.2':'3bd22d737cff5359c57bd420318561e34a9cffb9738a65feb5d0b56ded9f0126'})
    return d


class CachedResultsTests(unittest.TestCase):
    def report(self):
        with (ROOT/'results/native-cached-frame-vm-20261005a.json').open('rb') as stream:
            return replay(stream.read(1024**2+1))

    def test_actual_report_and_all_executed_source_pins(self):
        d=self.report()
        for name,pin in d['source_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),pin,name)
        self.assertEqual(len(d['source_sha256']),14)

    def test_scope_identity_and_timing_tampering_rejected(self):
        for path,value in [(('benchmark','verified_stage_values'),49766399),
                (('benchmark','component_routes'),[1,1,1]),
                (('benchmark','verification_scope'),'all-timed-frames'),
                (('benchmark','plan_bytes'),True),
                (('scope','playback_fps_measured'),True),
                (('scope','sk4_accuracy_improvement'),True),
                (('resources','observed_swap_bytes'),1),
                (('resources','runtime_cpu_quota'),'one-cpu'),
                (('identities','compile_sources_prepost_identical'),False)]:
            d=self.report();d[path[0]][path[1]]=value
            with self.subTest(path=path),self.assertRaises(ValueError): replay(json.dumps(d).encode())
        d=self.report();d['benchmark']['cached']['wall_ns'][0]=1.0
        with self.assertRaises(ValueError): replay(json.dumps(d).encode())
        for field in ('artifact_sha256','runtime_sha256'):
            d=self.report();d[field][next(iter(d[field]))]='a'*64
            with self.subTest(field=field),self.assertRaises(ValueError): replay(json.dumps(d).encode())

    def test_unknown_private_data_and_malformed_json_rejected(self):
        for field in ('private_paths','metadata','input_sha256','stage_sha256'):
            d=self.report();d[field]={'secret':'private-film'}
            with self.subTest(field=field),self.assertRaises(ValueError): replay(json.dumps(d).encode())
        d=self.report();d['source_sha256']['private-rpu']='a'*64
        with self.assertRaises(ValueError): replay(json.dumps(d).encode())
        for raw in (b'[]',b'{"x":1,"x":2}',b'{"x":NaN}',b' '*(1024**2+1)):
            with self.assertRaises(ValueError): replay(raw)


if __name__=='__main__': unittest.main()
