"""Deterministic file/contract checks, not generated teaching or calibrated grades."""

import base64
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from eval_core.html_report import comparison_bundle, render_html, report_bundle, write_html
from eval_core.reporting import build_experiment, report_experiment, summarize_trial
from eval_core.store import digest, read_json, write_json
from hyperknow.eval_cli import main
from test_eval_reporting import case_record, frozen_evidence, trial_record


ROOT = Path(__file__).resolve().parents[1]


def embedded_bundle(content):
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>',
                      content, flags=re.DOTALL)
    return json.loads(match.group(1))


class HtmlReportTests(unittest.TestCase):
    def setUp(self):
        self.review_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.review_temp.cleanup)

    def invoke(self, arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([*arguments, "--review-dir", self.review_temp.name])
        return code, json.loads(output.getvalue())

    def test_report_preserves_authoritative_verdicts_and_source(self):
        trial = trial_record()
        original = deepcopy(trial)
        bundle = report_bundle([trial])
        self.assertEqual(bundle["entries"][0]["summary"], summarize_trial(trial))
        self.assertEqual(bundle["report"]["scope"], "selected_results")
        self.assertEqual(bundle["report"]["counts"]["by_status"], {"passed": 1})
        self.assertTrue(bundle["entries"][0]["evidence"][0]["integrity"]["valid"])
        self.assertEqual(trial, original)
        bundle["entries"][0]["evidence"][0]["data"]["saved"] = "viewer copy only"
        self.assertEqual(trial, original)

    def test_pending_plan_has_readable_case_and_subject_without_fabricated_evidence(self):
        plan = build_experiment({"id": "html-engineering", "version": "1", "cases": [case_record()]},
                                [{"identity": "unknown", "label": "not-executed"}], 2)
        bundle = report_bundle([], plan)
        self.assertEqual(bundle["report"], report_experiment(plan, []))
        self.assertEqual(bundle["report"]["counts"]["by_status"], {"pending": 2})
        for entry in bundle["entries"]:
            self.assertEqual(entry["case"]["title"], "Saved facts")
            self.assertEqual(entry["subject"]["identity"], "unknown")
            self.assertEqual(entry["status"], "pending")
            self.assertIsNone(entry["summary"])
            self.assertEqual(entry["evidence"], [])

    def test_explicit_binding_resolves_actual_trial_without_guessing(self):
        case, subject = case_record(), {"identity": "unknown"}
        plan = build_experiment({"id": "html-binding", "version": "1", "cases": [case]}, [subject], 1)
        trial = trial_record(case, subject, "actual-trial")
        trial["experiment"] = {"experiment_id": plan["experiment_id"],
                               "planned_trial_id": plan["trials"][0]["trial_id"], "repetition": 1}
        bundle = report_bundle([trial], plan)
        self.assertEqual(len(bundle["entries"]), 1)
        self.assertEqual(bundle["entries"][0]["trial_id"], "actual-trial")
        self.assertEqual(bundle["entries"][0]["status"], "passed")

    def test_invalid_result_with_null_grades_still_exports_as_invalid_material(self):
        case, subject = case_record(), {"identity": "unknown"}
        plan = build_experiment({"id": "html-null-grades", "version": "1", "cases": [case]}, [subject], 1)
        trial = trial_record(case, {"identity": "wrong"}, plan["trials"][0]["trial_id"])
        trial["grades"] = None
        self.assertEqual(report_experiment(plan, [trial])["counts"]["invalid"], 1)
        bundle = report_bundle([trial], plan)
        self.assertEqual([entry["status"] for entry in bundle["entries"]], ["pending", "invalid"])
        self.assertEqual(bundle["entries"][1]["grades"][0]["error"]["type"], "invalid_grading_records")

    def test_invalid_or_duplicate_results_never_fill_a_planned_task(self):
        case, subject = case_record(), {"identity": "unknown"}
        plan = build_experiment({"id": "html-invalid", "version": "1", "cases": [case]}, [subject], 1)
        trial = trial_record(case, {"identity": "wrong"}, plan["trials"][0]["trial_id"])
        bundle = report_bundle([trial], plan)
        self.assertEqual([entry["status"] for entry in bundle["entries"]], ["pending", "invalid"])
        self.assertIn("subject_identity_mismatch", bundle["entries"][1]["reason"])
        self.assertIsNone(bundle["entries"][1]["summary"])
        self.assertNotIn("result", bundle["report"]["invalid_results"][0])
        trial["subject"] = subject
        bundle = report_bundle([trial, trial], plan)
        self.assertEqual([entry["status"] for entry in bundle["entries"]], ["pending", "invalid", "invalid"])
        self.assertEqual(bundle["report"]["counts"]["invalid"], 2)

    def test_invalid_identity_fields_do_not_break_other_planned_entries(self):
        case, subject = case_record(), {"identity": "unknown"}
        plan = build_experiment({"id": "html-invalid-shapes", "version": "1", "cases": [case]}, [subject], 1)
        trial = trial_record(case, subject, "unplanned")
        trial.update(trial_id=["not-a-string"], case=[], subject=[], actions=None, grades=None, evidence=None)
        bundle = report_bundle([trial], plan)
        self.assertEqual([entry["status"] for entry in bundle["entries"]], ["pending", "invalid"])
        entry = bundle["entries"][1]
        self.assertIsInstance(entry["trial_id"], str)
        self.assertIsNone(entry["case"])
        self.assertIsNone(entry["subject"])
        self.assertEqual(entry["actions"], [])
        self.assertEqual(entry["invalid_fields"]["trial_id"], ["not-a-string"])
        self.assertFalse(entry["evidence"][0]["integrity"]["valid"])

    def test_damaged_evidence_stale_grading_and_unknown_usage_remain_visible(self):
        damaged = trial_record()
        damaged["evidence"][0]["data"]["saved"] = "altered after freezing"
        entry = report_bundle([damaged])["entries"][0]
        self.assertFalse(entry["summary"]["passed"])
        self.assertFalse(entry["evidence"][0]["integrity"]["valid"])
        stale = trial_record()
        stale["evidence"].append(frozen_evidence({"later": "new facts"}, "later"))
        entry = report_bundle([stale])["entries"][0]
        self.assertFalse(entry["summary"]["grading_current"])
        self.assertFalse(entry["summary"]["passed"])
        self.assertIsNone(entry["summary"]["grading_usage"]["usage"]["total_tokens"])

    def test_comparison_retains_unpaired_and_both_sides(self):
        before = trial_record(verdict="fail")
        after = trial_record(subject={"assembly": "candidate"}, trial_id="new-trial")
        unpaired = trial_record(case=case_record("unpaired"), trial_id="extra-trial")
        bundle = comparison_bundle([before], [after, unpaired])
        self.assertEqual(bundle["report"]["counts"]["changes"], {"improved": 1})
        self.assertEqual(bundle["report"]["counts"]["unpaired"], 1)
        self.assertEqual([entry["side"] for entry in bundle["entries"]], ["baseline", "candidate", "candidate"])

    def test_grader_requests_and_raw_responses_are_not_duplicated_into_export(self):
        trial = trial_record()
        trial["grades"][0].update(request={"private-request": "do-not-copy"}, raw_response={"response": "do-not-copy"})
        entry = report_bundle([trial])["entries"][0]
        self.assertNotIn("request", entry["grades"][0])
        self.assertNotIn("raw_response", entry["grades"][0])
        self.assertEqual(entry["grades"][0]["attempt_id"], "attempt-1")

    def test_script_breakout_and_template_tokens_round_trip_only_as_data(self):
        trial = trial_record()
        attack = '</script><script>globalThis.injected=1</script><img src="https://invalid.test/" onerror="alert(1)">'
        trial["case"]["task"]["input"] = attack + " __EVAL_REPORT_CSP__ __EVAL_REPORT_DATA__ & \u2028\u2029"
        trial["case_hash"] = digest(trial["case"])
        bundle = report_bundle([trial])
        content = render_html(bundle)
        self.assertEqual(embedded_bundle(content), bundle)
        self.assertNotIn(attack, content)
        scripts = re.findall(r"<script>(.*?)</script>", content, flags=re.DOTALL)
        self.assertEqual(len(scripts), 1)
        expected = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
        self.assertIn("script-src 'sha256-" + expected + "'", content)
        self.assertIn("connect-src 'none'", content)
        self.assertIn("frame-src 'none'", content)
        self.assertIn("form-action 'none'", content)

        class Elements(HTMLParser):
            tags = []

            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))

        parser = Elements()
        parser.feed(content)
        self.assertNotIn("iframe", [tag for tag, _ in parser.tags])
        self.assertFalse(any(tag == "script" and "src" in attrs for tag, attrs in parser.tags))
        self.assertFalse(any(key.lower().startswith("on") for _, attrs in parser.tags for key in attrs))
        for forbidden in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "eval(", "fetch(", "XMLHttpRequest"):
            self.assertNotIn(forbidden, scripts[0])

    def test_export_refuses_non_html_overwrite_and_non_json_values(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.html"
            bundle = report_bundle([trial_record()])
            write_html(path, bundle)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_html(path, bundle)
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(ValueError):
                write_html(path.with_suffix(".json"), bundle)
            bundle["generated_at"] = float("nan")
            with self.assertRaises(ValueError):
                render_html(bundle)

    def test_reader_first_layout_retains_original_payload_and_technical_access(self):
        bundle = report_bundle([trial_record()])
        content = render_html(bundle)
        self.assertEqual(embedded_bundle(content), bundle)
        for label in ("先选一道题", "1. 用户问了什么", "2. AI 实际怎样回答", "3. 这次是怎么评分的",
                      "技术详情（原始证据、执行与评分记录）", "报告范围、隐私与评分限制", "看评分理由"):
            self.assertIn(label, content)
        self.assertLess(content.index('section(body, "1. 用户问了什么"'), content.index('section(body, "2. AI 实际怎样回答"'))
        self.assertLess(content.index('section(body, "2. AI 实际怎样回答"'), content.index('section(body, "3. 这次是怎么评分的"'))
        self.assertIn("revealEvidence", content)
        self.assertIn("还不能下结论", content)

    def test_report_and_compare_cli_keep_json_and_sources_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            left, right = root / "before.json", root / "after.json"
            write_json(left, trial_record(verdict="fail"))
            write_json(right, trial_record(subject={"assembly": "candidate"}, trial_id="new-trial"))
            before = {path: path.read_bytes() for path in (left, right)}
            for arguments, target in ((["report", "--result", str(left)], root / "review.html"),
                                      (["compare", "--baseline", str(left), "--candidate", str(right)], root / "compare.html")):
                code, original = self.invoke(arguments)
                self.assertEqual(code, 0)
                code, exported = self.invoke([*arguments, "--html", str(target)])
                self.assertEqual(code, 0)
                self.assertEqual(exported, original)
                self.assertEqual(embedded_bundle(target.read_text(encoding="utf-8"))["schema_version"], 1)
                self.assertEqual(self.invoke([*arguments, "--html", str(target)])[0], 2)
            for path, data in before.items():
                self.assertEqual(path.read_bytes(), data)
            self.assertEqual(self.invoke(["report", "--result", str(left), "--html",
                                         str(ROOT / "eval-report-must-not-be-created.html")])[0], 2)
            self.assertFalse((ROOT / "eval-report-must-not-be-created.html").exists())

    def test_experiment_cli_can_export_only_pending_tasks_without_business_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = build_experiment({"id": "html-offline", "version": "1", "cases": [case_record()]},
                                    [{"identity": "unknown"}], 1)
            write_json(root / "experiment.json", plan)
            code, report = self.invoke(["report", "--experiment", str(root / "experiment.json"),
                                        "--html", str(root / "pending.html")])
            self.assertEqual(code, 0)
            self.assertEqual(report["counts"]["by_status"], {"pending": 1})
            self.assertEqual(embedded_bundle((root / "pending.html").read_text(encoding="utf-8"))["entries"][0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
