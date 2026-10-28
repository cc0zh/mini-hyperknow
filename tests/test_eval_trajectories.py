"""Pure recorded-data transformation checks, not evidence of model execution."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from eval_core.store import digest, read_json, write_json
from hyperknow.eval_checks import RULES
from hyperknow.eval_trajectories import export_recorded_run, export_trial_trajectories


def call(identity, response, **updates):
    return {"id": identity, "run_id": "run-schema", "kind": "lesson", "phase": "generating",
            "attempt": 1, "system_prompt": "结构转换的纯数据输入，不是模型调用", "messages": ["请求内容"],
            "response": response, "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            "stop_reason": "stop", "model": "schema-model", **updates}


class TrajectoryTests(unittest.TestCase):
    def test_structured_generation_and_repair_use_actual_recorded_attempts(self):
        calls = [call("c1", "结构校验失败内容"), call("c2", "后续内容", attempt=2,
                    messages=["请求内容", "显式修复请求"], phase="generating")]
        result = export_recorded_run({"run_id": "run-schema", "kind": "lesson"}, calls,
                                     trial_id="trial-schema", subject={"identity": "unknown"})
        agents = [item for item in result["steps"] if item["source"] == "agent"]
        self.assertEqual(len(agents), 2)
        self.assertEqual(result["final_metrics"]["total_prompt_tokens"], 20)
        users = [item for item in result["steps"] if item["source"] == "user"]
        self.assertEqual([item["message"] for item in users], ["请求内容", "显式修复请求"])
        self.assertEqual(result["extra"]["mini_hyperknow"]["source_recording_complete"], "unknown")

    def test_historical_answer_is_context_not_a_new_current_run_inference(self):
        response = {"role": "assistant", "content": "当前回复", "tool_calls": [], "stop_reason": "stop",
                    "model": "schema-model", "usage": None}
        recorded = call("c1", response, kind="assistance", usage=None,
            messages=[{"role": "user", "content": "历史问题"},
                      {"role": "assistant", "content": "历史回复", "tool_calls": []},
                      {"role": "user", "content": "当前问题"}])
        result = export_recorded_run({"run_id": "run-schema", "kind": "assistance"}, [recorded],
                                     trial_id="trial-schema", subject={})
        self.assertEqual(len([s for s in result["steps"] if s["source"] == "agent"]), 1)
        self.assertNotIn("total_prompt_tokens", result["final_metrics"])
        self.assertTrue(any("historical assistant" in s["message"] for s in result["steps"]))

    def test_conflicting_ids_and_foreign_run_are_rejected(self):
        run = {"run_id": "run-schema", "kind": "research"}
        item = call("c1", "内容")
        for calls in ([], [item, deepcopy(item)], [{**item, "run_id": "another"}]):
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                export_recorded_run(run, calls, trial_id="trial-schema", subject={})

    def test_unknown_usage_and_provider_failure_are_not_filled_with_zero(self):
        with self.assertRaises(ValueError):
            export_recorded_run({"run_id": "run-schema", "kind": "quiz"},
                [call("c1", None, usage=None, stop_reason="error")], trial_id="trial-schema", subject={})
        result = export_recorded_run({"run_id": "run-schema", "kind": "quiz"},
            [call("c1", "已有记录"), call("c2", None, usage=None, stop_reason="error")],
            trial_id="trial-schema", subject={})
        self.assertFalse(result["extra"]["mini_hyperknow"]["complete"])
        self.assertNotIn("total_prompt_tokens", result["final_metrics"])

    def test_real_file_export_is_idempotent_and_never_changes_frozen_data(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            data = {"runs": {"run-schema": {"run_id": "run-schema", "kind": "lesson"}},
                    "calls": [call("c1", "结构数据")], "turns": []}
            material = {"checkpoint_id": "final", "data": data,
                        "observation": {"state": "terminal", "outcome": "success", "actions": [],
                                        "resources": {}, "checkpoints": ["final"]}}
            evidence = {"evidence_id": digest(material), **material,
                        "sha256": digest(data), "captured_at": "2026-10-27"}
            state = {"trial_id": "trial-schema", "subject": {}, "evidence": [evidence]}
            write_json(output / "result.json", state)
            first = export_trial_trajectories(output)
            self.assertEqual(first["evidence"], state["evidence"])
            self.assertTrue(first["trajectories"]["run-schema"]["valid"])
            second = export_trial_trajectories(output)
            self.assertEqual(first, second)
            self.assertEqual(read_json(output / "result.json")["evidence"], state["evidence"])
            state["evidence"][0]["observation"]["outcome"] = "failed"
            write_json(output / "result.json", state)
            original = (output / "result.json").read_bytes()
            with self.assertRaises(ValueError):
                export_trial_trajectories(output)
            self.assertEqual((output / "result.json").read_bytes(), original)

    def test_assistance_rules_require_linked_saved_turn_not_tool_success(self):
        run = {"run_id": "run-schema", "turn_id": "turn-schema", "status": "ready"}
        turn = {"run_id": "run-schema", "turn_id": "turn-schema", "status": "ready", "artifacts": [],
                "response": {"text": "结构内容", "questions": [], "plan": [], "waiting_for": "none"}}
        view = {"e1": {"data": {"runs": {"run-schema": run}, "turns": [turn]}}}
        for name in ("saved_assistance", "no_artifacts", "no_questions"):
            self.assertEqual(RULES[name]({}, view)["verdict"], "pass")
        turn["run_id"] = "replacement"
        self.assertEqual(RULES["saved_assistance"]({}, view)["verdict"], "undetermined")


if __name__ == "__main__":
    unittest.main()
