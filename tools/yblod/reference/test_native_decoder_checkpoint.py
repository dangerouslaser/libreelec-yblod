"""Synthetic sanitizer tests only: not a decoder execution checkpoint."""
import copy
import json
import hashlib
from pathlib import Path
import unittest
import native_decoder_checkpoint as probe


def fixture():
    pins = lambda names: {name: "a"*64 for name in names}
    resource = {"memory.max": "536870912", "memory.swap.max": "0", "memory.swap.current": "0",
                "memory.peak": "8388608", "memory.events": "max 0\noom 0\noom_kill 0\nhigh 0"}
    stages = {role: dict(samples=16 if role.endswith("_Y") else 4, byte_exact=True, sha256="b"*64) for role in probe.STAGES}
    private = dict(status="complete", memory_cap_required=True, baseline_kind="native-c-integer",
                   completion=dict(kind="arithmetic-frame-complete", counts=[16,4,4], diagnostic_queries=0),
                   stages=stages, input_sha256={role:"b"*64 for role in probe.STAGES},
                   library_sha256="a"*64, source_sha256=pins(probe.RUNTIME_SOURCES),
                   memory_before=resource, memory_after=copy.deepcopy(resource),
                   instructions_sha256="private-instructions", private_path="/private/film.mkv",
                   nested_secret=dict(rpu="private-rpu"))
    private["producer"] = dict(schema="yblod.native-decoder-ingestion.v1", status="complete",
        local_presentation_index=64, frames_received=65, packets_sent=66, original_pts_verified=False,
        decoder_metadata=True, raw_rpu_exact=True, el_active_planes_exact=True, crc_requested=True,
        warning_or_error_logs=0, adapter_abi=1, instructions_bytes=9216, instructions_sha256="c"*64,
        avcodec_version=62*65536+1, avformat_version=62*65536+1, avutil_version=60*65536+1)
    private["instructions_sha256"] = "c"*64
    private["producer_binary_sha256"] = "a"*64
    private["producer_memory_before"] = copy.deepcopy(resource)
    private["producer_memory_after"] = copy.deepcopy(resource)
    kwargs = dict(producer_sources=pins(probe.PRODUCER_SOURCES), bridge_sources=pins(probe.BRIDGE_SOURCES),
                  artifacts=pins(probe.ARTIFACTS), target="ollie-cpu", compiler_version="GCC 16.2.0")
    kwargs["fixture_repair_proof"] = dict(independently_verified=True, prefix_byte_exact=True,
        exact_eof_zero_proven=True, removed_exact_eof_zero_bytes=1, original_sha256="d"*64,
        derived_sha256="e"*64, original_bytes=1025, derived_bytes=1024)
    return private, kwargs


