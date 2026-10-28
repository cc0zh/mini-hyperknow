"""Finite, product-independent execution with write-ahead action recovery."""

from copy import deepcopy
from pathlib import Path
import time
from uuid import uuid4

from .adapter import Adapter
from .budget import trial_budget_overruns
from .contracts import public_case, validate_case, validate_observation
from .evidence import validate_evidence
from .store import digest, exclusive, now, read_json, write_json


def _dictionary(value, label):
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON dictionary")
    digest(value)
    return deepcopy(value)


def _matches(condition, observation):
    return (observation["state"] in condition["state"]
            and ("action" not in condition or condition["action"] in observation["actions"])
            and ("checkpoint" not in condition or condition["checkpoint"] in observation["checkpoints"]))


def _is_complete(case, observation):
    return (observation["state"] in case["completion"]["states"]
            and observation.get("outcome") != "failed"
            and (observation.get("outcome") in case["completion"]["outcomes"]
                 or (observation["state"] == "waiting" and observation.get("outcome") is None)))


def _declared_checkpoints(case, observation):
    declared = set(case["capture"]) | {step["checkpoint"] for step in case["steps"]}
    return [checkpoint for checkpoint in observation["checkpoints"] if checkpoint in declared]


def _record_model_calls(result, observation):
    calls = observation.get("model_calls")
    previous = result["budget"]["last_reported_model_calls"]
    if calls is not None and (type(calls) is not int or calls < 0):
        raise ValueError("model_calls must be a nonnegative integer or null")
    if calls is not None and previous is not None and calls < previous:
        raise ValueError("cumulative model_calls cannot decrease")
    result["budget"]["model_calls"] = calls
    result["budget"]["model_calls_coverage"] = (
        observation.get("model_calls_coverage", "reported") if calls is not None else "unknown")
    if calls is not None:
        result["budget"]["last_reported_model_calls"] = calls


def _budget_reason(result, limits, elapsed):
    if elapsed >= limits["wait_seconds"]:
        return "wait_timeout"
    known = result["budget"]["last_reported_model_calls"]
    if limits["max_model_calls"] == 0 or known is not None and known >= limits["max_model_calls"]:
        return "model_call_limit"
    return None


def _append_evidence(result, observation, data, checkpoints):
    existing = {digest({key: item[key] for key in ("checkpoint_id", "data", "observation")})
                for item in result["evidence"]}
    for checkpoint in checkpoints:
        material = {"checkpoint_id": checkpoint, "data": deepcopy(data),
                    "observation": deepcopy(observation)}
        identity = digest(material)
        if identity not in existing:
            result["evidence"].append({"evidence_id": identity, **material,
                                       "sha256": digest(data), "captured_at": now()})
            existing.add(identity)


def _append_skip_capture(result, item, step, data):
    """Alias actual facts, explicitly distinguishing a skip from an action receipt."""
    observation = deepcopy(item["observation"])
    observation["runner_step"] = {"step_id": step["id"], "status": "skipped", "action_executed": False}
    _append_evidence(result, observation, data, [step["checkpoint"]])
    item.update(capture_status="captured", captured_at=now())


def _settle_step(result, observation):
    if observation["state"] not in {"waiting", "terminal"}:
        return False
    selected = next((item for item in result["steps"] if item["status"] == "selected"), None)
    action = next((action for action in result["actions"]
                   if selected and action["action_id"] == selected["action_id"]), None)
    if action and action["status"] == "committed":
        selected.update(status="settled", settled_at=now())
        return True
    return False


def _new_result(case, subject, trial_id=None, repetition=1, environment_policy="isolated"):
    return {"schema_version": 2, "trial_id": trial_id or str(uuid4()), "case": deepcopy(case),
            "case_hash": digest(case), "subject": deepcopy(subject) if subject is not None else {}, "environment": None,
            "repetition": repetition, "environment_policy": environment_policy,
            "bindings": {}, "actions": [], "evidence": [], "stage": "waiting",
            "error": None, "settled": False, "grades": [], "prepared": False,
            "created_at": now(), "observations": [],
            "steps": [{"step_id": step["id"], "status": "pending"} for step in case["steps"]],
            "budget": {"elapsed_seconds": 0.0, "model_calls": None,
                       "last_reported_model_calls": None, "model_calls_coverage": "unknown",
                       "hard_model_call_cap_guaranteed": False}}


