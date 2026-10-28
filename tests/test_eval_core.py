"""Pure JSON state and actual local files; no substitute adapters or providers.

These are engineering checks, not claims of product or model evaluation coverage.
Real HTTP adapter execution is checked in the integration suite separately.
"""

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from eval_core.cases import collect_sample, freeze_benchmark, publish_case
from eval_core.contracts import public_case, validate_case, validate_observation
from eval_core.runner import (_append_evidence, _append_skip_capture, _budget_reason,
                              _declared_checkpoints, _is_complete, _matches,
                              _new_result, _record_model_calls, _settle_step,
                              _validate_saved, execute_trial)
from eval_core.store import digest, exclusive, now, read_json, write_json


def case_data():
    return {"schema_version": 2, "id": "file-state-contract", "version": "1",
            "title": "JSON contract engineering check", "tags": ["engineering"],
            "task": {"profile": "local-file", "input": {"text": "公开资料"}},
            "prerequisites": {},
            "steps": [{"id": "write", "action": "write", "input": {"text": "input"},
                       "when": {"state": ["preparing"], "action": "write"},
                       "optional": False, "checkpoint": "after-write"}],
            "checks": [{"check_id": "saved", "version": "1", "kind": "rule",
                        "evaluator": "stored-json-v1", "criterion": "saved data",
                        "pass_when": "the declared facts are saved", "fail_when": "facts differ",
                        "evidence": ["saved"], "required": True, "applicable_when": {}}],
            "reference_facts": ["Private grading fact; never sent to execution."],
            "capture": ["saved"], "limits": {}, "completion": {}}


def observation(state="waiting", **extra):
    return {"state": state, "actions": [], "resources": {}, "checkpoints": [], **extra}


def journal():
    """A data fixture, not a simulated execution or a recorded provider reply."""
    case = validate_case(case_data())
    result = _new_result(case, {"source": "pure-data"}, "trial-data", 1, "isolated")
    result.update(environment={"storage": "declared-file-identity"}, prepared=True)
    initial = {"opaque": {"resource": "file-1", "version": 7}}
    result["bindings"] = deepcopy(initial)
    result["steps"][0].update(status="selected", action_id="command-data",
                               selection={"bindings": initial,
                                          "observation": observation("preparing", actions=["write"])})
    result["actions"].append({"action_id": "command-data", "step_id": "write", "status": "prepared",
                              "request": {"command_id": "command-data", "expected_version": 7,
                                          "target": {"opaque": "file-1"}, "body": {"text": "input"}}})
    return case, result


