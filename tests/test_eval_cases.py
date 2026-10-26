"""Pure Case validation and real local library files; no generated execution claims."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from hyperknow.eval_cases import (case_hash, classify_result, collect_sample, load_case,
                                 grading_budget, prepare_case, read_json, validate_case, write_json)


CASE = Path(__file__).resolve().parents[1] / "evals/concept-explanation/case.json"


class EvalCaseTests(unittest.TestCase):
    def test_seed_and_stable_hash(self):
        case = load_case(CASE)
        self.assertNotIn("skill_hint", case)
        self.assertEqual(len(case["rubric"]), 3)
        self.assertEqual(case_hash(case), case_hash(dict(reversed(list(case.items())))))

    def test_rejects_duplicate_rubric_and_unknown_fields(self):
        case = load_case(CASE)
        case["rubric"].append(deepcopy(case["rubric"][0]))
        with self.assertRaises(ValueError):
            validate_case(case)
        case = load_case(CASE)
        case["skill_hint"] = "concept-explanation"
        with self.assertRaises(ValueError):
            validate_case(case)
        case = load_case(CASE)
        case["expected_answer"] = "The observed output is not a golden answer"
        with self.assertRaises(ValueError):
            validate_case(case)

    def test_strict_json_and_atomic_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_json(path, {"text": "真实文件"})
            self.assertEqual(read_json(path), {"text": "真实文件"})
            for content in ('{"id":1,"id":2}', '{"value":NaN}'):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_json(path)

    def test_preparation_deduplicates_and_preserves_rubric(self):
        with tempfile.TemporaryDirectory() as directory:
            case = load_case(CASE)
            first = prepare_case(case, Path(directory))
            second = prepare_case(case, Path(directory))
            self.assertEqual(first, second)
            self.assertEqual(len(list(Path(directory).glob("*.json"))), 1)
            self.assertEqual(read_json(first)["case"], case)

    def sample_result(self, verdict="pass", attempt="grade-1"):
        case = load_case(CASE)
        return {"schema_version": 1, "execution_id": "execution-1", "case": case,
                "case_hash": case_hash(case), "evidence": {"run": {"run_id": "run-1"}},
                "final_response": {"text": "用于数据关联的输入值，不声称来自真实模型"},
                "rules": [{"id": key, "verdict": "pass", "reason": "test input"}
                          for key in ("delivery", "skill_trace", "no_artifacts", "no_questions", "trajectory")],
                "grades": [{"attempt_id": attempt, "status": "completed", "calibration_status": "unreviewed",
                            "results": [{"rubric_id": r["id"], "verdict": verdict,
                                         "reason": "pure classification input", "evidence_refs": ["final_response"]}
                                        for r in case["rubric"]]}]}

    def test_classification_does_not_turn_grader_error_into_bad_or_good(self):
        result = self.sample_result()
        self.assertEqual(classify_result(result), "good")
        result["grades"][-1]["status"] = "error"
        self.assertEqual(classify_result(result), "unresolved")
        result = self.sample_result("fail")
        self.assertEqual(classify_result(result), "bad")
        result["rules"][-1]["verdict"] = "fail"
        self.assertEqual(classify_result(result), "unresolved")
        result["rules"] = []
        self.assertEqual(classify_result(result), "unresolved")

    def test_budget_overrun_is_disclosed_and_cannot_produce_overall_good(self):
        result = self.sample_result()
        grade = result["grades"][-1]
        grade.update(config={"max_output_tokens": 2048}, usage={"completion_tokens": 6109})
        self.assertEqual(grading_budget(grade)["status"], "exceeded")
        self.assertEqual(classify_result(result), "unresolved")
        grade["results"][0]["verdict"] = "fail"
        self.assertEqual(classify_result(result), "bad")  # Preserve a known semantic failure, separately from the budget issue.
        grade["usage"] = None
        self.assertEqual(grading_budget(grade)["status"], "unknown")

    def test_runs_and_regrades_are_samples_not_new_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "cases"
            result_path = Path(directory) / "result.json"
            result = self.sample_result()
            write_json(result_path, result)
            path = collect_sample(result, library, result_path)
            collect_sample(result, library, result_path)
            self.assertEqual(len(read_json(path)["samples"]), 1)
            result["execution_id"] = "execution-2"
            result["grades"][0]["results"][0]["verdict"] = "fail"
            collect_sample(result, library, result_path)
            record = read_json(path)
            self.assertEqual([s["label"] for s in record["samples"]], ["good", "bad"])
            self.assertEqual(record["case"], load_case(CASE))
            self.assertEqual(record["usage"], "development")
            self.assertEqual(record["review_status"], "unreviewed")
            self.assertEqual(len(list(library.glob("*.json"))), 1)
            result["case_hash"] = "wrong"
            with self.assertRaises(ValueError):
                collect_sample(result, library, result_path)

    def test_first_grade_replaces_waiting_placeholder_but_preserves_explicit_regrades(self):
        with tempfile.TemporaryDirectory() as directory:
            library, source = Path(directory) / "cases", Path(directory) / "result.json"
            waiting = self.sample_result()
            waiting["grades"] = []
            path = collect_sample(waiting, library, source)
            self.assertEqual(read_json(path)["samples"][0]["label"], "unresolved")
            first = self.sample_result()
            collect_sample(first, library, source)
            self.assertEqual(len(read_json(path)["samples"]), 1)
            regrade = self.sample_result(attempt="grade-2")
            collect_sample(regrade, library, source)
            self.assertEqual(len(read_json(path)["samples"]), 2)


if __name__ == "__main__":
    unittest.main()