class SanitizerTests(unittest.TestCase):
    def test_reviewed_real_checkpoint_replay_and_source_pins(self):
        root = Path(__file__).resolve().parent
        path = root/'results/native-decoder-frame-2296-20261005a.json'
        with path.open('rb') as stream: raw = stream.read(1024**2+1)
        report = probe.replay_json(raw)
        self.assertEqual(report['completion']['counts'], [8294400,2073600,2073600])
        self.assertEqual(report['producer']['frames_received'], 65)
        self.assertEqual(report['producer']['packets_sent'], 65)
        self.assertEqual(report['execution_targets'], dict(producer='libreelec-vm-cpu', reconstruction='ollie-cpu'))
        for field in ('runtime_source_sha256','executed_producer_source_sha256','executed_bridge_source_sha256'):
            for name, expected in report[field].items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), expected, name)

    def test_strict_public_replay_and_tampering(self):
        private, kwargs = fixture(); result = probe.summarize(private, **kwargs)
        self.assertEqual(probe.replay_json(json.dumps(result).encode()), result)
        for path,value in ((("gpu_attempted",),0),(("private_path",),"secret"),
                (("producer","raw_rpu_exact"),False),(("runtime_versions","avcodec_version"),True),
                (("fixture_repair","removed_exact_eof_zero_bytes"),2),
                (("stages","mapped_Y","sha256"),"b"*64),(("resources","before","memory.max"),True)):
            changed = copy.deepcopy(result); target = changed
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError): probe.replay_json(json.dumps(changed).encode())
        for raw in (b'[]', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1.0}', b' '*(1024**2+1)):
            with self.assertRaises(ValueError): probe.replay_json(raw)

    def test_only_counts_and_public_pins_survive(self):
        private, kwargs = fixture()
        result = probe.summarize(private, **kwargs)
        raw = json.dumps(result)
        for secret in ("/private/film.mkv", "private-rpu", "b"*64, "c"*64, "d"*64, "e"*64):
            self.assertNotIn(secret, raw)
        self.assertEqual(len(result["stages"]), 12)
        self.assertEqual(result["completion"]["counts"], [16,4,4])
        self.assertIs(result["gpu_attempted"], False)
        self.assertEqual(result["execution_targets"], dict(producer="libreelec-vm-cpu", reconstruction="ollie-cpu"))

    def test_failed_or_incomplete_never_becomes_complete(self):
        for mutation in ("failed", "missing-stage", "false-match", "wrong-count", "wrong-hash", "float-count", "boolean-query", "bypass"):
            private, kwargs = fixture()
            if mutation == "failed": private["status"] = "failed"
            elif mutation == "missing-stage": private["stages"].pop("mapped_Y")
            elif mutation == "false-match": private["stages"]["mapped_Y"]["byte_exact"] = 1
            elif mutation == "wrong-count": private["stages"]["mapped_Y"]["samples"] = 15
            elif mutation == "wrong-hash": private["stages"]["mapped_Y"]["sha256"] = "c"*64
            elif mutation == "float-count": private["completion"]["counts"][0] = 16.0
            elif mutation == "boolean-query": private["completion"]["diagnostic_queries"] = False
            else: private["memory_cap_required"] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): probe.summarize(private, **kwargs)

    def test_unbounded_swapped_oom_changed_scope_rejected(self):
        for key, value in (("memory.max","max"),("memory.swap.current","1"),
                           ("memory.peak","536870913"),("memory.events","max 0\noom 1\noom_kill 0"),
                           ("memory.events","max 0\nmax 0\noom 0\noom_kill 0")):
            private, kwargs = fixture(); private["memory_after"][key] = value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError): probe.summarize(private, **kwargs)
        private, kwargs = fixture(); private["memory_after"]["memory.max"] = "268435456"
        with self.assertRaises(ValueError): probe.summarize(private, **kwargs)

    def test_inventory_and_library_identity_are_exact(self):
        for kind in ("runtime", "producer", "bridge", "artifact", "library", "compiler", "target"):
            private, kwargs = fixture()
            if kind == "runtime": private["source_sha256"]["private-rpu"] = "a"*64
            elif kind == "producer": kwargs["producer_sources"].pop("native_decoder_ingestion.c")
            elif kind == "bridge": kwargs["bridge_sources"]["private/path"] = "a"*64
            elif kind == "artifact": kwargs["artifacts"]["film"] = "a"*64
            elif kind == "library": private["library_sha256"] = "c"*64
            elif kind == "compiler": kwargs["compiler_version"] = "/private/compiler"
            else: kwargs["target"] = "/private/host"
            with self.subTest(kind=kind), self.assertRaises(ValueError): probe.summarize(private, **kwargs)

    def test_snapshot_unknown_fields_are_not_published(self):
        private, kwargs = fixture()
        private["memory_before"]["private_path"] = "/secret"
        private["stages"]["mapped_Y"]["private_pixels"] = "secret"
        self.assertNotIn("secret", json.dumps(probe.summarize(private, **kwargs)))

    def test_decoder_success_association_and_types_are_required(self):
        for key, value in (("status","failed"),("decoder_metadata",1),("raw_rpu_exact",False),
                ("crc_requested",False),("original_pts_verified",True),("local_presentation_index",65),
                ("instructions_bytes",9215),("warning_or_error_logs",1),("frames_received",97),
                ("avcodec_version",True),("avformat_version",1.5),("instructions_sha256","f"*64)):
            private, kwargs = fixture(); private["producer"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): probe.summarize(private, **kwargs)
        private, kwargs = fixture(); private["producer_binary_sha256"] = "f"*64
        with self.assertRaises(ValueError): probe.summarize(private, **kwargs)

    def test_fixture_proof_is_required_and_private(self):
        for key, value in (("independently_verified",False),("prefix_byte_exact",1),
                           ("exact_eof_zero_proven",False),("removed_exact_eof_zero_bytes",True),
                           ("original_bytes",1026),("original_sha256","e"*64)):
            private, kwargs = fixture(); kwargs["fixture_repair_proof"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): probe.summarize(private, **kwargs)


if __name__ == "__main__": unittest.main()
