"""Run the unchanged independent contract against prepared code tables."""
from pathlib import Path
import tempfile
import test_native_mmr_composer_independent as base

ROOT = Path(__file__).resolve().parent


class PreparedMMRTests(base.MMRIndependentTests):
    @classmethod
    def setUpClass(cls):
        staging = tempfile.TemporaryDirectory()
        cls.addClassCleanup(staging.cleanup)
        directory = Path(staging.name)
        for path in ROOT.iterdir():
            if path.suffix in (".c", ".h"):
                source = ROOT / "native_mmr_prepared_composer.c" if path.name == "native_mmr_composer.c" else path
                (directory / path.name).symlink_to(source.resolve())
        original = base.ROOT
        try:
            base.ROOT = directory
            super().setUpClass()
        finally:
            base.ROOT = original
