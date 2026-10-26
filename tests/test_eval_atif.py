"""Handwritten data-only conversion checks, not evidence of model execution."""

from copy import deepcopy
import json
import unittest

from hyperknow.eval_atif import export_trajectory, validate_trajectory


def run_data():
    return {"kind": "assistance", "run_id": "run-1", "conversation_id": "conversation-1",
            "turn_id": "turn-1", "model": "requested-model",
            "input": {"text": "解释链式法则", "history": [], "history_truncated": False}}


def response_data(content="", tool_id=None, *, usage=None):
    return {"role": "assistant", "content": content,
            "tool_calls": ([{"id": tool_id, "name": "get_skills",
                             "arguments": {"name": "optional-example"}}] if tool_id else []),
            "stop_reason": "tool_use" if tool_id else "stop", "model": "returned-model",
            "provider": "openai", "usage": usage, "error_message": None}


def call_data(run, attempt, messages, response, *, call_id=None, system="实际教学系统提示"):
    return {"id": call_id or f"call-{attempt}", "run_id": run["run_id"], "kind": "assistance",
            "phase": "generating", "attempt": attempt, "requested_model": run["model"],
            "model": response["model"], "provider": response["provider"],
            "system_prompt": system, "messages": deepcopy(messages),
            "tools": [{"type": "function", "function": {"name": "get_skills",
                       "parameters": {"description": "RAW_SCHEMA_SENTINEL"}}}],
            "input_basis": deepcopy(run["input"]), "response": deepcopy(response),
            "usage": deepcopy(response["usage"]), "stop_reason": response["stop_reason"],
            "skill_uses": [], "created_at": f"2026-10-26T10:00:0{attempt}+00:00"}


def text_call(run=None, *, usage=None, system="实际教学系统提示"):
    run = run or run_data()
    return call_data(run, 1, [{"role": "user", "content": "模型实际看到的用户文字，不从run.input伪造"}],
                     response_data("公开回复", usage=usage), system=system)


def tool_flow():
    run = run_data()
    messages, calls = [{"role": "user", "content": "模型实际输入"}], []
    for attempt, tool_id, call_id in ((1, "skill-1", "call-z"), (2, "skill-2", "call-a"), (3, None, "call-m")):
        response = response_data("公开回复" if tool_id is None else "", tool_id,
                                 usage={"prompt_tokens": 10 * attempt, "completion_tokens": 2 * attempt,
                                        "cached_tokens": attempt, "total_tokens": 12 * attempt})
        calls.append(call_data(run, attempt, messages, response, call_id=call_id))
        messages.append(response)
        if tool_id:
            messages.append({"role": "tool_result", "tool_call_id": tool_id,
                             "content": f"{tool_id}可见结果\n[truncated; full text: unavailable]", "is_error": False})
    return run, calls


