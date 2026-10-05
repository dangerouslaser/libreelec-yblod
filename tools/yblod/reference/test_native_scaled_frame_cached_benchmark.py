"""Synthetic paired-benchmark guards, not an actual target speed result."""
import json
import os
import shlex
import struct
from pathlib import Path
import subprocess
import tempfile
import test_native_scaled_frame_benchmark as base

ROOT=Path(__file__).resolve().parent


class CachedBenchmarkTests(base.BenchmarkTests):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary=Path(cls.directory.name)/"cached-benchmark"
        subprocess.run(["cc","-std=c11","-O2","-fno-lto","-Wall","-Wextra",
            "-Werror","-Wconversion","-Wshadow",
            *shlex.split(os.environ.get('YB_CACHED_BENCHMARK_TEST_CFLAGS','')),
            *(str(ROOT/name) for name in
            ("native_scaled_frame_cached_benchmark.c","native_cached_composer.c",
             "native_scaled_surface.c","native_decoder_frame_bridge.c",
             "native_integration_probe.c","native_composer.c","native_sampling_probe.c")),
             "-o",str(cls.binary)],check=True,capture_output=True)

    def test_successful_warmup_three_complete_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths,_=self.fixture(Path(temporary))
            result=self.invoke(paths)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertEqual(report['counts'],[4,1,1])
            self.assertEqual(report['component_routes'],[1,1,1])
            self.assertEqual(report['verified_dispatches'],3)
            self.assertEqual(report['verified_stage_values'],24)
            self.assertTrue(report['all_four_stages_full_frame_byte_exact'])
            self.assertEqual(report['verification_scope'],'untimed-full-frame-before-timing')
            self.assertEqual(report['orders'],['reference,cached','cached,reference','reference,cached'])
            self.assertEqual(report['warmups_per_backend'],1)
            self.assertEqual(report['paired_repeats'],3)
            self.assertEqual(report['timed_last_chunk_crosschecks'],8)
            self.assertEqual(report['timed_crosscheck_scope'],'last-chunk-only-external-kernels-no-lto')
            self.assertTrue(report['preparation_and_teardown_included'])
            self.assertTrue(0<report['plan_bytes']<65536)
            self.assertTrue(0<report['frame_bytes']<65536)
            for backend in ('reference','cached'):
                for key,values in report[backend].items():
                    self.assertEqual(len(values),3,key)
                    self.assertTrue(all(type(n) is int and n>=0 for n in values),key)
                for clock in ('wall','cpu'):
                    self.assertTrue(all(p<=t for p,t in zip(
                        report[backend]['preparation_'+clock+'_ns'],report[backend][clock+'_ns'])))

    def test_invalid_nlq_denominator_no_success_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths,instructions=self.fixture(Path(temporary))
            instructions.nlq[2].denominator=22
            with paths[0].open('wb') as stream: stream.write(bytes(instructions))
            self.rejected(self.invoke(paths))

    def test_mmr_fallback_paired_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths,instructions=self.fixture(Path(temporary))
            for c in (1,2):
                segment=instructions.mapping.components[c].segments[0]
                segment.method=1;segment.order=3
                for row in range(3):
                    for term in range(7): segment.coefficients[row][term]=0
                segment.coefficients[0][c]=1<<23
                segment.coefficients[2][6]=-(1<<22)
            with paths[0].open('wb') as stream: stream.write(bytes(instructions))
            result=self.invoke(paths)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertTrue(report['all_four_stages_full_frame_byte_exact'])
            self.assertEqual(report['component_routes'],[1,0,0])

    def test_multichunk_partial_tail_complete_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths,_=self.fixture(Path(temporary))
            width,height=258,258
            ycount=width*height;ccount=ycount//4
            codes=[(i*17)%1024 for i in range(ycount)]
            chroma=[(i*19)%1024 for i in range(ccount)]
            payloads={1:struct.pack('<'+str(ycount)+'H',*codes),
                2:struct.pack('<'+str(ccount)+'H',*chroma),
                3:struct.pack('<'+str(ccount)+'H',*reversed(chroma)),
                4:struct.pack('<'+str(ccount)+'H',*chroma),
                5:struct.pack('<'+str(ycount+2*ccount)+'H',
                    *([v*64 for v in codes]+[word for v in chroma for word in (v*64,(1023-v)*64)]))}
            for i,payload in payloads.items():
                with paths[i].open('wb') as stream: stream.write(payload)
            report=json.loads(self.invoke(paths,(str(width),str(height))).stdout)
            self.assertEqual(report['counts'],[ycount,ccount,ccount])
            self.assertEqual(report['verified_dispatches'],4)
            self.assertEqual(report['verified_stage_values'],(ycount+2*ccount)*4)
            self.assertTrue(report['all_four_stages_full_frame_byte_exact'])
