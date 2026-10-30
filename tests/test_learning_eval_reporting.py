"""Pure report-contract tests and real append-only HTML files, not model evaluations."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from hyperknow_eval.judging import JUDGE_VERSION, judge_definition_hash, public_settings, student_definition_hash
from hyperknow_eval.reporting import DISCLAIMER, aggregate, compare, summarize, write_report
from hyperknow_eval.storage import add_evidence, digest, evidence_hash, new_trial
from test_learning_eval_judging import learning_case, payload, settings


def report_record(output: Path, *, repetition=1, subject="unknown", simulated=False) -> dict:
    config = {"judge": public_settings(settings()), "repetition": repetition,
              "interaction_mode": "simulated" if simulated else "scripted"}
    record = new_trial(output, learning_case(simulated=simulated), config=config)
    if simulated:
        record["config"]["student"] = public_settings(settings(model="student-model"))
        record["config"]["student_definition_hash"] = student_definition_hash(record, record["config"]["student"])
    record["subject"] = {"identity": subject}
    record["status"] = "completed"
    add_evidence(record, "output", "Light supplies energy. A helpful analogy.", {})
    return record


def append_protocol_judgment(record: dict, *, verdict="met", model="judge-snapshot") -> dict:
    """Construct contract input for pure report validation; never execute a provider."""
    content = payload(record["case"], record["evidence"][0]["id"], "Light supplies energy", verdict)
    usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    attempt = {"attempt_id": "protocol-only", "role": "judge", "status": "completed",
               "config": deepcopy(record["config"]["judge"]), "prompt_version": JUDGE_VERSION,
               "definition_hash": judge_definition_hash(record["case"], record["config"]["judge"]),
               "evidence_hash": evidence_hash(record), "results": json.loads(content)["criteria"],
               "model": model, "usage": usage, "error": None,
               "raw_response": {"model": model, "usage": usage, "choices": [
                   {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}}
    record["judgments"].append(attempt)
    return attempt


class SummaryTests(unittest.TestCase):
    def test_execution_engineering_and_teaching_are_separate_no_empty_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            record = report_record(Path(directory) / "trial")
            result = summarize(record)
            self.assertEqual(result["execution"]["status"], "completed")
            self.assertEqual(result["engineering"]["status"], "insufficient")
            self.assertEqual(result["teaching"]["status"], "insufficient")
            self.assertEqual(result["teaching"]["dimensions"]["correctness"],
                             {"met": 0, "not_met": 0, "insufficient": 1, "total": 1})
            self.assertEqual(result["teaching"]["dimensions"]["grounding"]["total"], 0)
            self.assertEqual(result["calibration_status"], "unreviewed")
            self.assertIn("真人学习收益", result["disclaimer"])
            self.assertIsNone(result["usage"]["judge"]["usage"]["total_tokens"])

    def test_critical_not_met_vetoes_even_if_another_criterion_is_insufficient(self):
        with tempfile.TemporaryDirectory() as directory:
            record = report_record(Path(directory) / "trial")
            attempt = append_protocol_judgment(record, verdict="not_met")
            attempt["results"][1].update(verdict="insufficient", evidence_id="", quote="")
            attempt["raw_response"]["choices"][0]["message"]["content"] = json.dumps({"criteria": attempt["results"]})
            result = summarize(record)
            self.assertEqual(result["teaching"]["status"], "not_met")
            self.assertTrue(result["teaching"]["critical_veto"])
            self.assertEqual(result["teaching"]["critical_not_met"], ["facts"])
            self.assertEqual(result["teaching"]["dimensions"]["pedagogy"]["insufficient"], 1)

    def test_stale_missing_or_modified_judgment_never_reuses_old_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            original = report_record(Path(directory) / "trial")
            append_protocol_judgment(original)
            self.assertEqual(summarize(original)["teaching"]["status"], "met")
            variants = []
            for field, value in (("evidence_hash", "old"), ("definition_hash", "old"),
                                 ("prompt_version", "old-prompt"), ("model", "other-actual"),
                                 ("raw_response", None), ("results", [])):
                record = deepcopy(original)
                record["judgments"][-1][field] = value
                variants.append(record)
            changed = deepcopy(original)
            add_evidence(changed, "output", "a later observation", {})
            variants.append(changed)
            changed = deepcopy(original)
            changed["judgments"][-1]["config"]["model"] = "new-requested-model"
            variants.append(changed)
            changed = deepcopy(original)
            changed["judgments"].append({**deepcopy(changed["judgments"][0]), "status": "error",
                                          "error": {"type": "TransportError"}})
            variants.append(changed)
            for record in variants:
                with self.subTest(record=record):
                    result = summarize(record)
                    self.assertEqual(result["teaching"]["status"], "insufficient")
                    self.assertEqual(result["teaching"]["dimensions"]["correctness"]["total"], 1)
                    self.assertEqual(result["teaching"]["dimensions"]["correctness"]["met"], 0)

    def test_actual_output_overrun_is_error_not_agent_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            record = report_record(Path(directory) / "trial")
            attempt = append_protocol_judgment(record)
            attempt["usage"]["completion_tokens"] = attempt["config"]["max_output_tokens"] + 1
            attempt["raw_response"]["usage"] = attempt["usage"]
            result = summarize(record)
            self.assertEqual(result["execution"]["status"], "completed")
            self.assertEqual(result["teaching"]["status"], "insufficient")
            self.assertEqual(len(result["output_budget_violations"]), 1)
            self.assertEqual(result["judgment"]["status"], "invalid_or_stale")

    def test_engineering_checks_do_not_imply_teaching_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            record = report_record(Path(directory) / "trial")
            record["checks"] = [{"id": "saved", "passed": True}, {"id": "shape", "verdict": "met"}]
            result = summarize(record)
            self.assertEqual(result["engineering"]["status"], "met")
            self.assertEqual(result["teaching"]["status"], "insufficient")
            record["checks"].append({"id": "incomplete", "passed": None})
            self.assertEqual(summarize(record)["engineering"]["status"], "insufficient")
            record["checks"].append({"id": "save-failed", "passed": False})
            self.assertEqual(summarize(record)["engineering"]["status"], "not_met")

    def test_business_usage_latest_run_snapshot_deduplicates_references_and_unknowns(self):
        with tempfile.TemporaryDirectory() as directory:
            record = report_record(Path(directory) / "trial")
            record["business_runs"] = ["run-a", "run-b"]
            measured = {"call_index": 0, "model": "business-model", "provider": "provider",
                        "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}}
            unknown = {"call_index": 1, "model": "business-model", "usage": None}
            add_evidence(record, "model_calls", [measured], {"run_id": "run-a"})
            add_evidence(record, "model_calls", [measured, measured, unknown], {"run_id": "run-a"})
            add_evidence(record, "model_calls", [], {"run_id": "run-b"})
            record["model_requests"] = [{"role": "business", "run_id": "run-a", "call_id": "a",
                                         "usage": measured["usage"]}]
            result = summarize(record)["usage"]["business"]
            self.assertEqual(result["observed_calls"], 2)
            self.assertEqual(result["unknown_usage_calls"], 1)
            self.assertEqual(result["known_usage"]["total_tokens"], 10)
            self.assertIsNone(result["usage"]["total_tokens"])
            self.assertEqual(result["missing_inventory_runs"], [])

    def test_usage_counts_judge_errors_and_missing_business_inventory_not_as_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            record = report_record(Path(directory) / "trial")
            append_protocol_judgment(record)
            record["judgments"].append({"role": "judge", "status": "error", "sent_at": "2026-10-29",
                                         "usage": None, "raw_response": None})
            record["business_runs"] = ["missing-run"]
            result = summarize(record)
            self.assertEqual(result["usage"]["judge"]["observed_calls"], 2)
            self.assertIsNone(result["usage"]["judge"]["usage"]["total_tokens"])
            self.assertEqual(result["usage"]["judge"]["known_usage"]["total_tokens"], 30)
            self.assertEqual(result["usage"]["business"]["missing_inventory_runs"], ["missing-run"])
            self.assertIsNone(result["usage"]["business"]["usage"]["total_tokens"])

    def test_aggregate_keeps_failed_trials_coverage_and_all_criterion_denominators(self):
        with tempfile.TemporaryDirectory() as directory:
            first = report_record(Path(directory) / "first")
            append_protocol_judgment(first)
            second = report_record(Path(directory) / "second")
            second["status"] = "failed"
            second["error"] = {"type": "BusinessFailure"}
            result = aggregate([first, second])
            self.assertEqual(result["trials"], 2)
            self.assertEqual(result["execution"], {"completed": 1, "failed": 1})
            self.assertEqual(result["coverage"]["domain"], {"biology": 2})
            self.assertEqual(result["teaching"]["dimensions"]["correctness"],
                             {"met": 1, "not_met": 0, "insufficient": 1, "total": 2})
            self.assertEqual(aggregate([])["teaching"]["statuses"], {})


class ComparisonTests(unittest.TestCase):
    def test_failed_and_unjudged_trials_are_compared_without_success_only_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            first = report_record(Path(directory) / "baseline", subject="baseline-source")
            second = report_record(Path(directory) / "candidate", subject="candidate-source")
            first["status"] = "failed"
            append_protocol_judgment(second)
            result = compare([first], [second])
            self.assertEqual(result["paired_trials"], 1)
            self.assertEqual(result["baseline"]["execution"], {"failed": 1})
            self.assertEqual(result["criterion_transitions"]["correctness"], {"insufficient -> met": 1})
            self.assertEqual(len(result["pairs"]), 1)

    def test_rejects_missing_duplicate_or_changed_configuration_and_same_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            first = report_record(Path(directory) / "baseline", subject="source-a")
            second = report_record(Path(directory) / "candidate", subject="source-b")
            for baseline, candidate in (([], [second]), ([first], []), ([first, first], [second]),
                                        ([first], [second, deepcopy(second)])):
                with self.assertRaises(ValueError):
                    compare(baseline, candidate)
            for change in ("case", "config", "trial_id", "repetition"):
                altered = deepcopy(second)
                if change == "case":
                    altered["case"]["reference"]["facts"].append("changed private fact")
                    altered["case_hash"] = digest(altered["case"])
                elif change == "config":
                    altered["config"]["judge"]["max_output_tokens"] += 1
                elif change == "trial_id":
                    altered["trial_id"] = first["trial_id"]
                    for evidence in altered["evidence"]:
                        evidence["trial_id"] = altered["trial_id"]
                else:
                    altered["config"]["repetition"] = 2
                with self.subTest(change=change), self.assertRaises(ValueError):
                    compare([first], [altered])

    def test_unknown_subject_allows_comparison_but_no_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            first = report_record(Path(directory) / "baseline")
            second = report_record(Path(directory) / "candidate")
            result = compare([first], [second])
            self.assertTrue(any("unknown attribution" in warning for warning in result["warnings"]))

    def test_same_known_source_negative_control_is_allowed_and_model_difference_disclosed(self):
        with tempfile.TemporaryDirectory() as directory:
            first = report_record(Path(directory) / "baseline", subject="same-source")
            second = report_record(Path(directory) / "candidate", subject="same-source")
            first["subject"]["model"] = "business-a"
            second["subject"]["model"] = "business-b"
            result = compare([first], [second])
            self.assertEqual(result["paired_trials"], 1)
            self.assertTrue(any("negative control" in warning for warning in result["warnings"]))
            self.assertTrue(any("subject model differs" in warning for warning in result["warnings"]))

    def test_explicit_rejudge_uses_latest_configuration_without_rewriting_initial_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            first = report_record(Path(directory) / "baseline")
            second = report_record(Path(directory) / "candidate")
            original_plan = deepcopy(first["config"]["judge"])
            for record in (first, second):
                attempt = append_protocol_judgment(record)
                attempt["config"]["context_budget"] += 1000
                attempt["definition_hash"] = judge_definition_hash(record["case"], attempt["config"])
            self.assertEqual(summarize(first)["teaching"]["status"], "met")
            self.assertTrue(summarize(first)["judgment"]["differs_from_planned"])
            self.assertEqual(first["config"]["judge"], original_plan)
            self.assertEqual(compare([first], [second])["paired_trials"], 1)
            second["judgments"][-1]["config"]["context_budget"] += 1
            second["judgments"][-1]["definition_hash"] = judge_definition_hash(
                second["case"], second["judgments"][-1]["config"])
            with self.assertRaises(ValueError):
                compare([first], [second])

    def test_repetitions_pair_by_explicit_index_not_list_order(self):
        with tempfile.TemporaryDirectory() as directory:
            first = [report_record(Path(directory) / f"b-{i}", repetition=i) for i in (1, 2)]
            second = [report_record(Path(directory) / f"c-{i}", repetition=i) for i in (2, 1)]
            self.assertEqual(compare(first, second)["paired_trials"], 2)
            second[0]["config"]["repetition"] = 1
            with self.assertRaises(ValueError):
                compare(first, second)

    def test_actual_judge_model_change_and_stale_criteria_are_incomparable(self):
        with tempfile.TemporaryDirectory() as directory:
            first = report_record(Path(directory) / "baseline")
            second = report_record(Path(directory) / "candidate")
            append_protocol_judgment(first, model="resolved-a")
            append_protocol_judgment(second, model="resolved-b")
            with self.assertRaisesRegex(ValueError, "actual judge model"):
                compare([first], [second])
            second["judgments"][-1]["model"] = "resolved-a"
            second["judgments"][-1]["raw_response"]["model"] = "resolved-a"
            second["judgments"][-1]["results"].pop()
            with self.assertRaisesRegex(ValueError, "stale or invalid"):
                compare([first], [second])

    def test_student_definition_change_cannot_be_silently_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            first = report_record(Path(directory) / "baseline", simulated=True)
            second = report_record(Path(directory) / "candidate", simulated=True)
            self.assertEqual(compare([first], [second])["paired_trials"], 1)
            second["config"]["student"]["model"] = "changed-student"
            with self.assertRaises(ValueError):
                compare([first], [second])


class OfflineHtmlTests(unittest.TestCase):
    def test_offline_report_escapes_all_content_and_never_overwrites_existing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = report_record(root / "trial")
            malicious = '<script src="https://remote.invalid/a.js">alert(1)</script><img onerror="alert(2)">'
            record["transcript"].append({"role": "tutor", "text": malicious})
            add_evidence(record, "output", malicious, {})
            record["judgments"].append({"status": "error", "error": {"message": "raw protocol error " + malicious}})
            output = root / "report.html"
            write_report(output, [record])
            content = output.read_text(encoding="utf-8")
            self.assertNotIn("<script", content)
            self.assertNotIn("<img", content)
            self.assertIn("&lt;script", content)
            self.assertIn("Content-Security-Policy", content)
            self.assertIn("default-src &apos;none&apos;", content)
            self.assertIn("PRIVATE: light supplies energy", content)
            self.assertIn("raw protocol error", content)
            self.assertIn(DISCLAIMER, content)
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                write_report(output, [record])
            self.assertEqual(before, output.read_bytes())
            with self.assertRaises(ValueError):
                write_report(root / "report.json", [record])

    def test_old_records_are_rejected_without_automatic_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                write_report(Path(directory) / "old.html", [{"schema_version": 2}])
            self.assertFalse((Path(directory) / "old.html").exists())


if __name__ == "__main__":
    unittest.main()
