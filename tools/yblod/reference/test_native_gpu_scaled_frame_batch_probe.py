"""Synthetic larger-batch host guards; no GPU execution or speed claims."""
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile

import test_native_gpu_scaled_frame_probe as base

ROOT = Path(__file__).resolve().parent


class GPUScaledFrameBatchHostTests(base.GPUScaledFrameHostTests):
    source_name = "native_gpu_scaled_frame_batch_probe.c"
    report_schema = "yblod.native-gpu-scaled-frame-batch-probe.v1"

    def validated(self, result, counts, dispatches):
        report = super().validated(result, counts, dispatches)
        self.assertEqual(report["gpu_batch_samples"], 262144)
        self.assertEqual(report["cpu_chunk_samples"], 65536)
        self.assertEqual(report["gpu_batch_dispatches"],
                         sum((n + 262143) // 262144 for n in counts))
        self.assertEqual(report["gpu_oracle_dispatches"], 0)
        self.assertEqual(report["golden_suffix_samples"],
                         (counts[-1] - 1) % 65536 + 1)
        self.assertEqual(report["golden_suffix_offset"],
                         (counts[-1] - 1) % 262144 + 1
                         - ((counts[-1] - 1) % 65536 + 1))
        self.assertEqual(report["timed_crosscheck_scope"],
                         "final-CPU-subchunk-suffix-only")
        return report

    def test_source_keeps_cpu_subchunks_and_suffix_indices(self):
        # Offline structural guard only; this does not execute GPU code.
        source = (ROOT / self.source_name).read_text()
        self.assertIn("enum { CHUNK=65536, GPU_BATCH=262144 };", source)
        self.assertEqual(source.count(
            "uint32_t subcount=n-offset;if(subcount>CHUNK)subcount=CHUNK;"), 2)
        self.assertIn("dispatch(w,c,substart,subcount,&reference,NULL,scratch)", source)
        self.assertIn("suffix_offset(final_gpu_count,last_count,&suffix)", source)
        self.assertIn("size_t index=(size_t)suffix+i;", source)

    def test_suffix_helper_boundaries_and_atomic_invalid_rejection(self):
        # Compile the actual private pure helper into a host-only harness.
        # This checks suffix arithmetic, not graphics execution.
        directory = Path(self.directory.name)
        harness = directory / "suffix-helper.c"
        harness.write_text('#define main yb_batch_original_main\n#include "'
            + str(ROOT / self.source_name) + '"\n#undef main\n'
            'int main(void) {\n'
            ' const uint32_t good[][3]={{1,1,0},{65536,65536,0},'
            '{262144,65536,196608},{65792,256,65536},{1024,1024,0}};\n'
            ' for(unsigned i=0;i<5;i++){uint32_t offset=77;'
            ' if(!suffix_offset(good[i][0],good[i][1],&offset)||offset!=good[i][2])return 1;}\n'
            ' const uint32_t bad[][2]={{0,0},{1,0},{65536,65537},'
            '{262145,1},{100,101}};\n'
            ' for(unsigned i=0;i<5;i++){uint32_t offset=77;'
            ' if(suffix_offset(bad[i][0],bad[i][1],&offset)||offset!=77)return 2;}\n'
            ' if(suffix_offset(1,1,NULL))return 3;\n return 0;\n}\n')
        binary = directory / "suffix-helper"
        compiled = subprocess.run(["cc", "-std=c11", "-O2", "-fno-lto", "-Wall",
            "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
            "-DYB_GPU_PROBE_HOST_ONLY", "-I", str(ROOT),
            *shlex.split(os.environ.get("YB_GPU_FRAME_TEST_CFLAGS", "")),
            str(harness), *(str(ROOT / name) for name in (
                "native_gpu_guard.c", "native_gpu_probe_fixture.c",
                "native_mmr_composer.c", "native_scaled_surface.c",
                "native_decoder_frame_bridge.c", "native_integration_probe.c",
                "native_composer.c", "native_sampling_probe.c")),
            "-o", str(binary)], capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        result = subprocess.run([str(binary)], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def fixture_geometry(self, directory, width, height):
        paths, _ = self.fixture(directory)
        ycount = width * height
        ccount = ycount // 4
        y = [(i * 17 + i // 1024) % 1024 for i in range(ycount)]
        chroma = [(i * 19 + i // 256) % 1024 for i in range(ccount)]
        payloads = {
            1: struct.pack("<" + str(ycount) + "H", *y),
            2: struct.pack("<" + str(ccount) + "H", *chroma),
            3: struct.pack("<" + str(ccount) + "H", *reversed(chroma)),
            4: struct.pack("<" + str(ccount) + "H", *chroma),
            5: struct.pack("<" + str(ycount + 2 * ccount) + "H",
                *([v * 64 for v in y] + [word for v in chroma
                  for word in (v * 64, (1023 - v) * 64)])),
        }
        for index, payload in payloads.items():
            paths[index].write_bytes(payload)
        return paths, [ycount, ccount, ccount]

    def test_gpu_batch_boundary_cpu_subchunks_and_partial_tail(self):
        # Exact 262144 Y boundary, then a 1024-sample Y tail and 256-sample
        # chroma tails. The host still verifies bounded 65536-sample subchunks.
        for width, height in ((512, 512), (514, 512)):
            with self.subTest(width=width), tempfile.TemporaryDirectory() as temporary:
                paths, counts = self.fixture_geometry(Path(temporary), width, height)
                dispatches = sum((n + 65535) // 65536 for n in counts)
                self.validated(self.invoke(paths, (str(width), str(height))),
                               counts, dispatches)

    def test_late_fractional_sample_after_larger_batch_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = self.fixture_geometry(Path(temporary), 514, 512)
            raw = bytearray(paths[5].read_bytes())
            raw[-2] |= 63
            paths[5].write_bytes(raw)
            result = self.invoke(paths, ("514", "512"))
            self.rejected(result)
            self.assertNotEqual(result.returncode, 3)
