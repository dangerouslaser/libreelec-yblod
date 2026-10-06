"""Saved synthetic checkpoint audit; no GPU, media or runtime access."""
import hashlib
import json
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent

class ExportCheckpointTests(unittest.TestCase):
    def test_frozen_source_and_numeric_results(self):
        raw=(HERE/"VAAPI_SURFACE_EXPORT_RESULTS.json").read_bytes()
        self.assertLess(len(raw),65536)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),"3841fd4aeec27125bdeb56bb6427df51e72ffe3735d01a81bf7848da6728143a")
        data=json.loads(raw)
        self.assertEqual(set(data),{"schema","provenance","runs"})
        root=next(p for p in HERE.parents if (p/"engine").is_dir())
        for name,pin in data["provenance"]["source_sha256"].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),pin)
        self.assertEqual([r["format"] for r in data["runs"]],["p010","y416"])
        for run in data["runs"]:
            r=run["result"]
            for key in ("complete","synthetic_upload","surface_synchronized",
                        "descriptor_structural_valid","cleanup_complete"):
                self.assertIs(r[key],True)
            for key in ("layout_extent_verified","egl_import_tested",
                        "zero_copy_proven","dv_playback_tested"):
                self.assertIs(r[key],False)
            self.assertEqual((r["width"],r["height"],r["objects"]),(4,4,1))
            self.assertEqual(r["nominal_rt_bits"],10 if run["format"]=="p010" else 12)
            self.assertEqual(r["layers"],2 if run["format"]=="p010" else 1)
            for obj in r["object_layout"]:
                self.assertEqual(set(obj),{"size","modifier"})
                self.assertEqual(obj["modifier"],72057594037927938)
            for layer in r["layer_layout"]:
                self.assertEqual(set(layer),{"drm_format","planes"})
                for plane in layer["planes"]:
                    self.assertEqual(set(plane),{"object_index","offset","pitch"})
            resources=run["resources"]
            self.assertTrue(resources["artifacts_unchanged"])
            self.assertEqual(resources["kodi_before"],"active")
            self.assertEqual(resources["kodi_after"],"active")
            for phase in ("before","after"):
                p=resources[phase]
                self.assertEqual(p["memory.max"],"536870912")
                self.assertEqual(p["memory.swap.max"],"0")
                self.assertEqual(p["memory.swap.current"],"0")
                self.assertLess(int(p["memory.peak"]),512*1024**2)
                events=dict(line.split() for line in p["memory.events"].splitlines())
                for key in ("high","max","oom","oom_kill"):
                    self.assertEqual(events[key],"0")
