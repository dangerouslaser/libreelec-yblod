import json
import shutil
import unittest

from extract_frame import digest
from summarize_policies import POLICIES, main, summarize
import test_summarize_cases as fixtures


class PolicySummaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SummaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.case = self.expand((self.fixture.direct, self.fixture.bound))

    def expand(self, pair):
        directories = list(pair)
        for policy in POLICIES[2:]:
            path = pair[1].parent / (pair[0].name + "-" + policy)
            shutil.copytree(pair[1], path)
            self.fixture.alter(path, "output.json", lambda r: r.update(policy=policy))
            self.fixture.alter(path, "sk4.json", lambda r: r.update(policy=policy))
            directories.append(path)
        return directories

    def test_all_policies_and_deltas(self):
        report = summarize([self.case])
        self.assertEqual(report["policies"], list(POLICIES))
        self.assertEqual(report["case_count"], 1)
        self.assertEqual(report["run_count"], 5)
        controls = report["cases"][0]["controls"]
        self.assertEqual(list(controls), list(POLICIES))
        for policy, run in controls.items():
            self.assertTrue(run["byte_identical_to_direct"])
            self.assertEqual(run["channels"]["I"]["metrics"]["samples"], 24)
            self.assertEqual(run["channels"]["I"]["change_vs_direct"]["mean_absolute_codes"],
                             0 if policy == "direct" else -2)
            self.assertIn("comparison_report_sha256", run["sources"])

    def test_multiple_cases_no_pooling(self):
        second = self.expand(self.fixture.make_case("150"))
        self.fixture.alter(second[4], "sk4.json", lambda r: r["channels"]["I"].update(
            mean_absolute_codes=6, rmse_codes=7))
        report = summarize([self.case, second])
        self.assertEqual(report["run_count"], 10)
        changed = report["cases"][1]["controls"][POLICIES[4]]["channels"]["I"]
        self.assertEqual(changed["change_vs_direct"]["mean_absolute_codes"], 2)
        self.assertIn("mean_absolute_codes", changed["metrics_increased"])
        self.assertNotIn("channels", report)
        self.assertNotIn("winner", report)

    def test_byte_difference_detected(self):
        path = self.case[3] / "tunnel.rgb8"
        path.write_bytes(bytes([1]) * 96)
        self.fixture.alter(self.case[3], "output.json", lambda r: r["stages"]["unembedded_tunnel"].update(sha256=digest(path)))
        report = summarize([self.case])
        self.assertFalse(report["cases"][0]["controls"][POLICIES[3]]["byte_identical_to_direct"])

    def test_rejects_empty_wrong_count_and_duplicates(self):
        for cases in ([], [self.case[:4]], [self.case + self.case[:1]], [self.case, self.case]):
            with self.subTest(count=len(cases)):
                with self.assertRaises(ValueError):
                    summarize(cases)

    def test_rejects_wrong_policy_order(self):
        case = list(self.case)
        case[2], case[3] = case[3], case[2]
        with self.assertRaisesRegex(ValueError, "policy"):
            summarize([case])

    def test_rejects_control_provenance_mismatch(self):
        self.fixture.alter(self.case[4], "output.json", lambda r: r.update(rpu_sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "rpu_sha256"):
            summarize([self.case])

    def test_rejects_capture_mismatch(self):
        self.fixture.alter(self.case[2], "sk4.json", lambda r: r.update(capture_sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "capture_sha256"):
            summarize([self.case])

    def test_cli_and_no_overwrite(self):
        path = self.root / "policies.json"
        args = ["--case", *map(str, self.case), "--output", str(path)]
        main(args)
        before = path.read_bytes()
        self.assertEqual(json.loads(before)["run_count"], 5)
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
