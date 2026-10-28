"""Real local HTTP/SQLite and offline grading regressions; no model worker starts."""

from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest

from eval_core.contracts import public_case, validate_case
from eval_core.grading import evidence_view, grade_trial
from eval_core.reporting import summarize_trial
from eval_core.runner import _matches, execute_trial
from eval_core.store import digest, read_json, write_json
from hyperknow.eval_checks import RULES
from tests import test_eval_adapter as adapter_tests
from tests.test_eval_reporting import case_record, frozen_evidence, trial_record


ROOT = Path(__file__).resolve().parents[1]


class CatalogExecutionTests(unittest.TestCase):
    def test_every_checked_in_case_has_a_reachable_initial_action(self):
        paths = sorted((ROOT / "evals/general").glob("*/case.json"))
        self.assertEqual(len(paths), 14)
        for path in paths:
            with self.subTest(case=path.parent.name):
                harness = adapter_tests.AdapterTests()
                harness.setUp()
                try:
                    case = validate_case(read_json(path))
                    if case["prerequisites"].get("resources"):
                        harness.fixture_course(lesson=case["id"] in {"classroom-question", "quiz-practice"})
                    bindings = harness.adapter.prepare(public_case(case))
                    observation = harness.adapter.observe(bindings)
                    step = case["steps"][0]
                    self.assertIn(step["action"], observation["actions"])
                    self.assertTrue(_matches(step["when"], observation), observation["state"])
                    request = harness.adapter.build_action(step, observation, bindings, harness.command())
                    committed = harness.adapter.act(request)
                    self.assertEqual(harness.adapter.recover(request), committed)
                    self.assertEqual(len(committed["executions"]), 1)
                finally:
                    harness.tearDown()

    def test_zero_call_budget_cannot_enqueue_business_work(self):
        harness = adapter_tests.AdapterTests()
        harness.setUp()
        try:
            case = validate_case(read_json(ROOT / "evals/general/concept-chain-rule/case.json"))
            # Isolate the budget regression from the separately tested catalog condition.
            case["steps"][0]["when"]["state"] = ["preparing"]
            case["limits"].update(max_model_calls=0, wait_seconds=0.5, poll_seconds=0.01)
            result = execute_trial(case, harness.adapter, harness.directory / "trial", execute=True)
            self.assertEqual(result["error"]["code"], "model_call_limit")
            self.assertEqual(harness.db.list_records("runs"), [])
        finally:
            harness.tearDown()

    def test_observe_counts_saved_calls_without_claiming_complete_provider_coverage(self):
        harness = adapter_tests.AdapterTests()
        harness.setUp()
        try:
            bindings = harness.conversation()
            bindings, _ = harness.execute(bindings, "assistance.message", {"text": "工程输入"})
            run_id = bindings["run_ids"][-1]
            # These are persistence contract inputs, not model outputs or paid-call evidence.
            for index in range(2):
                harness.db.record_call(run_id, {"engineering_record": index})
            observed = harness.adapter.observe(bindings)
            self.assertEqual(observed["model_calls"], 2)
            self.assertEqual(observed["model_calls_coverage"], "saved_calls_only")
        finally:
            harness.tearDown()

    def test_final_checkpoint_checks_overrun_but_allows_exact_call_limit(self):
        for call_count, expected_stage in ((1, "completed"), (2, "blocked")):
            with self.subTest(call_count=call_count):
                harness = adapter_tests.AdapterTests()
                harness.setUp()
                stop, errors = threading.Event(), []

                def commit_schema_input():
                    try:
                        while not stop.is_set():
                            for run in harness.db.list_records("runs"):
                                if run["status"] == "queued":
                                    for index in range(call_count):
                                        harness.db.record_call(run["run_id"], {"engineering_record": index})
                                    harness.finish_turn({"run_ids": [run["run_id"]]})
                                    return
                            stop.wait(0.01)
                    except Exception as exc:
                        errors.append(exc)

                committer = threading.Thread(target=commit_schema_input)
                committer.start()
                try:
                    case = validate_case(read_json(ROOT / "evals/general/concept-chain-rule/case.json"))
                    case["limits"].update(max_model_calls=1, wait_seconds=5, poll_seconds=0.01)
                    result = execute_trial(case, harness.adapter, harness.directory / "trial", execute=True)
                    self.assertEqual(result["stage"], expected_stage, result.get("error"))
                    self.assertEqual(result["budget"]["last_reported_model_calls"], call_count)
                    if call_count > 1:
                        self.assertEqual(result["error"]["code"], "model_call_limit")
                finally:
                    stop.set()
                    committer.join(timeout=3)
                    harness.tearDown()
                self.assertFalse(committer.is_alive())
                self.assertEqual(errors, [])


