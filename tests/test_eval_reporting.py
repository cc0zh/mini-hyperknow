"""Offline reports use plain contracts, not a model or product-service substitute."""

from copy import deepcopy
import unittest

from eval_core.contracts import validate_case
from eval_core.grading import PROMPT_VERSION, evidence_set_hash, grading_definition_hash
from eval_core.reporting import (build_experiment, compare_results, report_experiment,
                                 summarize_trial)
from eval_core.store import digest


def case_record(case_id="case-1"):
    return validate_case({"schema_version": 2, "id": case_id, "version": "1", "title": "Saved facts",
                          "tags": ["engineering"], "task": {"profile": "generic", "input": "public input"},
                          "prerequisites": {}, "steps": [], "capture": ["done", "later"],
                          "checks": [{"check_id": "saved", "version": "1", "kind": "rule", "evaluator": "saved-v1",
                                      "criterion": "Saved fact", "pass_when": "Valid", "fail_when": "Invalid",
                                      "evidence": ["done"], "required": True}], "reference_facts": []})


def frozen_evidence(data, checkpoint="done"):
    material = {"checkpoint_id": checkpoint, "data": data,
                "observation": {"state": "waiting", "actions": [], "checkpoints": [checkpoint], "resources": {}}}
    return {"evidence_id": digest(material), **material, "sha256": digest(data), "captured_at": "2026-10-27"}


def trial_record(case=None, subject=None, trial_id="trial-1", verdict="pass"):
    case = case_record() if case is None else validate_case(case)
    evidence = frozen_evidence({"saved": "real local JSON"})
    result = {"schema_version": 2, "trial_id": trial_id, "case": case, "case_hash": digest(case),
            "subject": {"assembly": "baseline"} if subject is None else subject,
            "environment": {"target": "local-files"}, "environment_policy": "isolated", "repetition": 1,
            "bindings": {}, "actions": [], "evidence": [evidence], "stage": "completed", "settled": True,
            "grades": [{"attempt_id": "attempt-1", "definition_hash": grading_definition_hash(case),
                        "prompt_version": PROMPT_VERSION, "config": None, "status": "completed", "error": None,
                        "results": [{"check_id": check["check_id"], "verdict": verdict,
                                     "reason": "Saved fact inspected", "evidence_refs": [evidence["evidence_id"]]}
                                    for check in case["checks"]],
                        "request": None, "usage": None, "budget_check": {"status": "not_requested"}}]}
    result["grades"][0]["evidence_set_hash"] = evidence_set_hash(result)
    return result


