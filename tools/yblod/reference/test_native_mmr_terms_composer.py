"""Independent contract plus every basis/power read of the term candidate."""
from pathlib import Path
import tempfile
import test_native_mmr_composer_independent as base
from test_native_composer import polynomial, mmr

ROOT = Path(__file__).resolve().parent


class TermsMMRTests(base.MMRIndependentTests):
    @classmethod
    def setUpClass(cls):
        staging = tempfile.TemporaryDirectory()
        cls.addClassCleanup(staging.cleanup)
        directory = Path(staging.name)
        for path in ROOT.iterdir():
            if path.suffix in (".c", ".h"):
                source = ROOT / "native_mmr_terms_composer.c" if path.name == "native_mmr_composer.c" else path
                (directory / path.name).symlink_to(source.resolve())
        original = base.ROOT
        try:
            base.ROOT = directory
            super().setUpClass()
        finally:
            base.ROOT = original

    def test_each_active_basis_power_signed_and_endpoint_clamped(self):
        for depth in (8, 10):
            last = (1 << depth) - 1
            triples = [(i, (i * 17 + 3) & last, (i * 31 + 7) & last)
                       for i in range(last + 1)]
            parameters = [dict(offset=last // 2, slope=2048, threshold=3, maximum=1025)] * 3
            unit = 1 << 32
            for row in range(3):
                for term in range(7):
                    rows = [[0] * 7 for _ in range(3)]
                    rows[row][term] = unit
                    negative = [[-v for v in r] for r in rows]
                    source = [polynomial([0, last], [0, unit]),
                              mmr([1, last - 1], rows, -unit // 8),
                              mmr([3, last - 3], negative, unit // 2)]
                    self.compare(source, depth, 32, parameters, 12,
                                 triples, list(range(last + 1)))