class ContractTests(unittest.TestCase):
    def test_defaults_and_public_projection_do_not_mutate_private_case(self):
        original = case_data()
        case = validate_case(original)
        self.assertEqual(case["limits"], {"max_actions": 32, "wait_seconds": 420,
                                         "poll_seconds": 0.25, "max_model_calls": 32})
        self.assertEqual(case["completion"], {"states": ["waiting", "terminal"], "outcomes": ["success"]})
        public = public_case(case)
        self.assertNotIn("checks", public)
        self.assertNotIn("reference_facts", public)
        self.assertEqual(public["capture"], ["saved"])
        public["task"]["input"]["text"] = "changed"
        self.assertEqual(original["task"]["input"]["text"], "公开资料")
        self.assertEqual(case["task"]["input"]["text"], "公开资料")
        self.assertEqual(validate_case(case), case)

    def test_task_accepts_only_public_json_input_and_declared_answer_policy(self):
        for value in ("text", {"x": 1}, [1, "text"], None, False):
            case = case_data()
            case["task"]["input"] = value
            case["task"]["answer_policy"] = {"mode": "declared", "skip": False}
            self.assertEqual(validate_case(case)["task"]["input"], value)
        case["task"]["tool_code"] = "must not be interpreted"
        with self.assertRaises(ValueError):
            validate_case(case)

    def test_forbids_extra_fields_and_arbitrary_conditions_at_every_boundary(self):
        paths = [(), ("task",), ("steps", 0), ("steps", 0, "when"),
                 ("checks", 0), ("checks", 0, "applicable_when"), ("limits",), ("completion",)]
        for path in paths:
            with self.subTest(path=path):
                case = case_data()
                target = case
                for key in path:
                    target = target[key]
                target["expression"] = "arbitrary.code()"
                with self.assertRaises(ValueError):
                    validate_case(case)

    def test_string_versions_and_shared_rule_llm_check_identity(self):
        case = case_data()
        for bad in (2.0, "2", True, None):
            invalid = deepcopy(case)
            invalid["schema_version"] = bad
            with self.assertRaises(ValueError):
                validate_case(invalid)
        for bad in (1, "", "   ", None):
            invalid = deepcopy(case)
            invalid["version"] = bad
            with self.assertRaises(ValueError):
                validate_case(invalid)
        case["checks"][0]["evaluator"] = {"name": "not-an-identity-string"}
        with self.assertRaises(ValueError):
            validate_case(case)
        case = case_data()
        duplicate = deepcopy(case["checks"][0])
        duplicate["kind"] = "llm"
        case["checks"].append(duplicate)
        with self.assertRaises(ValueError):
            validate_case(case)

    def test_rejects_duplicate_steps_unknown_evidence_and_wrong_types(self):
        case = case_data()
        case["steps"].append(deepcopy(case["steps"][0]))
        with self.assertRaises(ValueError):
            validate_case(case)
        case = case_data()
        case["checks"][0]["evidence"] = ["unplanned"]
        with self.assertRaises(ValueError):
            validate_case(case)
        for key, value in (("max_actions", True), ("max_model_calls", -1),
                           ("poll_seconds", 0), ("wait_seconds", float("inf"))):
            case = case_data()
            case["limits"][key] = value
            with self.assertRaises(ValueError):
                validate_case(case)

    def test_check_may_reference_step_alias_without_duplicate_capture_declaration(self):
        case = case_data()
        case["checks"][0]["evidence"] = ["after-write"]
        self.assertEqual(validate_case(case)["checks"][0]["evidence"], ["after-write"])

    def test_evidence_fields_default_to_full_data_and_keep_projection_private(self):
        original = case_data()
        case = validate_case(original)
        self.assertEqual(case["checks"][0]["evidence_fields"], [])
        self.assertNotIn("evidence_fields", original["checks"][0])
        projected = deepcopy(original)
        projected["checks"][0]["evidence_fields"] = ["turns", "artifacts"]
        normalized = validate_case(projected)
        self.assertEqual(normalized["checks"][0]["evidence_fields"], ["turns", "artifacts"])
        self.assertEqual(validate_case(normalized), normalized)
        self.assertEqual(public_case(case), public_case(normalized))

    def test_evidence_fields_reject_duplicate_names_after_normalization(self):
        for fields in (["turns", "turns"], ["turns", " turns "]):
            case = case_data()
            case["checks"][0]["evidence_fields"] = fields
            with self.assertRaises(ValueError):
                validate_case(case)

    def test_evidence_fields_allow_top_level_keys_not_paths_expressions_or_wrong_types(self):
        case = case_data()
        case["checks"][0]["evidence_fields"] = ["runs", "resources", "source_refs", "source-refs"]
        self.assertEqual(validate_case(case)["checks"][0]["evidence_fields"], case["checks"][0]["evidence_fields"])
        for invalid in (["resources.runs"], ["$.turns"], ["turns[0]"], ["/resources"], ["*"],
                        ["runs()"], [""], ["   "], [1], "turns", None):
            with self.subTest(value=invalid):
                case["checks"][0]["evidence_fields"] = invalid
                with self.assertRaises(ValueError):
                    validate_case(case)

    def test_observation_validates_common_fields_and_keeps_opaque_resources(self):
        value = observation("running", resources={"anything": {"version": "opaque"}},
                            model_calls=None, product_fact={"unknown-to-core": True})
        self.assertEqual(validate_observation(value), value)
        for patch in ({"state": "invented"}, {"actions": "write"}, {"resources": []},
                      {"checkpoints": [""]}, {"actions": ["write", "write"]},
                      {"model_calls": -1}, {"model_calls": True}, {"model_calls": 1.5}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_observation({**value, **patch})

    def test_null_outcome_is_normalized_without_losing_other_observation_facts(self):
        for state in ("preparing", "running", "waiting", "terminal"):
            current = observation(state, outcome=None, data={"actual": "fact"})
            normalized = validate_observation(current)
            self.assertNotIn("outcome", normalized)
            self.assertEqual(normalized["data"], {"actual": "fact"})
            self.assertIsNone(current["outcome"])


class StoreTests(unittest.TestCase):
    def test_hash_is_canonical_and_rejects_non_json(self):
        self.assertEqual(digest({"b": 2, "a": "资料"}), digest({"a": "资料", "b": 2}))
        for invalid in (float("nan"), float("inf"), {1: "integer key"}, (1, 2), {"x": object()}):
            with self.assertRaises(ValueError):
                digest(invalid)
        self.assertIsNotNone(datetime.fromisoformat(now()).tzinfo)

    def test_real_atomic_json_retains_previous_value_on_serialization_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "data.json"
            write_json(path, {"text": "真实本地文件", "version": 1})
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                write_json(path, {"bad": float("nan")})
            self.assertEqual(path.read_bytes(), original)
            write_json(path, {"version": 2})
            self.assertEqual(read_json(path), {"version": 2})
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_read_rejects_duplicate_keys_and_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_json(path)

    def test_real_lock_rejects_second_writer_and_cleans_up_exceptions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".writer.lock"
            with self.assertRaisesRegex(RuntimeError, "intentional"):
                with exclusive(path):
                    self.assertTrue(path.is_file())
                    with self.assertRaises(ValueError):
                        with exclusive(path):
                            self.fail("a second writer acquired the lock")
                    raise RuntimeError("intentional cleanup check")
            self.assertFalse(path.exists())
            path.write_text("leftover crash lock", encoding="utf-8")
            with self.assertRaises(ValueError):
                with exclusive(path):
                    self.fail("a stale lock must not be removed automatically")
            self.assertEqual(path.read_text(encoding="utf-8"), "leftover crash lock")


class CasePipelineTests(unittest.TestCase):
    def test_publication_detects_a_corrupted_content_addressed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory)
            case = validate_case(case_data())
            path = publish_case(case, library, "assistant:engineering-review")
            corrupted = read_json(path)
            corrupted["case"]["title"] = "changed outside publication API"
            write_json(path, corrupted)
            with self.assertRaises(ValueError):
                publish_case(case, library, "assistant:engineering-review")
            with self.assertRaises(ValueError):
                freeze_benchmark({"id": "corruption", "version": "1", "title": "Corruption check",
                                  "members": [{"id": case["id"], "version": case["version"],
                                               "case_hash": digest(case)}]}, library)

    def test_offline_publication_is_immutable_and_does_not_claim_human_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory)
            case = validate_case(case_data())
            path = publish_case(case, library, "assistant:engineering-review")
            original = path.read_bytes()
            record = read_json(path)
            self.assertEqual(record["case"], case)
            self.assertEqual(path.stem, digest(case))
            self.assertEqual(record["status"], "published")
            self.assertEqual(record["review_status"], "reviewed")
            self.assertEqual(record["calibration_status"], "uncalibrated")
            self.assertEqual(record["independent_human_review"], "not_verified")
            self.assertEqual(publish_case(case, library, "another-declared-reviewer"), path)
            self.assertEqual(path.read_bytes(), original)
            case["title"] = "changed content needs a new version"
            with self.assertRaises(ValueError):
                publish_case(case, library, "assistant:engineering-review")
            case["version"] = "2"
            self.assertNotEqual(publish_case(case, library, "assistant:engineering-review"), path)
            with self.assertRaises(ValueError):
                publish_case(case, library, "")

    def test_freeze_requires_exact_published_member_and_preserves_fixed_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory)
            case = validate_case(case_data())
            publish_case(case, library, "assistant:engineering-review")
            definition = {"schema_version": 2, "id": "engineering", "version": "1", "title": "Data checks",
                          "members": [{"id": case["id"], "version": case["version"], "case_hash": digest(case)}]}
            path = freeze_benchmark(definition, library)
            original = path.read_bytes()
            frozen = read_json(path)
            self.assertEqual(path.stem, digest(frozen["benchmark"]))
            self.assertEqual(frozen["benchmark"]["members"], definition["members"])
            self.assertEqual(freeze_benchmark(definition, library), path)
            self.assertEqual(path.read_bytes(), original)
            invalid = deepcopy(definition)
            invalid["members"][0]["version"] = "latest"
            with self.assertRaises(ValueError):
                freeze_benchmark(invalid, library)
            invalid = deepcopy(definition)
            invalid["members"] *= 2
            with self.assertRaises(ValueError):
                freeze_benchmark(invalid, library)
            invalid = deepcopy(definition)
            invalid["title"] = "new content with same version"
            with self.assertRaises(ValueError):
                freeze_benchmark(invalid, library)

    def test_samples_append_immutable_snapshots_without_creating_or_editing_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory)
            case, result = journal()
            path = collect_sample(result, library)
            original = path.read_bytes()
            self.assertEqual(collect_sample(result, library), path)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((library / "cases").exists())
            result["grades"].append({"attempt_id": "pure-data-attempt", "status": "error"})
            second = collect_sample(result, library)
            self.assertNotEqual(path, second)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(read_json(second)["review_status"], "unreviewed")
            self.assertEqual(len(list(second.parent.glob("*.json"))), 2)
            result["case_hash"] = "wrong"
            with self.assertRaises(ValueError):
                collect_sample(result, library)


