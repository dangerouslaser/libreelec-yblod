"""Source-colour invariance, not trim semantics or HDMI serialization proof.

The saved association fixture is synthetic/opaque, not a conforming bitstream.
Extension dictionaries exercise ownership boundaries, not full RPU validation.
"""
import copy
import hashlib
import unittest

import colour_metadata
from colour_stage import ColourConfig, convert_sample
import test_colour_metadata as fixture_support
from test_colour_stage import IDENTITY, UNIT


def add_extensions(dm, variant):
    value = copy.deepcopy(dm)
    if variant:
        blocks = value["cmv29_metadata"]["ext_metadata_blocks"]
        blocks.extend([
            {"Level1": {"min_pq": 0, "avg_pq": 512+variant, "max_pq": 3000+variant}},
            {"Level2": {"target_max_pq": 2500, "trim_slope": 2048+variant,
                        "trim_offset": 2048, "trim_power": 2048,
                        "trim_chroma_weight": 2048, "trim_saturation_gain": 2048,
                        "ms_weight": -1}}])
        value["cmv29_metadata"]["num_ext_blocks"] = len(blocks)
        value["cmv40_metadata"] = {"num_ext_blocks": 1, "ext_metadata_blocks": [
            {"Level8": {"target_display_index": 1, "trim_slope": 2048+variant,
                        "trim_offset": 2048, "trim_power": 2048}}]}
    return value


def configuration(dm):
    return ColourConfig.from_dm(dm, target_ycc=IDENTITY, target_lms=IDENTITY,
                               target_offset=(0, 0, 0), pq_policy=UNIT, code_scale=4096)


class DisplayMetadataSensitivityTests(unittest.TestCase):
    def bundle(self):
        fixture = fixture_support.ColourMetadataTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_adding_and_changing_extensions_leave_every_colour_intermediate_unchanged(self):
        fixture = self.bundle()
        original = copy.deepcopy(fixture.rpu["vdr_dm_data"])
        baseline_config = configuration(original)
        samples = ((0, 0, 0), (1, 2048, 4095), (327.25, 512.125, 2048.5),
                   (4095, 4095, 4095), (2048, 2048, 2048))
        expected = tuple(convert_sample(sample, baseline_config) for sample in samples)
        for variant in (1, 7, 100):
            modified = add_extensions(original, variant)
            self.assertNotEqual(modified, original)
            config = configuration(modified)
            self.assertEqual(config, baseline_config)
            self.assertEqual(tuple(convert_sample(sample, config) for sample in samples), expected)

    def test_checked_saved_association_and_configuration_keep_changed_dm_without_applying_trims(self):
        fixture = self.bundle()
        original = copy.deepcopy(fixture.rpu["vdr_dm_data"])
        first = colour_metadata.load(fixture.result, fixture.extraction)
        choices = dict(target_ycc=IDENTITY, target_lms=IDENTITY, target_offset=(0, 0, 0),
                       pq_policy=UNIT, outside_codes=[0, 0, 0], code_scale=4096)
        baseline = configuration(first["source_dm"])
        previous_rpu_hash = first["provenance"]["rpu_json_sha256"]
        for variant in (1, 7):
            modified = add_extensions(original, variant)
            fixture.rpu["vdr_dm_data"] = modified
            fixture.refresh()  # recompute actual saved parsed/extraction association
            checked = colour_metadata.load(fixture.result, fixture.extraction)
            self.assertEqual(checked["source_dm"], modified)
            self.assertNotEqual(checked["provenance"]["rpu_json_sha256"], previous_rpu_hash)
            previous_rpu_hash = checked["provenance"]["rpu_json_sha256"]
            self.assertEqual(checked["identity"], first["identity"])
            self.assertEqual(checked["active_rectangle"], first["active_rectangle"])
            settings = colour_metadata.make_configuration(fixture.result, fixture.extraction,
                fixture.root / f"configuration-{variant}.json", **choices)
            self.assertEqual(settings["source_dm"], modified)
            self.assertEqual(settings["source_provenance"], checked["provenance"])
            self.assertEqual(configuration(settings["source_dm"]), baseline)
            self.assertEqual(convert_sample((2048, 512.25, 4095), configuration(settings["source_dm"])),
                             convert_sample((2048, 512.25, 4095), baseline))

    def test_trim_only_changes_do_not_bypass_saved_association_hash(self):
        fixture = self.bundle()
        path = fixture.extraction / "rpu.json"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        fixture.rpu["vdr_dm_data"] = add_extensions(fixture.rpu["vdr_dm_data"], 1)
        fixture.write_json(path, fixture.rpu)  # deliberately leave extraction hash stale
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        with self.assertRaisesRegex(ValueError, "parsed RPU hash mismatch"):
            colour_metadata.load(fixture.result, fixture.extraction)


if __name__ == "__main__":
    unittest.main()
