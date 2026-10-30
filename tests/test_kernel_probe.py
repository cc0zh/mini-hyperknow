"""Probe mechanics only: never substitute these checks for model or teaching evidence."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "kernel_probe", Path(__file__).resolve().parents[1] / "scripts" / "probe_teaching_judgment.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class KernelProbeTests(unittest.TestCase):
    def test_all_arms_receive_identical_raw_evidence_and_instructions(self):
        for case in probe.load_cases():
            requests = [probe.request_for(case, arm, "explicit-model", None) for arm in probe.ARMS]
            self.assertEqual(len({row["messages"][0]["content"] for row in requests}), 1)
            for row in requests:
                public = probe.strict_json(row["messages"][1]["content"])
                self.assertEqual(public["evidence"], case["evidence"])
                self.assertEqual(public["lesson"], case["lesson"])
                self.assertNotIn("review_questions", public)
                self.assertEqual(row["max_completion_tokens"], 768)

    def test_matrix_is_complete_reproducible_and_initially_not_run(self):
        cases = probe.load_cases()
        matrix = probe.build_matrix(cases, "explicit-model", "https://api.deepseek.com", 3)
        self.assertEqual(matrix, probe.build_matrix(cases, "explicit-model", "https://api.deepseek.com", 3))
        self.assertEqual(len(matrix), 18)
        self.assertEqual(len({row["id"] for row in matrix}), 18)
        self.assertTrue(all(row["status"] == "not_run" and row["usage"] is None for row in matrix))
        self.assertTrue(all(row["request"]["max_tokens"] == 768 for row in matrix))
        self.assertEqual({row["arm"] for row in matrix}, set(probe.ARMS))
        higher = probe.build_matrix(cases, "explicit-model", None, 3, 1536)
        self.assertTrue(all(row["request"]["max_completion_tokens"] == 1536 for row in higher))
        self.assertEqual([row["id"] for row in higher], [row["id"] for row in matrix])

    def test_duplicate_keys_nonfinite_and_missing_citations_are_rejected(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                probe.strict_json(text)
        case = probe.load_cases()[0]
        decision = {"judgment": "not a teaching score", "evidence_ids": ["MISSING"],
                    "uncertainties": [], "next_action": "observe", "would_change_judgment_if": "new evidence"}
        with self.assertRaises(ValueError):
            probe.validate_decision(json.dumps(decision), case)
        decision["evidence_ids"] = ["E1"]
        self.assertEqual(probe.validate_decision(json.dumps(decision), case), decision)
        decision["unapproved"] = "extra"
        with self.assertRaises(ValueError):
            probe.validate_decision(json.dumps(decision), case)

    def test_output_must_be_new_and_inside_explicit_probe_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve() / "probe"
            target = base / "new-run"
            self.assertEqual(probe.new_directory(target, base), target)
            with self.assertRaises(FileExistsError):
                probe.new_directory(target, base)
            with self.assertRaises(ValueError):
                probe.new_directory(base.parent / "outside", base)
            with self.assertRaises(ValueError):
                probe.new_directory(base, base)

    def test_authored_negative_controls_are_not_hidden_student_facts(self):
        cases = probe.load_cases()
        stale = next(case for case in cases if case["id"] == "fraction_stale_note")
        self.assertEqual(stale["note_as_of"], "E1")
        self.assertEqual(len(stale["evidence"]), 2)
        false = next(case for case in cases if case["id"] == "units_false_note")
        self.assertIn("2.3", false["evidence"][0]["text"])
        self.assertIn("直接相加", false["summary"])

    def test_report_escapes_model_content_and_does_not_claim_teaching_success(self):
        cases = deepcopy(probe.load_cases())
        matrix = probe.build_matrix(cases, "explicit-model", None, 1)
        matrix[0]["raw"] = "<script>alert(1)</script>"
        manifest = {"cases": cases, "matrix": matrix, "model": "explicit-model", "seed": 1, "status": "planned"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.html"
            probe.render_report(path, manifest)
            rendered = path.read_text(encoding="utf-8")
            self.assertNotIn("<script>", rendered)
            self.assertIn("&lt;script&gt;", rendered)
            self.assertIn("没有自动教学总分", rendered)


if __name__ == "__main__":
    unittest.main()
