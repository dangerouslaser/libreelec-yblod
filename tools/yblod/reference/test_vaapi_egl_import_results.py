"""Independent saved synthetic observations; no device or private media."""
import hashlib
import json
from pathlib import Path
import unittest
from test_vaapi_egl_import_oracle import public_p010_words

HERE=Path(__file__).resolve().parent

class ImportCheckpointTests(unittest.TestCase):
    def test_frozen_evidence_and_exact_words(self):
        raw=(HERE/"VAAPI_EGL_IMPORT_RESULTS.json").read_bytes()
        self.assertLess(len(raw),65536)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),"7319c7144a04ef048b26862e4345f95e96cb5946b5ef9e52d0c79947e7684dec")
        d=json.loads(raw)
        root=next(p for p in HERE.parents if (p/"engine").is_dir())
        for name,pin in d["provenance"]["source_sha256"].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),pin)
        self.assertEqual([r["format"] for r in d["runs"]],["p010","y416"])
        y,cb,cr=public_p010_words()
        expected=list(y)+[word for pair in zip(cb,cr) for word in pair]
        p010=d["runs"][0]["result"]["egl_import"]
        self.assertIs(p010["actual_shader_read"],True)
        self.assertEqual((p010["storage_words_compared"],p010["storage_word_mismatches"]),(24,0))
        self.assertEqual(p010["public_synthetic_storage_words"],expected)
        self.assertTrue(p010["normalized_texture"])
        self.assertFalse(p010["integer_texture"])
        self.assertFalse(p010["colour_conversion"])
        self.assertFalse(p010["filtering"])
        self.assertTrue(all(c["exact_modifier_advertised"] and not c["external_only"] for c in p010["layer_caps"]))
        y416=d["runs"][1]["result"]["egl_import"]
        self.assertIs(y416["actual_shader_read"],False)
        self.assertEqual((y416["storage_words_compared"],y416["storage_word_mismatches"]),(0,0))
        self.assertEqual(y416["public_synthetic_storage_words"],[])
        self.assertTrue(y416["layer_caps"][0]["external_only"])
        for run in d["runs"]:
            r=run["result"]
            self.assertTrue(r["complete"])
            self.assertTrue(r["surface_synchronized"])
            self.assertTrue(r["cleanup_complete"])
            self.assertFalse(r["zero_copy_proven"])
            self.assertFalse(r["dv_playback_tested"])
            self.assertEqual(r["object_layout"][0]["modifier"],72057594037927938)
            resource=run["resources"]
            self.assertTrue(resource["artifacts_unchanged"])
            self.assertEqual((resource["kodi_before"],resource["kodi_after"]),("active","active"))
            for phase in ("before","after"):
                p=resource[phase]
                self.assertEqual((p["memory.max"],p["memory.swap.max"],p["memory.swap.current"]),("536870912","0","0"))
                events=dict(line.split() for line in p["memory.events"].splitlines())
                for key in ("high","max","oom","oom_kill"):
                    self.assertEqual(events[key],"0")