def _validate_saved(result, case, subject, trial_id=None, repetition=1, environment_policy="isolated"):
    _dictionary(result, "saved result")
    if (type(result.get("schema_version")) is not int or result["schema_version"] != 2
            or result.get("case_hash") != digest(case)
            or result.get("case") != case):
        raise ValueError("resume Case identity/schema mismatch")
    if type(result.get("trial_id")) is not str or not result["trial_id"].strip():
        raise ValueError("saved Trial identity is missing")
    if subject is not None and result.get("subject") != subject:
        raise ValueError("resume Subject identity mismatch")
    if ((trial_id is not None and result["trial_id"] != trial_id)
            or result.get("repetition") != repetition
            or result.get("environment_policy") != environment_policy):
        raise ValueError("resume planned Trial identity mismatch")
    if result.get("stage") not in {"completed", "waiting", "blocked", "failed"}:
        raise ValueError("invalid saved Trial stage")
    if type(result.get("prepared")) is not bool or type(result.get("settled")) is not bool:
        raise ValueError("invalid saved preparation/settlement status")
    if result.get("environment") is not None:
        _dictionary(result["environment"], "saved environment identity")
    progress = result.get("steps")
    if (type(progress) is not list or [item.get("step_id") for item in progress]
            != [step["id"] for step in case["steps"]]):
        raise ValueError("saved step plan does not match the Case")
    actions = result.get("actions")
    if type(actions) is not list:
        raise ValueError("saved actions must be a list")
    ids, step_ids = set(), set()
    for index, action in enumerate(actions):
        if (type(action) is not dict or type(action.get("action_id")) is not str
                or not action["action_id"] or action["action_id"] in ids
                or action.get("step_id") not in {step["id"] for step in case["steps"]}
                or action["step_id"] in step_ids
                or action.get("status") not in {"prepared", "in_flight", "committed"}):
            raise ValueError("invalid saved action identity/status")
        _dictionary(action.get("request"), "saved action request")
        if action["status"] == "committed":
            _dictionary(action.get("bindings"), "committed action bindings")
        elif index != len(actions) - 1:
            raise ValueError("an unresolved action must be the final action")
        ids.add(action["action_id"])
        step_ids.add(action["step_id"])
    for step, item in zip(case["steps"], progress):
        status = item.get("status")
        if status not in {"pending", "selected", "skipped", "settled"}:
            raise ValueError("invalid saved step status")
        if status == "skipped" and not step["optional"]:
            raise ValueError("a required step cannot be skipped")
        if status == "skipped":
            if item.get("capture_status") not in {"pending", "captured"}:
                raise ValueError("skipped step has no persisted capture status")
            validate_observation(item.get("observation"))
            _dictionary(item.get("capture_bindings"), "skipped step capture bindings")
        if status in {"selected", "settled"}:
            action = next((a for a in actions if a["step_id"] == step["id"]), None)
            if not item.get("action_id") or (action and action["action_id"] != item["action_id"]):
                raise ValueError("saved step/action identity mismatch")
            if status == "settled" and (not action or action["status"] != "committed"):
                raise ValueError("settled step has no committed action")
            if status == "selected" and not action:
                _dictionary(item.get("selection"), "saved step selection")
        elif step["id"] in step_ids:
            raise ValueError("saved action has no selected step")
    unfinished = False
    for item in progress:
        if unfinished and item["status"] != "pending":
            raise ValueError("saved steps are not a settled prefix and one active step")
        if item["status"] in {"pending", "selected"}:
            unfinished = True
    _dictionary(result.get("bindings"), "saved bindings")
    committed = [action for action in actions if action["status"] == "committed"]
    if committed and result["bindings"] != committed[-1]["bindings"]:
        raise ValueError("saved bindings do not match the last committed receipt")
    if type(result.get("evidence")) is not list or type(result.get("grades")) is not list:
        raise ValueError("saved evidence and grades must be lists")
    evidence_ids = set()
    declared = set(case["capture"]) | {step["checkpoint"] for step in case["steps"]}
    for evidence in result["evidence"]:
        if (type(evidence) is not dict or not {"evidence_id", "checkpoint_id", "sha256", "data",
                                              "observation", "captured_at"} <= evidence.keys()):
            raise ValueError("invalid saved evidence structure")
        if evidence["checkpoint_id"] not in declared or evidence["evidence_id"] in evidence_ids:
            raise ValueError("undeclared checkpoint or duplicate saved evidence identity")
        _dictionary(evidence["data"], "saved evidence facts")
        validate_evidence(evidence)
        for key in ("trial_id", "case_hash"):
            if key in evidence and evidence[key] != result[key]:
                raise ValueError("saved evidence belongs to another Trial or Case")
        evidence_ids.add(evidence["evidence_id"])
    captured = {evidence["checkpoint_id"] for evidence in result["evidence"]}
    for step, item in zip(case["steps"], progress):
        if (item["status"] == "settled" or (item["status"] == "skipped" and item["capture_status"] == "captured")):
            if step["checkpoint"] not in captured:
                raise ValueError("settled/skipped step has no captured checkpoint")
    if result.get("stage") == "completed" and (not result.get("settled") or
            not result["prepared"] or result["environment"] is None or
            any(item["status"] not in {"settled", "skipped"}
                or (item["status"] == "skipped" and item["capture_status"] != "captured") for item in progress)):
        raise ValueError("completed Trial has unfinished steps or execution")
    observations = result.get("observations")
    if type(observations) is not list:
        raise ValueError("saved observations must be a list")
    for observation in observations:
        validate_observation(observation["observation"])
    if result["stage"] == "completed" and (not observations or not _is_complete(case, observations[-1]["observation"])):
        raise ValueError("completed Trial has no successful completion observation")
    budget = _dictionary(result.get("budget"), "saved budget")
    if type(budget.get("elapsed_seconds")) not in (int, float) or budget["elapsed_seconds"] < 0:
        raise ValueError("invalid saved elapsed time")
    for key in ("model_calls", "last_reported_model_calls"):
        value = budget.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("invalid saved model-call count")