class TrialReportTests(unittest.TestCase):
    def test_pass_requires_complete_required_grades_and_settled_execution(self):
        result = trial_record()
        summary = summarize_trial(result)
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["business_status"], "passed")
        for mutate in (lambda r: r.update(settled=False), lambda r: r.update(stage="waiting"),
                       lambda r: r["grades"][-1]["results"].clear(),
                       lambda r: r["grades"][-1]["results"][0].update(verdict="undetermined"),
                       lambda r: r["grades"][-1].update(status="error", error={"type": "ParsingError"}),
                       lambda r: r["grades"][-1].update(budget_check={"status": "exceeded"}),
                       lambda r: r["grades"].clear()):
            changed = deepcopy(result)
            mutate(changed)
            self.assertFalse(summarize_trial(changed)["passed"])

    def test_business_failures_and_measurement_errors_are_not_conflated(self):
        failed = summarize_trial(trial_record(verdict="fail"))
        self.assertEqual(failed["business_failures"], ["saved"])
        self.assertEqual(failed["measurement_errors"], [])
        self.assertEqual(failed["status"], "failed")
        result = trial_record(verdict="undetermined")
        result["grades"][-1].update(status="error", error={"type": "ValueError"})
        measurement = summarize_trial(result)
        self.assertEqual(measurement["business_failures"], [])
        self.assertEqual(measurement["measurement_errors"][0]["type"], "grader_error")
        self.assertEqual(measurement["business_status"], "undetermined")

    def test_fixed_not_applicable_never_becomes_a_required_pass(self):
        case = case_record()
        case["checks"][0]["applicable_when"] = {"state": ["terminal"]}
        result = trial_record(case, verdict="not_applicable")
        self.assertFalse(summarize_trial(result)["passed"])
        case["checks"][0]["required"] = False
        case["checks"].append({**case["checks"][0], "check_id": "required", "required": True,
                               "applicable_when": {"state": ["waiting"]}})
        result = trial_record(case)
        result["grades"][-1]["results"][0]["verdict"] = "not_applicable"
        self.assertTrue(summarize_trial(result)["passed"])

    def test_bad_grade_identity_duplicates_and_corrupt_evidence_cannot_pass(self):
        changes = (lambda r: r["grades"][-1]["results"].append(deepcopy(r["grades"][-1]["results"][0])),
                   lambda r: r["grades"][-1]["results"][0].update(check_id="unknown"),
                   lambda r: r["grades"][-1]["results"][0].update(evidence_refs=["missing"]),
                   lambda r: r["grades"][-1]["results"][0].update(quote="invented quote"),
                   lambda r: r["evidence"][0]["data"].update(saved="changed"),
                   lambda r: r.update(case_hash="wrong"),
                   lambda r: r["grades"][-1].pop("definition_hash"))
        for change in changes:
            result = trial_record()
            change(result)
            summary = summarize_trial(result)
            self.assertFalse(summary["passed"])
            self.assertTrue(summary["measurement_errors"])

    def test_all_required_checkpoints_and_the_original_definition_must_match(self):
        case = case_record()
        case["checks"][0]["evidence"] = ["done", "later"]
        self.assertFalse(summarize_trial(trial_record(case))["passed"])
        result = trial_record()
        result["case"]["checks"][0]["version"] = "2"
        result["case_hash"] = digest(result["case"])
        summary = summarize_trial(result)
        self.assertFalse(summary["passed"])
        self.assertTrue(any(error["type"] == "grader_identity_error" for error in summary["measurement_errors"]))

    def test_latest_attempt_is_authoritative_but_historical_usage_is_retained(self):
        result = trial_record(verdict="fail")
        latest = deepcopy(result["grades"][0])
        latest["attempt_id"] = "new-explicit-attempt"
        latest["results"][0]["verdict"] = "pass"
        result["grades"][0].update(request={"saved": "input"}, usage={"prompt_tokens": 10, "completion_tokens": 2})
        latest.update(request={"saved": "new input"}, usage=None)
        result["grades"].append(latest)
        summary = summarize_trial(result)
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["attempt_id"], "new-explicit-attempt")
        self.assertEqual(summary["grading_usage"]["usage"]["prompt_tokens"], None)
        self.assertEqual(summary["grading_usage"]["known_usage"]["prompt_tokens"], 10)
        self.assertEqual(summary["grading_usage"]["unknown_usage_attempts"], 1)

    def test_business_call_usage_is_deduplicated_across_checkpoints_and_unknown_is_not_zero(self):
        result = trial_record()
        calls = [{"id": "call-a", "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}},
                 {"id": "call-b", "usage": None}]
        result["evidence"] = [frozen_evidence({"calls": calls}), frozen_evidence({"calls": calls}, "later")]
        result["grades"][-1]["results"][0]["evidence_refs"] = [result["evidence"][0]["evidence_id"]]
        usage = summarize_trial(result)["business_usage"]
        self.assertEqual(usage["calls"], 2)
        self.assertEqual(usage["known_usage"]["total_tokens"], 14)
        self.assertIsNone(usage["usage"]["total_tokens"])
        self.assertEqual(usage["unknown_usage_calls"], 1)
        result["evidence"][1] = frozen_evidence({"calls": [{"id": "call-a", "usage": {"total_tokens": 99}}]}, "later")
        usage = summarize_trial(result)["business_usage"]
        self.assertEqual(usage["conflicting_call_ids"], ["call-a"])
        self.assertIsNone(usage["known_usage"]["total_tokens"])

    def test_runner_budget_error_blocks_overall_pass_without_inventing_content_failure(self):
        result = trial_record()
        result.update(stage="blocked", error={"code": "model_call_limit", "message": "exhausted"})
        summary = summarize_trial(result)
        self.assertFalse(summary["passed"])
        self.assertTrue(summary["budget_exceeded"])
        self.assertEqual(summary["business_failures"], [])

    def test_measured_output_overrun_is_detected_even_without_a_precomputed_budget_flag(self):
        result = trial_record()
        result["grades"][-1].update(config={"max_output_tokens": 10}, usage={"completion_tokens": 11})
        summary = summarize_trial(result)
        self.assertFalse(summary["passed"])
        self.assertTrue(summary["budget_exceeded"])


class ComparisonTests(unittest.TestCase):
    def test_subject_changes_are_the_comparison_not_a_pairing_constraint(self):
        before = trial_record(subject={"assembly": "old"}, verdict="fail")
        after = trial_record(subject={"assembly": "new"}, trial_id="new-trial")
        comparison = compare_results([before], [after])
        self.assertEqual(len(comparison["pairs"]), 1)
        self.assertEqual(comparison["pairs"][0]["change"], "improved")
        self.assertEqual(comparison["unpaired"], [])

    def test_fixture_snapshot_not_alias_or_manifest_source_label_controls_pairing(self):
        case = case_record()
        case["prerequisites"] = {"resources": {"source": {"kind": "document"}}}
        before = trial_record(case)
        after = trial_record(case, subject={"assembly": "candidate"}, trial_id="new-trial")
        for result, source in ((before, "source-a"), (after, "source-b")):
            result["environment"].update(fixture_snapshot_sha256=digest({"same": "fixed facts"}),
                                         fixture_manifest_sha256=source)
        self.assertEqual(len(compare_results([before], [after])["pairs"]), 1)
        after["environment"]["fixture_snapshot_sha256"] = digest({"different": "facts"})
        comparison = compare_results([before], [after])
        self.assertEqual(comparison["pairs"], [])
        self.assertTrue(all("fixture_hash_mismatch" in row["reasons"] for row in comparison["unpaired"]))
        after["environment"].pop("fixture_snapshot_sha256")
        self.assertTrue(any("unknown_fixture_identity" in row["reasons"]
                            for row in compare_results([before], [after])["unpaired"]))

    def test_repetition_definition_case_and_environment_mismatches_have_reasons(self):
        before = trial_record()
        for field, value, expected in (("repetition", 2, "repetition_mismatch"),
                                       ("environment_policy", "different", "environment_policy_hash_mismatch")):
            after = trial_record(trial_id="other")
            after[field] = value
            comparison = compare_results([before], [after])
            self.assertEqual(comparison["pairs"], [])
            self.assertTrue(all(expected in row["reasons"] for row in comparison["unpaired"]))
        after = trial_record(trial_id="other")
        after["grades"][-1]["definition_hash"] = "new-grader-version"
        comparison = compare_results([before], [after])
        self.assertTrue(all("grading_definition_hash_mismatch" in row["reasons"] for row in comparison["unpaired"]))
        changed = case_record()
        changed["version"] = "2"
        comparison = compare_results([before], [trial_record(changed)])
        self.assertTrue(all("case_hash_mismatch" in row["reasons"] for row in comparison["unpaired"]))

    def test_failed_blocked_and_ambiguous_trials_are_never_filtered_out(self):
        left, right = [], []
        for repetition, stage in ((1, "completed"), (2, "failed"), (3, "blocked")):
            before, after = trial_record(trial_id=f"left-{repetition}"), trial_record(trial_id=f"right-{repetition}")
            for result in (before, after):
                result.update(stage=stage, repetition=repetition, settled=stage != "blocked")
            left.append(before)
            right.append(after)
        comparison = compare_results(left, right)
        self.assertEqual(len(comparison["pairs"]), 3)
        self.assertEqual(comparison["counts"]["baseline"], 3)
        self.assertEqual({row["baseline"]["stage"] for row in comparison["pairs"]}, {"completed", "failed", "blocked"})
        duplicate = compare_results([left[0], deepcopy(left[0])], [right[0]])
        self.assertEqual(duplicate["pairs"], [])
        self.assertEqual(len(duplicate["unpaired"]), 3)
        self.assertTrue(all("ambiguous_duplicate_pair" in row["reasons"] for row in duplicate["unpaired"]))

    def test_missing_counterpart_and_missing_grader_identity_are_explicit(self):
        result = trial_record()
        comparison = compare_results([result], [])
        self.assertEqual(comparison["unpaired"][0]["reasons"], ["missing_counterpart"])
        result["grades"] = []
        comparison = compare_results([result], [trial_record(trial_id="other")])
        self.assertTrue(any("missing_grading_definition" in row["reasons"] for row in comparison["unpaired"]))


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.benchmark = {"id": "fixed-benchmark", "version": "1", "cases": [case_record(), case_record("case-2")]}
        self.subjects = [{"assembly": "baseline"}, {"assembly": "candidate"}]

    def for_plan(self, planned):
        result = trial_record(planned["case"], subject=planned["subject"], trial_id=planned["trial_id"])
        result.update(repetition=planned["repetition"], environment_policy=planned["environment_policy"])
        return result

    def test_matrix_is_fixed_complete_deterministic_and_does_not_mutate_inputs(self):
        source = deepcopy(self.benchmark)
        experiment = build_experiment(self.benchmark, self.subjects, 3)
        self.assertEqual(len(experiment["trials"]), 12)
        self.assertEqual(len({row["trial_id"] for row in experiment["trials"]}), 12)
        self.assertEqual(experiment, build_experiment(self.benchmark, self.subjects, 3))
        self.assertEqual(self.benchmark, source)
        experiment["trials"][0]["case"]["title"] = "changed output copy"
        self.assertEqual(self.benchmark, source)

    def test_all_missing_tasks_remain_pending_and_failed_blocked_results_remain_present(self):
        experiment = build_experiment(self.benchmark, self.subjects, 2)
        self.assertEqual(report_experiment(experiment, [])["counts"]["by_status"], {"pending": 8})
        failed, blocked = [self.for_plan(plan) for plan in experiment["trials"][:2]]
        failed["grades"][-1]["results"][0]["verdict"] = "fail"
        blocked.update(stage="blocked", settled=False, error={"code": "missing_fixture"})
        report = report_experiment(experiment, [failed, blocked])
        self.assertEqual(report["counts"]["planned"], 8)
        self.assertEqual(report["counts"]["by_status"], {"failed": 1, "blocked": 1, "pending": 6})
        self.assertEqual(report["invalid_results"], [])

    def test_wrong_result_identities_are_invalid_not_attributed_to_a_planned_trial(self):
        experiment = build_experiment(self.benchmark, self.subjects, 2)
        mutations = (lambda r: r.update(subject={"assembly": "unplanned"}), lambda r: r.update(repetition=2),
                     lambda r: r.update(case_hash="wrong"), lambda r: r.update(environment_policy="different"),
                     lambda r: r["grades"][-1].update(definition_hash="different"), lambda r: r.update(trial_id="foreign"))
        for mutate in mutations:
            result = self.for_plan(experiment["trials"][0])
            mutate(result)
            report = report_experiment(experiment, [result])
            self.assertEqual(report["counts"]["by_status"], {"pending": 8})
            self.assertEqual(len(report["invalid_results"]), 1)

    def test_explicit_binding_preserves_independent_trial_id_and_repetition(self):
        experiment = build_experiment(self.benchmark, self.subjects, 2)
        planned = experiment["trials"][1]
        result = self.for_plan(planned)
        result.pop("repetition")
        result.update(trial_id="independent-real-execution", experiment={"experiment_id": experiment["experiment_id"],
                      "planned_trial_id": planned["trial_id"], "repetition": 2})
        result["grades"][0]["evidence_set_hash"] = evidence_set_hash(result)
        report = report_experiment(experiment, [result])
        self.assertEqual(report["trials"][1]["status"], "passed")
        self.assertEqual(report["trials"][1]["summary"]["trial_id"], "independent-real-execution")
        result["repetition"] = 1
        self.assertEqual(len(report_experiment(experiment, [result])["invalid_results"]), 1)

    def test_duplicate_results_are_ambiguous_not_an_opportunity_to_pick_success(self):
        experiment = build_experiment(self.benchmark, self.subjects, 1)
        result = self.for_plan(experiment["trials"][0])
        duplicate = deepcopy(result)
        duplicate["grades"][-1]["results"][0]["verdict"] = "fail"
        report = report_experiment(experiment, [result, duplicate])
        self.assertEqual(report["counts"]["by_status"], {"pending": 4})
        self.assertEqual(len(report["invalid_results"]), 2)

    def test_invalid_matrix_parameters_and_unfixed_hashes_are_rejected(self):
        for repetitions in (0, -1, True, 1.5):
            with self.subTest(repetitions=repetitions), self.assertRaises(ValueError):
                build_experiment(self.benchmark, self.subjects, repetitions)
        for subjects in ([], [{}], self.subjects[:1] * 2):
            with self.assertRaises(ValueError):
                build_experiment(self.benchmark, subjects, 1)
        benchmark = {**self.benchmark, "cases": [{"case": case_record(), "case_hash": "wrong"}]}
        with self.assertRaises(ValueError):
            build_experiment(benchmark, self.subjects, 1)
        with self.assertRaises(ValueError):
            build_experiment({**self.benchmark, "grading_config": {"api_key": "must-not-persist"}}, self.subjects, 1)


if __name__ == "__main__":
    unittest.main()