class ExportTests(unittest.TestCase):
    def export(self, run, calls):
        return export_trajectory(run, calls, execution_id="execution-1", agent_version="code-sha-1")

    def test_mapping_single_inference_steps_and_same_step_tool_feedback(self):
        run, calls = tool_flow()
        before = deepcopy((run, calls))
        trajectory = self.export(run, calls)
        self.assertEqual((run, calls), before)
        self.assertEqual(validate_trajectory(trajectory), trajectory)
        self.assertEqual(trajectory["schema_version"], "ATIF-v1.7")
        self.assertEqual(trajectory["agent"], {"name": "mini-hyperknow-assistance", "version": "code-sha-1"})
        self.assertEqual(trajectory["session_id"], "execution-1")
        self.assertNotEqual(trajectory["trajectory_id"], "execution-1")
        self.assertEqual(trajectory["trajectory_id"], self.export(run, calls)["trajectory_id"])
        steps = trajectory["steps"]
        self.assertEqual([step["step_id"] for step in steps], [1, 2, 3, 4, 5])
        self.assertEqual([step["source"] for step in steps], ["system", "user", "agent", "agent", "agent"])
        self.assertEqual([step["extra"]["mini_hyperknow"]["call_id"] for step in steps[2:]],
                         ["call-z", "call-a", "call-m"])
        for step, tool_id in zip(steps[2:4], ("skill-1", "skill-2")):
            self.assertEqual(step["llm_call_count"], 1)
            self.assertEqual(step["model_name"], "returned-model")
            self.assertEqual(step["tool_calls"][0], {"tool_call_id": tool_id, "function_name": "get_skills",
                                                    "arguments": {"name": "optional-example"}})
            result = step["observation"]["results"][0]
            self.assertEqual(result["source_call_id"], tool_id)
            self.assertEqual(result["content"], f"{tool_id}可见结果\n[truncated; full text: unavailable]")
            self.assertEqual(result["extra"]["mini_hyperknow"]["original_truncation"], "unknown")
        self.assertEqual(len(steps[2]["observation"]["results"]), 1)
        self.assertEqual(len(steps[2]["observation"]["results"][0]["extra"]["mini_hyperknow"]["evidence_refs"]), 2)
        self.assertEqual(trajectory["final_metrics"], {"total_steps": 5, "total_prompt_tokens": 60,
                                                      "total_completion_tokens": 12, "total_cached_tokens": 6})
        self.assertTrue(trajectory["extra"]["mini_hyperknow"]["complete"])
        self.assertTrue(trajectory["extra"]["mini_hyperknow"]["usage_complete"])

    def test_context_references_raw_definitions_and_hidden_reasoning_not_duplicated(self):
        run = run_data()
        call = text_call(run)
        call["response"]["reasoning_content"] = "HIDDEN_REASONING_SENTINEL"
        trajectory = self.export(run, [call])
        step = trajectory["steps"][-1]
        self.assertEqual(step["extra"]["mini_hyperknow"]["context_refs"],
                         {key: f"model_calls/call-1/{key}" for key in
                          ("system_prompt", "messages", "tools", "input_basis")})
        self.assertEqual(trajectory["steps"][1]["message"], call["messages"][0]["content"])
        rendered = json.dumps(trajectory, ensure_ascii=False)
        self.assertNotIn("RAW_SCHEMA_SENTINEL", rendered)
        self.assertNotIn("HIDDEN_REASONING_SENTINEL", rendered)
        self.assertNotIn("reasoning_content", rendered)

    def test_format_repair_retains_changed_system_actual_user_and_separate_inference(self):
        run = run_data()
        first = text_call(run)
        first["response"]["content"] = "{not valid teaching JSON"
        repair_text = '{"response_excerpt":"{not valid", "response_truncated":true}'
        repair = call_data(run, 2, [{"role": "user", "content": repair_text}], response_data('{"text":"修复"}'),
                           system="真实格式修复系统提示")
        trajectory = self.export(run, [first, repair])
        self.assertEqual([step["source"] for step in trajectory["steps"]],
                         ["system", "user", "agent", "system", "user", "agent"])
        self.assertEqual([step["message"] for step in trajectory["steps"]],
                         [first["system_prompt"], first["messages"][0]["content"], first["response"]["content"],
                          repair["system_prompt"], repair_text, repair["response"]["content"]])
        refs = trajectory["steps"][-1]["extra"]["mini_hyperknow"]["context_refs"]
        self.assertEqual(refs["messages"], "model_calls/call-2/messages")
        self.assertEqual(refs["input_basis"], "model_calls/call-2/input_basis")

    def test_unknown_usage_does_not_become_zero_and_partial_totals_are_omitted(self):
        run = run_data()
        unknown = self.export(run, [text_call(run)])
        self.assertNotIn("metrics", unknown["steps"][-1])
        self.assertEqual(unknown["final_metrics"], {"total_steps": 3})
        self.assertFalse(unknown["extra"]["mini_hyperknow"]["usage_complete"])
        run, calls = tool_flow()
        calls[-1]["usage"] = calls[-1]["response"]["usage"] = {"prompt_tokens": 30}
        partial = self.export(run, calls)
        self.assertEqual(partial["final_metrics"], {"total_steps": 5, "total_prompt_tokens": 60})
        self.assertEqual(partial["steps"][2]["metrics"]["completion_tokens"], 2)
        zero = self.export(run_data(), [text_call(usage={"prompt_tokens": 0, "completion_tokens": 0})])
        self.assertEqual(zero["final_metrics"]["total_prompt_tokens"], 0)

    def test_missing_tool_results_are_legal_but_explicitly_incomplete(self):
        run, calls = tool_flow()
        trajectory = self.export(run, calls[:1])
        self.assertNotIn("observation", trajectory["steps"][-1])
        metadata = trajectory["extra"]["mini_hyperknow"]
        self.assertEqual(metadata["missing_observations"], ["skill-1"])
        self.assertFalse(metadata["complete"])
        self.assertEqual(validate_trajectory(trajectory), trajectory)

    def test_missing_attempts_are_disclosed_without_reordering(self):
        run = run_data()
        call = text_call(run)
        call["attempt"] = 2
        metadata = self.export(run, [call])["extra"]["mini_hyperknow"]
        self.assertEqual(metadata["missing_call_attempts"], [1])
        self.assertFalse(metadata["complete"])

    def test_no_system_prompt_means_no_invented_system_step(self):
        trajectory = self.export(run_data(), [text_call(system="")])
        self.assertEqual([step["source"] for step in trajectory["steps"]], ["user", "agent"])

    def test_observable_provider_error_not_fabricated_as_assistant_text(self):
        run = run_data()
        call = text_call(run)
        call["response"].update(content="", stop_reason="error", error_message="Provider request failed")
        call["stop_reason"] = "error"
        step = self.export(run, [call])["steps"][-1]
        self.assertEqual(step["message"], "")
        self.assertEqual(step["extra"]["mini_hyperknow"]["error_message"], "Provider request failed")

    def test_invalid_call_inputs_and_identity_conflicts_fail_closed(self):
        changes = [
            lambda r, c: c.clear(),
            lambda r, c: c.reverse(),
            lambda r, c: c[1].update(attempt=1),
            lambda r, c: c[1].update(id=c[0]["id"]),
            lambda r, c: c[0].update(run_id="another-run"),
            lambda r, c: c[0].update(input_basis={"text": "different input"}),
            lambda r, c: c[0].update(kind="grader"),
            lambda r, c: r.update(kind="grader"),
            lambda r, c: c[0].update(response="not a recorded assistant object"),
            lambda r, c: c[0].pop("created_at"),
            lambda r, c: c[0].update(created_at="2026-10-26"),
            lambda r, c: c[0].update(messages=[{"role": "user", "content": [{"type": "audio"}]}]),
            lambda r, c: c[0].update(model="conflicting-model"),
            lambda r, c: c[0].update(usage={"prompt_tokens": 100}),
            lambda r, c: c[1]["messages"].append({"role": "tool_result", "tool_call_id": "orphan",
                                                 "content": "no source", "is_error": False}),
            lambda r, c: c[1]["messages"][1].update(content="conflicting historical assistant"),
            lambda r, c: c[2]["messages"][2].update(content="conflicting observation"),
            lambda r, c: c[1]["response"]["tool_calls"][0].update(id="skill-1"),
            lambda r, c: c[1]["messages"].append(deepcopy(c[1]["messages"][2])),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                run, calls = tool_flow()
                change(run, calls)
                with self.assertRaises(ValueError):
                    self.export(run, calls)

    def test_non_object_or_non_json_tool_arguments_are_never_repaired(self):
        for arguments in ('{"name":', '{"name":"valid-but-not-a-snapshot-object"}', [],
                          {"x": float("nan")}, {"x": float("inf")}, {1: "non-string key"}, {"x": (1, 2)}):
            with self.subTest(arguments=arguments):
                run, calls = tool_flow()
                calls[0]["response"]["tool_calls"][0]["arguments"] = arguments
                with self.assertRaises(ValueError):
                    self.export(run, calls)

    def test_usage_validation_rejects_negative_boolean_and_bad_cache_accounting(self):
        for usage in ({"prompt_tokens": -1}, {"completion_tokens": True}, {"prompt_tokens": "1"},
                      {"prompt_tokens": 2, "cached_tokens": 3}, {"cached_tokens": 1},
                      {"cost_usd": float("nan")}, {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 4}):
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                self.export(run_data(), [text_call(usage=usage)])


class ValidationTests(unittest.TestCase):
    def test_reject_versions_new_fields_roles_cross_step_refs_and_invalid_metrics(self):
        run, calls = tool_flow()
        original = export_trajectory(run, calls, execution_id="e", agent_version="v")
        changes = [
            lambda d: d.update(schema_version="ATIF-v1.8"),
            lambda d: d.update(schema_version="ATIF-v1.6"),
            lambda d: d.pop("schema_version"),
            lambda d: d.pop("agent"),
            lambda d: d["agent"].pop("version"),
            lambda d: d.update(audio=[]),
            lambda d: d["steps"][0].update(message=[{"type": "audio"}]),
            lambda d: d["steps"][0].update(step_id=2),
            lambda d: d["steps"][0].update(source="tool"),
            lambda d: d["steps"][0].update(model_name="not-an-agent"),
            lambda d: d["steps"][0].update(metrics={"prompt_tokens": 0}),
            lambda d: d["steps"][2].update(llm_call_count=0),
            lambda d: d["steps"][2].update(llm_call_count=True),
            lambda d: d["steps"][2].update(reasoning_content="hidden"),
            lambda d: d["steps"][2]["observation"]["results"][0].update(source_call_id="skill-2"),
            lambda d: d["steps"][2]["observation"]["results"][0].update(content=[{"type": "audio"}]),
            lambda d: d["steps"][2]["tool_calls"].append(deepcopy(d["steps"][2]["tool_calls"][0])),
            lambda d: d["steps"][2]["metrics"].update(cached_tokens=11),
            lambda d: d["final_metrics"].update(total_prompt_tokens=61),
            lambda d: d["final_metrics"].update(total_steps=99),
            lambda d: d["final_metrics"].update(total_cost_usd=0),
            lambda d: d["steps"][2]["metrics"].update(logprobs=[]),
            lambda d: d.update(extra={"not_json": object()}),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                data = deepcopy(original)
                change(data)
                with self.assertRaises(ValueError):
                    validate_trajectory(data)

    def test_validation_returns_independent_plain_data_and_accepts_z_timestamp(self):
        trajectory = export_trajectory(run_data(), [text_call()], execution_id="e", agent_version="v")
        trajectory["steps"][-1]["timestamp"] = "2026-10-26T10:00:01Z"
        validated = validate_trajectory(trajectory)
        self.assertEqual(validated, trajectory)
        validated["steps"][-1]["extra"]["mini_hyperknow"]["call_id"] = "changed"
        self.assertEqual(trajectory["steps"][-1]["extra"]["mini_hyperknow"]["call_id"], "call-1")


if __name__ == "__main__":
    unittest.main()
