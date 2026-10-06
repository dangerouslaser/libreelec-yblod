"""Source/dispatch contract only; not a GPU performance or accuracy test."""
from pathlib import Path
import os
import unittest
from rewrite_workgroup import rewrite, ORIGINAL

STAGED_SOURCE = Path(__file__).with_name("native_gpu_composer_backend_libplacebo_workgroup.c")
REPO_SOURCE = Path(__file__).resolve().parents[3] / "engine/experimental/native_gpu_composer_backend_libplacebo_workgroup.c"
SOURCE = Path(os.environ.get("YB_WORKGROUP_SOURCE", str(
    STAGED_SOURCE if STAGED_SOURCE.exists() else REPO_SOURCE
))).read_text()


class WorkgroupContract(unittest.TestCase):
    def test_rewrite_only_local_size(self):
        source = "prefix\n" + ORIGINAL + "\nsuffix\n"
        for x, y in ((8, 8), (16, 8), (16, 16)):
            self.assertEqual(rewrite(source, x, y),
                             f"prefix\nlayout(local_size_x={x},local_size_y={y}) in;\nsuffix\n")
        for source in ("", ORIGINAL + ORIGINAL):
            with self.assertRaises(ValueError):
                rewrite(source, 16, 8)
        with self.assertRaises(ValueError):
            rewrite(ORIGINAL, 32, 8)

    def test_create_checks_declared_group(self):
        self.assertIn("group[0]!=(GLint)YB_WORKGROUP_X", SOURCE)
        self.assertIn("group[1]!=(GLint)YB_WORKGROUP_Y", SOURCE)
        self.assertIn("invocations<(GLint)(YB_WORKGROUP_X*YB_WORKGROUP_Y)", SOURCE)

    def test_submit_uses_consistent_geometry(self):
        self.assertIn("(width+YB_WORKGROUP_X-1U)/YB_WORKGROUP_X", SOURCE)
        self.assertIn("(height+YB_WORKGROUP_Y-1U)/YB_WORKGROUP_Y", SOURCE)
        self.assertNotIn("(width+7U)/8U", SOURCE)
        self.assertNotIn("(height+7U)/8U", SOURCE)

    def test_partial_groups_cover_each_plane(self):
        for width, height in ((2, 2), (34, 18), (66, 34), (3840, 2160)):
            for divisor in (1, 2):
                for gx, gy in ((16, 8), (16, 16)):
                    w, h = width // divisor, height // divisor
                    dx, dy = (w + gx - 1) // gx, (h + gy - 1) // gy
                    self.assertLess((dx - 1) * gx, w)
                    self.assertGreaterEqual(dx * gx, w)
                    self.assertLess((dy - 1) * gy, h)
                    self.assertGreaterEqual(dy * gy, h)

    def test_fences_and_status_remain(self):
        for operation in ("g->MemoryBarrier(", "g->FenceSync(",
                          "g->ClientWaitSync(", "g->GetBufferSubData("):
            self.assertIn(operation, SOURCE)


if __name__ == "__main__":
    unittest.main()