def _preflight(adapter, case, result, *, resume=False):
    bindings = deepcopy(result["bindings"]) if resume and result["prepared"] else None
    environment = _dictionary(adapter.preflight(deepcopy(public_case(case)), bindings), "preflight identity")
    if result["environment"] is not None and result["environment"] != environment:
        raise ValueError("resume target/environment identity mismatch")
    return environment


def execute_trial(case, adapter: Adapter, output, *, execute=False, resume=False, subject=None,
                  trial_id=None, repetition=1, environment_policy="isolated") -> dict:
    """Run an explicitly authorized finite plan, or read/recover without sending.

    output may be a directory or a .json result path. Resume never calls prepare
    again after successful preparation. A completed resume only validates Case,
    Subject and adapter target identity; it does not rewrite the result or lock.
    """
    case = validate_case(case)
    digest(subject)
    if type(execute) is not bool or type(resume) is not bool:
        raise ValueError("execute and resume must be explicit booleans")
    if trial_id is not None and (type(trial_id) is not str or not trial_id.strip()):
        raise ValueError("trial_id must be a nonempty string")
    if type(repetition) is not int or repetition < 1:
        raise ValueError("repetition must be a positive integer")
    if type(environment_policy) is not str or not environment_policy.strip():
        raise ValueError("environment_policy must be a nonempty string")
    output = Path(output)
    path = output if output.suffix.lower() == ".json" else output / "result.json"
    if resume and path.exists():
        result = read_json(path)
        _validate_saved(result, case, subject, trial_id, repetition, environment_policy)
        if result["stage"] == "completed":
            _preflight(adapter, case, result, resume=True)
            return result
    with exclusive(path.parent / ".writer.lock"):
        if resume:
            if not path.exists():
                raise ValueError("cannot resume a missing Trial")
            result = read_json(path)
            _validate_saved(result, case, subject, trial_id, repetition, environment_policy)
        else:
            if path.exists():
                raise ValueError("Trial already exists; use resume instead of overwriting")
            result = _new_result(case, subject, trial_id, repetition, environment_policy)
        started = time.monotonic()
        previous_elapsed = result["budget"]["elapsed_seconds"]

        def elapsed():
            return previous_elapsed + time.monotonic() - started

        def save():
            result["budget"]["elapsed_seconds"] = elapsed()
            write_json(path, result)

        def stop(stage, code, message, *, unsettled=False):
            result["stage"] = stage
            result["error"] = {"code": code, "message": str(message)}
            if unsettled:
                result["settled"] = False
            save()
            return result

        try:
            environment = _preflight(adapter, case, result, resume=resume)
        except ValueError as exc:
            # A different target must never rewrite or rebind an existing Trial.
            if resume and result["environment"] is not None:
                raise
            return stop("blocked", "preflight_error", exc, unsettled=True)
        except Exception as exc:
            return stop("blocked", "preflight_error", exc, unsettled=True)
        result["environment"] = environment
        result["stage"], result["error"] = "waiting", None
        save()
        if not result["prepared"]:
            try:
                bindings = _dictionary(adapter.prepare(deepcopy(public_case(case))), "prepared bindings")
            except Exception as exc:
                return stop("blocked", "prepare_error", exc, unsettled=True)
            result["bindings"], result["prepared"] = bindings, True
            save()

        # There is no safe inference that an in-flight command was never sent.
        for action in result["actions"]:
            if action["status"] == "in_flight":
                try:
                    receipt = adapter.recover(deepcopy(action["request"]))
                    if receipt is None:
                        return stop("blocked", "unresolved_action", "original command has no verified receipt",
                                    unsettled=True)
                    bindings = _dictionary(receipt, "recovered bindings")
                except Exception as exc:
                    return stop("blocked", "recovery_error", exc, unsettled=True)
                action.update(status="committed", bindings=bindings, committed_at=now(), recovered=True)
                result["bindings"] = deepcopy(bindings)
                save()

        limits = case["limits"]

        def capture_skip(item):
            step = next(step for step in case["steps"] if step["id"] == item["step_id"])
            try:
                data = _dictionary(adapter.collect(deepcopy(item["observation"]), deepcopy(item["capture_bindings"])),
                                   "skipped step facts")
            except Exception as exc:
                return stop("blocked", "capture_error", exc)
            _append_skip_capture(result, item, step, data)
            save()
            return None

        for item in result["steps"]:
            if item["status"] == "skipped" and item["capture_status"] == "pending":
                stopped = capture_skip(item)
                if stopped is not None:
                    return stopped

        def budget_gate():
            reason = _budget_reason(result, limits, elapsed())
            if reason:
                return stop("waiting" if reason == "wait_timeout" else "blocked", reason,
                            "local Trial time or reported model-call budget exhausted")
            return None

        def submit(action):
            if not execute:
                return stop("blocked", "execution_not_authorized", "sending actions requires execute=True")
            gate = budget_gate()
            if gate is not None:
                return gate
            action["status"] = "in_flight"
            action["submitted_at"] = now()
            result["settled"] = False
            save()  # Exact request and command ID reach disk before the external call.
            try:
                bindings = _dictionary(adapter.act(deepcopy(action["request"])), "action receipt bindings")
            except Exception as exc:
                return stop("blocked", "action_outcome_unknown", exc, unsettled=True)
            action.update(status="committed", bindings=bindings, committed_at=now())
            result["bindings"] = deepcopy(bindings)
            save()
            return None

        while True:
            try:
                observation = validate_observation(adapter.observe(deepcopy(result["bindings"])))
                _record_model_calls(result, observation)
            except Exception as exc:
                return stop("blocked", "observation_error", exc, unsettled=True)
            result["observations"].append({"observation": deepcopy(observation), "observed_at": now()})
            safe = observation["state"] in {"waiting", "terminal"}
            unresolved = any(action["status"] == "in_flight" for action in result["actions"])
            result["settled"] = safe and not unresolved
            selected = next((item for item in result["steps"] if item["status"] == "selected"), None)
            active = next((action for action in result["actions"]
                           if selected and action["action_id"] == selected["action_id"]), None)
            checkpoints = _declared_checkpoints(case, observation)
            if safe and active and active["status"] == "committed":
                step = next(step for step in case["steps"] if step["id"] == selected["step_id"])
                if step["checkpoint"] not in checkpoints:
                    checkpoints.append(step["checkpoint"])
            if checkpoints:
                try:
                    data = _dictionary(adapter.collect(deepcopy(observation), deepcopy(result["bindings"])),
                                       "collected facts")
                except Exception as exc:
                    return stop("blocked", "capture_error", exc)
                _append_evidence(result, observation, data, checkpoints)
            if _settle_step(result, observation):
                save()
                selected, active = None, None
            else:
                save()
            if observation["state"] == "blocked":
                return stop("blocked", "adapter_blocked", observation.get("error", "adapter is blocked"),
                            unsettled=True)
            if observation["state"] == "terminal" and (observation.get("outcome") == "failed"
                    or observation.get("outcome") not in case["completion"]["outcomes"]):
                return stop("failed", "terminal_outcome", observation.get("outcome", "missing terminal outcome"))

            overruns = trial_budget_overruns(result, limits, elapsed=elapsed())
            if overruns:
                reason = overruns[0]
                return stop("waiting" if reason == "wait_timeout" else "blocked", reason,
                            "known Trial usage exceeds its fixed budget; in-flight work may still be running")

            if selected:
                if active is None:
                    if not execute:
                        return stop("blocked", "execution_not_authorized", "building a new action requires execute=True")
                    # A pre-build crash must not choose a different branch or version.
                    snapshot = selected["selection"]
                    step = next(step for step in case["steps"] if step["id"] == selected["step_id"])
                    try:
                        request = _dictionary(adapter.build_action(deepcopy(step), deepcopy(snapshot["observation"]),
                                                                  deepcopy(snapshot["bindings"]), selected["action_id"]),
                                              "built action request")
                    except Exception as exc:
                        return stop("blocked", "build_action_error", exc)
                    active = {"action_id": selected["action_id"], "step_id": selected["step_id"],
                              "status": "prepared", "request": request, "prepared_at": now()}
                    result["actions"].append(active)
                    save()
                if active["status"] == "prepared":
                    stopped = submit(active)
                    if stopped is not None:
                        return stopped
                    continue
                # A committed request is not a settled step while work is running.
            else:
                while True:
                    pending = next((item for item in result["steps"] if item["status"] == "pending"), None)
                    if pending is None:
                        if _is_complete(case, observation):
                            result.update(stage="completed", error=None, settled=True)
                            save()
                            return result
                        if safe:
                            return stop("failed" if observation["state"] == "terminal" else "waiting",
                                        "completion_not_met", "Case completion condition is not satisfied")
                        break
                    step = next(step for step in case["steps"] if step["id"] == pending["step_id"])
                    matches = _matches(step["when"], observation) and step["action"] in observation["actions"]
                    if not matches:
                        if safe and step["optional"]:
                            pending.update(status="skipped", skipped_at=now(), observation=deepcopy(observation),
                                           capture_status="pending", capture_bindings=deepcopy(result["bindings"]))
                            save()
                            stopped = capture_skip(pending)
                            if stopped is not None:
                                return stopped
                            continue
                        if safe:
                            return stop("failed" if observation["state"] == "terminal" else "waiting",
                                        "step_not_available", f"required step is not available: {step['id']}")
                        break
                    if not execute:
                        return stop("blocked", "execution_not_authorized", "sending actions requires execute=True")
                    gate = budget_gate()
                    if gate is not None:
                        return gate
                    if len(result["actions"]) >= limits["max_actions"]:
                        return stop("blocked", "action_limit", "Trial action budget exhausted")
                    pending.update(status="selected", action_id=str(uuid4()), selected_at=now(),
                                   selection={"observation": deepcopy(observation),
                                              "bindings": deepcopy(result["bindings"])})
                    save()  # Freeze branch, command identity and binding versions before building.
                    selected = pending
                    break
                if selected:
                    continue
            if elapsed() >= limits["wait_seconds"]:
                return stop("waiting", "wait_timeout", "work has not reached a safe completion state")
            time.sleep(min(limits["poll_seconds"], max(0, limits["wait_seconds"] - elapsed())))
