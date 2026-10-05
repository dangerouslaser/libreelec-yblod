"""Reuse prepared synthetic fixtures to check native whole-frame stage bytes.

This deliberately inherits the unchanged streaming differential fixtures. The
oracle runs first; only the streaming backend invocation is replaced. During
native processing both standalone and reference Python arithmetic are forbidden.
"""
from contextlib import ExitStack
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import native_stage
import reference
import streaming_composer as composer
import test_streaming_differential as differential


class NativeFrameTests(differential.StreamingDifferentialTests):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):
            raise unittest.SkipTest("host C compiler unavailable")
        cls.temporary=tempfile.TemporaryDirectory()
        cls.library=native_stage.build(Path(cls.temporary.name)/"build")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def compare(self,**fixture):
        original=composer.run
        calls=[]
        def native_run(*args,**kwargs):
            with ExitStack() as patches:
                for module,name in ((composer.mapping,"map_sample"),(composer.nlq,"correction"),
                                    (composer.composition,"compose_residual"),(reference,"map_sample"),
                                    (reference,"inverse_el"),(reference,"reconstruct")):
                    patches.enter_context(mock.patch.object(module,name,
                        side_effect=AssertionError("Python arithmetic reached during native frame")))
                report=original(*args,**kwargs,backend="native",native_library=self.library)
            self.assertEqual(report["backend"],"native")
            self.assertIn("native_provenance",report)
            self.assertEqual(len(report["stages"]),12)
            calls.append(report)
            return report
        with mock.patch.object(composer,"run",side_effect=native_run):
            super().compare(**fixture)
        self.assertEqual(len(calls),len(fixture.get("chunks",(1,3,65536))))


if __name__=="__main__":unittest.main()
