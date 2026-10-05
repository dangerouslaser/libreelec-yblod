import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from capture_repeat import (CHUNK_BYTES, FRAME_BYTES, Hardware, attempt_driver_dump, capture_cycle, compare_files, copy_chunks, file_record,
                            fresh_log, parse_buffers, parse_freeze, parse_state,
                            physical_read, same_picture, stop_verified)


class CaptureParserTests(unittest.TestCase):
    def test_exact_log_watermark_excludes_stale_records(self):
        before = "[ 1.000001] buf[0]mem_start = 0x1000, mem_size = 0x1000\n[ 2.0] old\n"
        after = before + "[ 2.0] new appended same tick\n[ 2.000001] new\n"
        self.assertEqual(fresh_log(before, after), "[ 2.0] new appended same tick\n[ 2.000001] new\n")
        with self.assertRaisesRegex(ValueError, "watermark"):
            fresh_log(before, "[ 3.0] ring overwritten\n")
        with self.assertRaisesRegex(ValueError, "backwards"):
            fresh_log(before, before+"[ 1.0] clock reset\n")

    def test_ring_rotation_preserves_unique_suffix(self):
        before = "".join(f"[ {i}.0] line{i}\n" for i in range(30))
        after = "".join(f"[ {i}.0] line{i}\n" for i in range(10, 31))
        self.assertEqual(fresh_log(before, after), "[ 30.0] line30\n")

    def test_embedded_bracket_values_are_not_kernel_timestamps(self):
        before = "[ 20.123456] register [90000] nested [999999.123456]\n"
        new = "[ 20.223456] next [1] buffer[3]\n"
        self.assertEqual(fresh_log(before, before+new), new)
        # Raw payload continuation lines with integer brackets are not times.
        before += "[90000] register continuation\n"
        self.assertEqual(fresh_log(before, before+new), new)
        fake = "payload [ 99.123456] flags=0x2,flags_isr=0x0\n"
        real = "[ 20.1] flags=0x0,flags_isr=0x0\n[ 20.2] cma_flag:0x0\n"
        self.assertEqual(parse_state(fake+real)["flags"], 0)
        with self.assertRaisesRegex(ValueError, "RD-list"):
            parse_freeze("payload [ 20.3] vdin_vf_freeze: add 1 frame from rd list\n")

    def test_parse_single_fresh_state_hex_cma_and_flags(self):
        report = parse_state("[ 1.1] flags=0x162804,flags_isr=0x0\n[ 1.2] cma_flag:0x101\n")
        self.assertEqual(report["cma_flag"], 0x101)
        self.assertFalse(report["flags"] & 2)
        with self.assertRaises(ValueError):
            parse_state("[ 1.1] flags=0x2,flags_isr=0x0\n")
        with self.assertRaises(ValueError):
            parse_state("[ 1.1] flags=0x2,flags_isr=0x0\n[ 1.2] cma_flag:0x1\n[ 1.3] cma_flag:0x1\n")

    def test_fresh_buffer_exact_bounds_and_rejection(self):
        line = f"[ 5.01] buf[1]mem_start = 0xc86ea000, mem_size = {FRAME_BYTES:#x}\n"
        parsed = parse_buffers(line)
        self.assertEqual(parsed[1]["size"], FRAME_BYTES)
        self.assertEqual(parsed[1]["address_hex"], "0xc86ea000")
        for changed in (line+line, line.replace("0xc86ea000", "0xc86ea001"),
                        line.replace(f"{FRAME_BYTES:#x}", "0x1000"), line.replace("buf[1]", "buf[9]")):
            with self.assertRaises(ValueError):
                parse_buffers(changed)
        with self.assertRaisesRegex(ValueError, "overlap"):
            parse_buffers(line+line.replace("buf[1]", "buf[2]"))

    def test_freeze_rejects_wr_fallback_duplicate_and_stale(self):
        line = "[ 1.20] vdin_vf_freeze: add 2 frame from rd list\n"
        self.assertEqual(parse_freeze(line), {"index": 2, "timestamp": "1.20", "list": "rd"})
        real_wr = "[ 1.21] vdin_vf_freeze: add frame 3 from wr list.\n"
        for changed in ("", line+line, line.replace("rd list", "wr list"), real_wr, line+real_wr):
            with self.assertRaisesRegex(ValueError, "RD-list"):
                parse_freeze(changed)

    def test_paused_identity_changes_fail(self):
        initial = {"pts_90k": 1, "kodi": {"speed": 0, "time": {"seconds": 84}}, "hdmi_config": "DV"}
        same_picture(initial, dict(initial, monotonic_ns=100))
        for key, value in (("pts_90k", 2), ("kodi", {"speed": 1}), ("hdmi_config", "SDR")):
            with self.assertRaisesRegex(ValueError, key):
                same_picture(initial, dict(initial, **{key: value}))

    def test_kodi_player_extra_fields_are_accepted_without_playback_changes(self):
        players = [{"playerid": 1, "playertype": "internal", "type": "video"}]
        properties = {"speed": 0, "time": {"hours": 0, "minutes": 1, "seconds": 24, "milliseconds": 600}}
        config = "VIC: 93 3840x2160p24hz\nEOTF: DV-Std\n"
        with (patch("capture_repeat.rpc", side_effect=[players, properties]) as calls,
              patch("capture_repeat.Path.read_text", side_effect=[config, "0x1234"])):
            snapshot = Hardware().snapshot()
        self.assertEqual(snapshot["kodi"], properties)
        self.assertEqual(snapshot["pts_90k"], 0x1234)
        self.assertEqual([call.args[0] for call in calls.call_args_list], ["Player.GetActivePlayers", "Player.GetProperties"])

    def test_stop_write_is_not_assumed_success(self):
        class Driver:
            def __init__(self, flags): self.flags, self.commands = flags, []
            def command(self, value): self.commands.append(value)
            def state(self): return {"flags": self.flags}, ""
        idle = Driver(0)
        self.assertEqual(stop_verified(idle), {"flags": 0})
        self.assertEqual(idle.commands, ["v4l2stop"])
        with self.assertRaisesRegex(ValueError, "stop was not confirmed"):
            stop_verified(Driver(2))


class ReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_chunked_copy_never_requests_whole_frame(self):
        class Source:
            largest = 0
            def __getitem__(self, interval):
                self.largest = max(self.largest, interval.stop-interval.start)
                return bytes([interval.start//CHUNK_BYTES])* (interval.stop-interval.start)
        source = Source()
        target = self.root / "first.rgb"
        size = 2*CHUNK_BYTES+17
        result = copy_chunks(source, size, target)
        self.assertEqual(source.largest, CHUNK_BYTES)
        self.assertEqual(result, file_record(target))
        self.assertEqual(result["bytes"], size)
        with self.assertRaises(FileExistsError):
            copy_chunks(source, size, target)

    def test_missing_driver_dump_strict_default_rejects(self):
        from unittest.mock import Mock
        driver, cycle, hardware = self.root / "missing.rgb", {}, Mock()
        with self.assertRaisesRegex(ValueError, "strict default"):
            attempt_driver_dump(hardware, driver, 2, cycle)
        hardware.command.assert_called_once_with(f"capture {driver} 2")
        self.assertEqual(cycle["dma_sync"]["status"], "unverified")
        self.assertNotIn("driver_dump", cycle)

    def test_missing_driver_dump_explicit_opt_in_records_limitation(self):
        from unittest.mock import Mock
        cycle = {}
        self.assertFalse(attempt_driver_dump(Mock(), self.root / "missing.rgb", 1, cycle, True))
        self.assertFalse(cycle["dma_sync"]["driver_dump_available"])
        self.assertIn("stale cache", cycle["dma_sync"]["limitation"])
        self.assertNotIn("driver_dump", cycle)

    def test_opt_in_does_not_allow_bad_driver_dump_or_overwrite(self):
        from unittest.mock import Mock
        driver = self.root / "bad.rgb"
        hardware = Mock()
        hardware.command.side_effect = lambda _: driver.write_bytes(b"short")
        with self.assertRaisesRegex(ValueError, "size differs"):
            attempt_driver_dump(hardware, driver, 0, {}, True)
        hardware.reset_mock()
        with self.assertRaisesRegex(ValueError, "already exists"):
            attempt_driver_dump(hardware, driver, 0, {}, True)
        hardware.command.assert_not_called()

    def test_available_driver_dump_keeps_record_in_both_modes(self):
        from unittest.mock import Mock
        for allow in (False, True):
            driver, cycle = self.root / f"driver-{allow}.rgb", {}
            hardware = Mock()
            hardware.command.side_effect = lambda _, path=driver: path.write_bytes(b"abcd")
            with patch("capture_repeat.FRAME_BYTES", 4):
                self.assertTrue(attempt_driver_dump(hardware, driver, 0, cycle, allow))
            self.assertEqual(cycle["driver_dump"], file_record(driver))
            self.assertEqual(cycle["dma_sync"]["status"], "driver_dump_observed")

    def test_unsynchronized_cycle_retains_both_reads_without_driver_claim(self):
        from unittest.mock import Mock
        initial = {"pts_90k": 1, "kodi": {"speed": 0}, "hdmi_config": "fixed"}
        hardware = Mock()
        hardware.snapshot.return_value = initial
        state_log = f"[ 3.0] buf[1]mem_start = 0x10000, mem_size = {FRAME_BYTES:#x}\n"
        hardware.state.return_value = ({"flags": 2}, state_log)
        hardware.event.return_value = "[ 3.1] vdin_vf_freeze: add 1 frame from rd list\n"
        def read_fixture(_buffer, path):
            path.write_bytes(b"same frozen bytes")
            return file_record(path)
        with (patch("capture_repeat.time.sleep"),
              patch("capture_repeat.physical_read", side_effect=read_fixture) as reads,
              patch("capture_repeat.metadata_check", return_value={"all_crc_valid": True}) as metadata):
            cycle = capture_cycle(hardware, self.root, 0, initial, allow_unverified_dma_sync=True)
        self.assertEqual(reads.call_count, 2)
        self.assertEqual(metadata.call_count, 2)
        self.assertEqual(cycle["status"], "complete")
        self.assertEqual(cycle["dma_sync"]["status"], "unverified")
        self.assertEqual(set(cycle["metadata"]), {"first_read", "second_read"})
        self.assertNotIn("driver_dump", cycle)
        self.assertNotIn("driver_vs_first_comparison", cycle)
        self.assertTrue(cycle["same_buffer_comparison"]["byte_identical"])

    def test_first_difference_at_chunk_boundary_and_length(self):
        first, second = self.root / "a", self.root / "b"
        first.write_bytes(b"abcdefgh")
        second.write_bytes(b"abcdXfgh")
        self.assertEqual(compare_files(first, second, 4), {"byte_identical": False, "first_difference_offset": 4, "compared_bytes": 8})
        second.write_bytes(b"abcdefgh")
        self.assertEqual(compare_files(first, second, 4), {"byte_identical": True, "first_difference_offset": None, "compared_bytes": 8})
        second.write_bytes(b"abcdefghi")
        self.assertEqual(compare_files(first, second, 4)["first_difference_offset"], 8)

    def test_short_copy_fails(self):
        with self.assertRaisesRegex(ValueError, "short"):
            copy_chunks(b"short", 10, self.root / "short.rgb")

    def test_physical_read_is_readonly_sync_and_descriptor_closed_on_failure(self):
        import os
        import mmap
        with (patch("capture_repeat.os.open", return_value=42) as opened,
              patch("capture_repeat.os.close") as closed,
              patch("capture_repeat.mmap.mmap", side_effect=OSError("test mapping denied")) as mapped):
            with self.assertRaises(OSError):
                physical_read({"address_hex": "0x1000", "size": 4096}, self.root / "unused")
        opened.assert_called_once_with("/dev/mem", os.O_RDONLY | os.O_SYNC)
        mapped.assert_called_once_with(42, 4096, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ, offset=4096)
        closed.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
