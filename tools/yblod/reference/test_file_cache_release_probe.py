from pathlib import Path
import tempfile
import unittest
from unittest import mock

import file_cache_release_probe as probe


class CacheProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"new"

    def test_snapshot_after_advice_precedes_every_post_advice_rehash(self):
        events=[];real_hash=probe.file_hash
        def hashed(path):events.append("hash:"+Path(path).name);return real_hash(path)
        def advice(path,sha,size):
            self.assertEqual(size,8*1024*1024);self.assertEqual(real_hash(path),sha)
            events.append("advice");return {"dontneed_advice_submitted":True,"eviction_verified":False}
        def snapshot():events.append("snapshot");return {"available":True,"memory.stat":{"file":123},"memory.current":456,"memory.max":536870912}
        with mock.patch.object(probe.release,"release_verified_file",side_effect=advice),mock.patch.object(probe,"memory_snapshot",side_effect=snapshot),mock.patch.object(probe,"file_hash",side_effect=hashed):
            report=probe.run(self.path)
        self.assertEqual(report["status"],"complete");self.assertEqual(report["gpu_jobs"],0)
        self.assertEqual(events[events.index("advice")+1:events.index("advice")+3],["snapshot","hash:synthetic-8m.bin"])
        self.assertEqual(report["before_advice_sha256"],report["after_advice_sha256"])
        self.assertEqual((self.path/report["file"]).stat().st_size,probe.FILE_BYTES)
        self.assertEqual([v["stage"] for v in report["snapshots"]],["before_write","after_write","after_hash","immediately_after_advice_before_rehash","after_rehash"])

    def test_advice_failure_retains_evidence_failed_report_no_fallback(self):
        with mock.patch.object(probe.release,"release_verified_file",side_effect=OSError("no advice")),mock.patch.object(probe,"memory_snapshot",return_value={"available":False}):
            report=probe.run(self.path)
        self.assertEqual(report["status"],"failed")
        self.assertEqual((self.path/report["file"]).stat().st_size,probe.FILE_BYTES)
        self.assertTrue((self.path/"file-cache-probe-report.json").is_file())
        self.assertNotIn("after_advice_sha256",report)

    def test_advice_mock_changes_file_detected_and_preserved(self):
        def advice(path,sha,size):Path(path).write_bytes(b"external writer changed fixture");return {}
        with mock.patch.object(probe.release,"release_verified_file",side_effect=advice),mock.patch.object(probe,"memory_snapshot",return_value={"available":False}):
            report=probe.run(self.path)
        self.assertEqual(report["status"],"failed");self.assertIn("changed",report["error"]["message"])
        self.assertEqual((self.path/report["file"]).read_bytes(),b"external writer changed fixture")

    def test_existing_destination_rejected_before_advice(self):
        self.path.mkdir()
        with mock.patch.object(probe.release,"release_verified_file") as advice:
            with self.assertRaises(FileExistsError):probe.run(self.path)
        advice.assert_not_called()


if __name__=="__main__":unittest.main()