class GradingReliabilityTests(unittest.TestCase):
    def rule_trial(self):
        case = case_record()
        case["checks"][0]["evaluator"] = "no_artifacts"
        result = trial_record(validate_case(case))
        result["grades"] = []
        result["evidence"] = [frozen_evidence({"turns": [{"turn_id": "first", "artifacts": []}]})]
        return result

    def test_new_evidence_invalidates_old_grade_without_implicit_regrading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_json(path, self.rule_trial())
            initial = grade_trial(path, rules=RULES)
            self.assertTrue(summarize_trial(initial)["passed"])
            original_attempt = deepcopy(initial["grades"][0])
            initial["evidence"].append(frozen_evidence(
                {"turns": [{"turn_id": "second", "artifacts": [{"kind": "quiz"}]}]}))
            write_json(path, initial)
            resumed = grade_trial(path, rules=RULES)
            self.assertEqual(resumed["grades"], [original_attempt])
            summary = summarize_trial(resumed)
            self.assertFalse(summary["passed"])
            self.assertTrue(any(error["type"] == "stale_grading" for error in summary["measurement_errors"]))
            regraded = grade_trial(path, rules=RULES, regrade=True)
            self.assertEqual(regraded["grades"][0], original_attempt)
            self.assertEqual(regraded["grades"][-1]["results"][0]["verdict"], "fail")

    def test_unbound_legacy_v2_grade_is_not_silently_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_json(path, self.rule_trial())
            result = grade_trial(path, rules=RULES)
            result["grades"][0].pop("evidence_set_hash", None)
            summary = summarize_trial(result)
            self.assertFalse(summary["passed"])
            self.assertTrue(any(error["type"] == "stale_grading" for error in summary["measurement_errors"]))

    def test_unknown_request_is_preserved_when_new_evidence_arrives(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_json(path, self.rule_trial())
            result = grade_trial(path, rules=RULES)
            result["grades"][0].update(status="in_flight", raw_response={"content": "not reinterpreted"},
                                       model_check_ids=[result["case"]["checks"][0]["check_id"]])
            original = deepcopy(result["grades"])
            result["evidence"].append(frozen_evidence({"new": "actual additional snapshot"}))
            write_json(path, result)
            resumed = grade_trial(path, rules=RULES)
            self.assertEqual(resumed["grades"], original)
            self.assertFalse(summarize_trial(resumed)["passed"])

    def test_report_uses_frozen_calls_when_trial_budget_observation_is_absent(self):
        result = self.rule_trial()
        result["case"]["limits"]["max_model_calls"] = 1
        result["case_hash"] = digest(result["case"])
        result["evidence"] = [frozen_evidence({"turns": [{"turn_id": "first", "artifacts": []}],
                                              "calls": [{"id": "one"}, {"id": "two"}]})]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_json(path, result)
            summary = summarize_trial(grade_trial(path, rules=RULES))
            self.assertTrue(summary["budget_exceeded"])
            self.assertFalse(summary["passed"])

    def test_corrupt_observation_or_checkpoint_cannot_reach_grading_or_pass_report(self):
        mutations = (lambda item: item["observation"].update(state="terminal", outcome="failed"),
                     lambda item: item.update(checkpoint_id="later"))
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "result.json"
                write_json(path, self.rule_trial())
                result = grade_trial(path, rules=RULES)
                mutate(result["evidence"][0])
                with self.assertRaises(ValueError):
                    evidence_view(result)
                write_json(path, result)
                with self.assertRaises(ValueError):
                    grade_trial(path, rules=RULES, regrade=True)
                self.assertFalse(summarize_trial(result)["passed"])

    def test_report_checks_known_trial_limits_without_a_precomputed_flag(self):
        mutations = (
            lambda result: result.update(budget={"last_reported_model_calls": 33}),
            lambda result: result.update(budget={"model_calls": 33}),
            lambda result: result.update(budget={"elapsed_seconds": 421}),
            lambda result: result.update(actions=[{"status": "committed"}] * 33),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "result.json"
                write_json(path, self.rule_trial())
                result = grade_trial(path, rules=RULES)
                mutate(result)
                summary = summarize_trial(result)
                self.assertTrue(summary["budget_exceeded"])
                self.assertFalse(summary["passed"])
                self.assertEqual(summary["business_failures"], [])


if __name__ == "__main__":
    unittest.main()
