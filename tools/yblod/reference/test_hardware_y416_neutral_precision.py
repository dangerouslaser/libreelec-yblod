import copy
from pathlib import Path
import unittest

import hardware_y416_neutral_precision as precision


class ObservedPrecisionTests(unittest.TestCase):
    def fixture(self):
        return {"schema":"yblod.hardware-y416-neutral.v1","status":"complete","all_sameformat_p010_gates_complete":True,
                "results":{"scaled":{"Y-x-step-plus":{"repeat_stable":True,"repeat_sha256":["a","a"],
                "near_neutral":{"Y":{"native_code_denominator":64,"nonzero_within_half_native_code_count":2,
                "raw_delta_histogram":[{"delta":-16,"count":1},{"delta":32,"count":1}]}}}}}}

    def test_observed_signed_words_and_invalid_histograms(self):
        report=self.fixture();rows=precision.observations(report)
        self.assertEqual([r["raw_word"] for r in rows],[32752,32800])
        for change in (lambda r:r.update(status="failed"),lambda r:r["results"]["scaled"]["Y-x-step-plus"].update(repeat_stable=False),
                       lambda r:r["results"]["scaled"]["Y-x-step-plus"]["near_neutral"]["Y"].update(nonzero_within_half_native_code_count=3)):
            bad=copy.deepcopy(report);change(bad)
            with self.assertRaises(ValueError):precision.observations(bad)
        for delta in (0,33,True,1.0):
            bad=copy.deepcopy(report);bad["results"]["scaled"]["Y-x-step-plus"]["near_neutral"]["Y"]["raw_delta_histogram"][0]["delta"]=delta
            with self.assertRaises(ValueError):precision.observations(bad)

    def test_json_rejects_duplicates_and_nonfinite(self):
        for data in ('{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}'):
            with self.assertRaises(ValueError):precision.strict_json(data)

    def test_actual_observations_native_alternatives_independent(self):
        report=Path(__file__).with_name("intel-y416-near-neutral-small-v11.json")
        if not report.exists():
            report=Path(__file__).parent/"results"/report.name
        if not report.exists():self.skipTest("archived synthetic observation artifact not installed")
        result=precision.analyse(report);self.assertEqual(result["status"],"complete")
        answers={r["raw_word"]:r for r in result["alternatives"]}
        self.assertEqual(sorted(answers),[32736,32752,32768,32784,32800])
        self.assertEqual(answers[32752]["hypothetical_literal"]["numerator"],4)
        self.assertTrue(answers[32752]["hypothetical_literal"]["opposite_sign_to_raw_delta"])
        self.assertEqual(answers[32784]["hypothetical_literal"]["numerator"],-4)
        self.assertEqual(answers[32800]["policies"]["nearest_half_up"]["integer_residual"],8)
        self.assertEqual(answers[32800]["policies"]["nearest_ties_even"]["integer_residual"],0)

    def test_production_observations_do_not_inherit_small_profile(self):
        report=Path(__file__).with_name("intel-y416-near-neutral-large-v11.json")
        if not report.exists():report=Path(__file__).parent/"results"/report.name
        if not report.exists():self.skipTest("production synthetic observation artifact not installed")
        result=precision.analyse(report)
        self.assertEqual(result["observations"],[{"stage":"scaled","case":"Y-x-step-plus",
                         "component":"Y","raw_word":32784,"count":2160}])
        answers={row["raw_word"]:row for row in result["alternatives"]}
        self.assertEqual(sorted(answers),[32768,32784])
        self.assertTrue(all(p["integer_residual"]==0 for p in answers[32784]["policies"].values()))
        self.assertEqual(answers[32784]["hypothetical_literal"]["numerator"],-4)


if __name__=="__main__":unittest.main()