class RunnerStateTests(unittest.TestCase):
    def test_only_finite_state_action_checkpoint_matching(self):
        case = validate_case(case_data())
        condition = {"state": ["waiting"], "action": "continue", "checkpoint": "saved"}
        current = observation(actions=["continue"], checkpoints=["saved"])
        self.assertTrue(_matches(condition, current))
        for patch in ({"state": "running"}, {"actions": []}, {"checkpoints": []}):
            self.assertFalse(_matches(condition, {**current, **patch}))
        self.assertFalse(_is_complete(case, observation("running", checkpoints=["saved"])))
        self.assertFalse(_is_complete(case, observation("terminal", outcome="failed")))
        self.assertFalse(_is_complete(case, observation("terminal")))
        self.assertTrue(_is_complete(case, observation("terminal", outcome="success")))
        self.assertTrue(_is_complete(case, observation("waiting")))
        self.assertTrue(_is_complete(case, observation("waiting", outcome=None)))

    def test_only_declared_checkpoints_become_evidence_while_all_observation_facts_remain(self):
        case, result = journal()
        current = observation("running", checkpoints=["saved", "undeclared", "after-write"],
                              data={"actual": "all observed facts"})
        checkpoints = _declared_checkpoints(case, current)
        self.assertEqual(checkpoints, ["saved", "after-write"])
        _append_evidence(result, current, {"facts": "read-only snapshot"}, checkpoints)
        self.assertEqual([item["checkpoint_id"] for item in result["evidence"]], checkpoints)
        self.assertEqual(current["checkpoints"], ["saved", "undeclared", "after-write"])
        self.assertEqual(result["evidence"][0]["observation"]["data"], current["data"])

    def test_optional_skip_captures_real_facts_with_no_action_or_invented_output(self):
        case = case_data()
        case["steps"][0]["optional"] = True
        case = validate_case(case)
        result = _new_result(case, {}, "skip-trial")
        result.update(prepared=True, environment={"storage": "declared-only"}, bindings={"opaque": "version-7"})
        current = observation("waiting", resources={"opaque": {"version": 7}}, checkpoints=[])
        item = result["steps"][0]
        item.update(status="skipped", observation=deepcopy(current), skipped_at=now(),
                    capture_status="pending", capture_bindings=deepcopy(result["bindings"]))
        _validate_saved(result, case, {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_json(path, result)
            result = read_json(path)
            item = result["steps"][0]
            facts = {"actual_stage": "ready", "questions": []}
            _append_skip_capture(result, item, case["steps"][0], facts)
            write_json(path, result)
            saved = read_json(path)
            self.assertEqual(saved["actions"], [])
            self.assertEqual(saved["steps"][0]["status"], "skipped")
            self.assertEqual(saved["steps"][0]["capture_status"], "captured")
            evidence = saved["evidence"][0]
            self.assertEqual(evidence["checkpoint_id"], "after-write")
            self.assertEqual(evidence["data"], facts)
            self.assertEqual(evidence["sha256"], digest(facts))
            self.assertEqual(evidence["observation"]["runner_step"],
                             {"step_id": "write", "status": "skipped", "action_executed": False})
            self.assertEqual(evidence["observation"]["resources"], current["resources"])
            _validate_saved(saved, case, {})
            # Recovery reads the persisted skip/capture plan; it does not select
            # an action just because a later observation would offer it.
            self.assertTrue(_matches(case["steps"][0]["when"], observation("preparing", actions=["write"])))
            self.assertEqual(saved["steps"][0]["status"], "skipped")
            self.assertEqual(saved["steps"][0]["capture_bindings"], {"opaque": "version-7"})

    def test_in_flight_or_running_step_never_settles_at_a_grading_checkpoint(self):
        case, result = journal()
        result["actions"][0]["status"] = "in_flight"
        self.assertFalse(_settle_step(result, observation("waiting")))
        result["actions"][0].update(status="committed", bindings={"opaque": {"version": 8}})
        result["bindings"] = deepcopy(result["actions"][0]["bindings"])
        self.assertFalse(_settle_step(result, observation("running", checkpoints=["saved"])))
        self.assertEqual(result["steps"][0]["status"], "selected")
        self.assertTrue(_settle_step(result, observation("waiting")))
        self.assertEqual(result["steps"][0]["status"], "settled")
        self.assertFalse(_settle_step(result, observation("waiting")))

    def test_evidence_hashes_data_and_deduplicates_full_fact_identity_without_overwrite(self):
        case, result = journal()
        current = observation("running", checkpoints=["saved"], resources={"opaque": {"version": 1}})
        data = {"facts": {"text": "first version"}}
        _append_evidence(result, current, data, ["saved", "after-write"])
        self.assertEqual(len(result["evidence"]), 2)
        first = deepcopy(result["evidence"])
        for item in first:
            self.assertEqual(item["sha256"], digest(data))
            self.assertEqual(item["evidence_id"], digest({key: item[key] for key in
                                                        ("checkpoint_id", "data", "observation")}))
        _append_evidence(result, current, data, ["saved", "after-write"])
        self.assertEqual(result["evidence"], first)
        changed = {"facts": {"text": "next version"}}
        _append_evidence(result, current, changed, ["saved"])
        self.assertEqual(result["evidence"][:2], first)
        self.assertEqual(len(result["evidence"]), 3)
        data["facts"]["text"] = "caller mutation"
        self.assertEqual(result["evidence"][0]["data"]["facts"]["text"], "first version")
        self.assertFalse(result["settled"])

    def test_unknown_model_usage_never_becomes_zero_or_a_hard_cap_guarantee(self):
        case, result = journal()
        _record_model_calls(result, observation(model_calls=None))
        self.assertIsNone(result["budget"]["model_calls"])
        self.assertEqual(result["budget"]["model_calls_coverage"], "unknown")
        self.assertFalse(result["budget"]["hard_model_call_cap_guaranteed"])
        self.assertIsNone(_budget_reason(result, case["limits"], 0))
        _record_model_calls(result, observation(model_calls=32))
        self.assertEqual(_budget_reason(result, case["limits"], 0), "model_call_limit")
        _record_model_calls(result, observation())
        self.assertIsNone(result["budget"]["model_calls"])
        self.assertEqual(_budget_reason(result, case["limits"], 0), "model_call_limit")
        with self.assertRaises(ValueError):
            _record_model_calls(result, observation(model_calls=31))
        self.assertEqual(_budget_reason(result, case["limits"], 420), "wait_timeout")
        self.assertFalse(result["settled"])

    def test_real_journal_preserves_exact_request_status_and_original_binding_selection(self):
        case, result = journal()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            request = deepcopy(result["actions"][0]["request"])
            for status in ("prepared", "in_flight", "committed"):
                result["actions"][0]["status"] = status
                if status == "committed":
                    result["actions"][0]["bindings"] = {"opaque": {"version": 8}}
                    result["bindings"] = {"opaque": {"version": 8}}
                write_json(path, result)
                saved = read_json(path)
                _validate_saved(saved, case, result["subject"], "trial-data", 1, "isolated")
                self.assertEqual(saved["actions"][0]["request"], request)
                self.assertEqual(saved["steps"][0]["selection"]["bindings"]["opaque"]["version"], 7)

    def test_resume_rejects_case_target_plan_and_evidence_drift(self):
        case, result = journal()
        _validate_saved(result, case, result["subject"])
        variants = [("trial_id", "different-trial"), ("repetition", 2),
                    ("environment_policy", "shared")]
        for key, value in variants:
            altered = deepcopy(result)
            altered[key] = value
            with self.assertRaises(ValueError):
                _validate_saved(altered, case, result["subject"], "trial-data", 1, "isolated")
        with self.assertRaises(ValueError):
            _validate_saved(result, case, {"source": "different"})
        altered_case = deepcopy(case)
        altered_case["title"] = "different Case"
        with self.assertRaises(ValueError):
            _validate_saved(result, altered_case, result["subject"])
        _append_evidence(result, observation(checkpoints=["saved"]), {"text": "fact"}, ["saved"])
        result["evidence"][0]["data"]["text"] = "tampered"
        with self.assertRaises(ValueError):
            _validate_saved(result, case, result["subject"])

    def test_completed_data_requires_settled_steps_and_successful_terminal_observation(self):
        case, result = journal()
        result["stage"], result["settled"] = "completed", True
        with self.assertRaises(ValueError):
            _validate_saved(result, case, result["subject"])
        result["actions"][0].update(status="committed", bindings={"opaque": "receipt"})
        result["bindings"] = {"opaque": "receipt"}
        self.assertTrue(_settle_step(result, observation("terminal", outcome="success")))
        _append_evidence(result, observation("terminal", outcome="success"),
                         {"source": "pure-data"}, ["after-write"])
        result["observations"].append({"observation": observation("terminal", outcome="success"), "observed_at": now()})
        _validate_saved(result, case, result["subject"])
        result["observations"][-1]["observation"]["outcome"] = "failed"
        with self.assertRaises(ValueError):
            _validate_saved(result, case, result["subject"])

    def test_saved_evidence_rejects_duplicate_ids_or_undeclared_checkpoints(self):
        case, result = journal()
        _append_evidence(result, observation(checkpoints=["saved"]), {"fact": "data"}, ["saved"])
        result["evidence"].append(deepcopy(result["evidence"][0]))
        with self.assertRaises(ValueError):
            _validate_saved(result, case, result["subject"])
        result["evidence"] = []
        _append_evidence(result, observation(checkpoints=["undeclared"]), {"fact": "data"}, ["undeclared"])
        with self.assertRaises(ValueError):
            _validate_saved(result, case, result["subject"])

    def test_public_entry_rejects_invalid_or_overwriting_file_inputs_before_adapter_boundary(self):
        # None deliberately provides no adapter. These guards must run before any
        # boundary call; there is no replacement implementation of that boundary.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            case, result = journal()
            write_json(path, result)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                execute_trial(case, None, path, execute=True)
            changed = deepcopy(case)
            changed["title"] = "wrong case"
            with self.assertRaises(ValueError):
                execute_trial(changed, None, path, resume=True)
            with exclusive(path.parent / ".writer.lock"):
                with self.assertRaises(ValueError):
                    execute_trial(case, None, path, execute=True, resume=True)
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(ValueError):
                execute_trial(case, None, Path(directory) / "missing", resume=True)
            for arguments in ({"execute": "yes"}, {"repetition": True}, {"trial_id": ""},
                              {"environment_policy": ""}):
                with self.assertRaises(ValueError):
                    execute_trial(case, None, path, **arguments)


if __name__ == "__main__":
    unittest.main()
