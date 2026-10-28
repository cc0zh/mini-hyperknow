"""Historical schema-v1 assets remain readable but never become executable trials."""

from copy import deepcopy
from pathlib import Path
import unittest

from eval_core.store import digest, read_json
from hyperknow.eval_legacy import (case_hash, classify_result, grading_budget,
                                   summarize_legacy_result, validate_case)

CASE = Path(__file__).resolve().parents[1] / "evals/concept-explanation/case.json"


def historical_result():
    case = validate_case(read_json(CASE))
    response = {"text": "历史只读测试材料，不声称来自真实模型"}
    return {"schema_version": 1, "execution_id": "历史执行-1", "stage": "collected",
            "case": case, "case_hash": case_hash(case), "final_response": response,
            "evidence": {"turn": {"response": response}},
            "rules": [{"id": key, "verdict": "pass", "reason": "data-only input"}
                      for key in ("delivery", "skill_trace", "no_artifacts", "no_questions", "trajectory")],
            "grades": [{"attempt_id": "historic-grade", "status": "completed", "calibration_status": "unreviewed",
                        "results": [{"rubric_id": item["id"], "verdict": "pass", "reason": "saved judgment",
                                     "evidence_refs": ["final_response"]} for item in case["rubric"]]}]}


class LegacyReadingTests(unittest.TestCase):
    def test_source_case_hash_and_rubric_validation_are_preserved(self):
        case = validate_case(read_json(CASE))
        self.assertEqual(len(case["rubric"]), 3)
        self.assertEqual(case_hash(case), case_hash(dict(reversed(list(case.items())))))
        for field, value in (("skill_hint", "concept-explanation"), ("expected_answer", "not a golden answer")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_case({**case, field: value})
        case["rubric"].append(deepcopy(case["rubric"][0]))
        with self.assertRaises(ValueError):
            validate_case(case)

    def test_summary_preserves_saved_judgments_and_does_not_mutate_or_alias_data(self):
        state = historical_result()
        original = deepcopy(state)
        summary = summarize_legacy_result(state)
        self.assertTrue(summary["legacy_read_only"])
        self.assertEqual(summary["label"], "good")
        self.assertEqual(state, original)
        summary["grades"][0]["results"][0]["verdict"] = "fail"
        self.assertEqual(state, original)
        self.assertIsNone(summary["subject_usage"])

    def test_grader_error_missing_measurement_and_content_failure_keep_old_meanings(self):
        state = historical_result()
        state["grades"][-1]["status"] = "error"
        self.assertEqual(classify_result(state), "unresolved")
        state = historical_result()
        state["grades"][0]["results"][0]["verdict"] = "fail"
        self.assertEqual(classify_result(state), "bad")
        state["rules"][-1]["verdict"] = "fail"
        self.assertEqual(classify_result(state), "unresolved")
        state["rules"] = []
        self.assertEqual(classify_result(state), "unresolved")

    def test_historical_budget_overrun_is_not_hidden_or_rewritten(self):
        state = historical_result()
        grade = state["grades"][-1]
        grade.update(config={"max_output_tokens": 2048}, usage={"completion_tokens": 6109})
        self.assertEqual(grading_budget(grade)["status"], "exceeded")
        self.assertEqual(classify_result(state), "unresolved")
        grade["results"][0]["verdict"] = "fail"
        self.assertEqual(classify_result(state), "bad")
        grade["usage"] = None
        self.assertEqual(grading_budget(grade)["status"], "unknown")

    def test_in_flight_response_is_neither_reparsed_nor_reissued(self):
        state = historical_result()
        state["grades"][0].update(status="in_flight", raw_response={"content": "not parsed"})
        original = deepcopy(state)
        summary = summarize_legacy_result(state)
        self.assertEqual(summary["label"], "unresolved")
        self.assertEqual(summary["grades"][0]["status"], "in_flight")
        self.assertEqual(state, original)

    def test_earliest_skill_hint_schema_preserves_original_hash_without_affecting_new_cases(self):
        state = historical_result()
        state["case"]["skill_hint"] = "concept-explanation"
        state["case_hash"] = digest(state["case"])
        original = deepcopy(state)
        self.assertEqual(summarize_legacy_result(state)["label"], "good")
        self.assertEqual(state, original)
        with self.assertRaises(ValueError):
            validate_case(state["case"])
        state["case_hash"] = case_hash({key: value for key, value in state["case"].items()
                                       if key != "skill_hint"})
        with self.assertRaisesRegex(ValueError, "identity"):
            summarize_legacy_result(state)
        state["case"]["skill_hint"] = "unrecognized-historical-hint"
        state["case_hash"] = digest(state["case"])
        with self.assertRaises(ValueError):
            summarize_legacy_result(state)

    def test_bad_schema_and_changed_case_are_rejected(self):
        state = historical_result()
        for version in (2, True, None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                summarize_legacy_result({**state, "schema_version": version})
        state["case"]["input"] = "changed historical task"
        with self.assertRaisesRegex(ValueError, "identity"):
            summarize_legacy_result(state)


if __name__ == "__main__":
    unittest.main()
