import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import capture_clean as clean


class CleanCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "fresh"
        self.backend = Mock()
        self.backend.inspect.return_value = {"name": "mesondrmfb", "blank_readback": "",
                                             "name_path": "mock/name", "control_path": "mock/blank"}
        self.hardware = Mock()
        self.hardware.snapshot.return_value = {"pts_90k": 10, "kodi": {"speed": 0}, "hdmi_config": "fixed"}
        self.validation = patch.object(clean, "validate_output", side_effect=lambda value: Path(value))
        self.validation.start()
        self.addCleanup(self.validation.stop)
        self.sleep = patch.object(clean.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.capture = patch.object(clean.capture_repeat, "run", return_value={"status": "complete", "cleanup": {"cma_restored": True}})
        self.captured = self.capture.start()
        self.addCleanup(self.capture.stop)

    def run_capture(self, **kwargs):
        return clean.run(self.output, backend=self.backend, hardware=self.hardware,
                         confirm_visible_gui=True, **kwargs)

    def test_confirmation_required_before_any_backend_access(self):
        with self.assertRaisesRegex(ValueError, "confirm-visible-gui"):
            clean.run(self.output, backend=self.backend, hardware=self.hardware)
        self.backend.inspect.assert_not_called()
        self.backend.write.assert_not_called()

    def test_non_mesondrmfb_rejected_without_writes(self):
        self.backend.inspect.return_value["name"] = "otherfb"
        with self.assertRaisesRegex(ValueError, "mesondrmfb"):
            self.run_capture()
        self.backend.write.assert_not_called()
        self.captured.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_success_records_observation_not_register_proof(self):
        result = self.run_capture()
        self.assertEqual([call.args[0] for call in self.backend.write.call_args_list], [1, 0])
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["gui_restore_write_completed"])
        self.assertIn("no independent", result["restoration_scope"])
        self.assertEqual(result["backend"]["blank_readback"], "")
        self.assertEqual(len(result["implementation_sha256"]), 64)
        self.assertEqual(len(result["capture_repeat_sha256"]), 64)
        self.assertEqual(json.loads((self.output / "gui-plane-orchestration.json").read_text()), result)
        self.captured.assert_called_once_with(self.output / "capture", cycles=3,
                                             hardware=self.hardware, allow_unverified_dma_sync=False)

    def test_dma_fallback_only_forwarded_when_explicit(self):
        result = self.run_capture(allow_unverified_dma_sync=True)
        self.assertTrue(self.captured.call_args.kwargs["allow_unverified_dma_sync"])
        self.assertTrue(result["allow_unverified_dma_sync"])

    def test_hide_failure_still_attempts_restore_and_saves_failure(self):
        self.backend.write.side_effect = [OSError("partial hide"), None]
        result = self.run_capture()
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["hide_write_completed"])
        self.assertTrue(result["gui_restore_write_completed"])
        self.captured.assert_not_called()
        self.assertTrue((self.output / "gui-plane-orchestration.json").is_file())

    def test_capture_exception_and_interrupt_restore(self):
        for failure in (OSError("capture directory failed"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                self.output = self.output.parent / type(failure).__name__
                self.captured.side_effect = failure
                result = self.run_capture()
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["gui_restore_write_completed"])
                self.assertTrue((self.output / "gui-plane-orchestration.json").is_file())

    def test_failed_capture_report_is_not_success(self):
        self.captured.return_value = {"status": "failed", "error": "CRC rejected", "cleanup": {"cma_restored": True}}
        result = self.run_capture()
        self.assertEqual(result["status"], "failed")
        self.assertIn("CRC rejected", result["errors"][0])
        self.assertTrue(result["gui_restore_write_completed"])

    def test_restore_failure_recorded_without_success_claim(self):
        self.backend.write.side_effect = [None, OSError("restore denied")]
        result = self.run_capture()
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["gui_restore_write_completed"])
        self.assertIn("restore denied", result["restore_error"])

    def test_changed_paused_picture_aborts_before_capture_and_restores(self):
        self.hardware.snapshot.side_effect = [self.hardware.snapshot.return_value,
                                             {"pts_90k": 11, "kodi": {"speed": 0}, "hdmi_config": "fixed"}]
        result = self.run_capture()
        self.assertEqual(result["status"], "failed")
        self.captured.assert_not_called()
        self.assertTrue(result["gui_restore_write_completed"])

    def test_existing_output_not_overwritten_or_gui_changed(self):
        self.output.mkdir()
        marker = self.output / "gui-plane-orchestration.json"
        marker.write_text("existing evidence")
        with self.assertRaises(FileExistsError):
            self.run_capture()
        self.backend.write.assert_not_called()
        self.assertEqual(marker.read_text(), "existing evidence")

    def test_cli_requires_visible_confirmation(self):
        with self.assertRaises(SystemExit) as failure:
            clean.main(["/storage/not-created"])
        self.assertEqual(failure.exception.code, 2)
        self.backend.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
