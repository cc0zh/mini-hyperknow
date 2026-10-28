"""ATIF-v1.7 text exports for recorded product calls, not simulated execution."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from eval_core.evidence import validate_evidence
from eval_core.store import digest, exclusive, read_json, write_json

from .eval_atif import validate_trajectory


METRICS = ("prompt_tokens", "completion_tokens", "cached_tokens", "cost_usd")


def export_recorded_run(run: dict, calls: list[dict], *, trial_id: str, subject: dict) -> dict:
    if not calls or not run.get("run_id") or not run.get("kind"):
        raise ValueError("missing run identity or representable recorded calls")
    ids = [call.get("id") for call in calls]
    if any(not isinstance(identity, str) or not identity for identity in ids) or len(ids) != len(set(ids)):
        raise ValueError("missing or duplicate call identities")
    if any(call.get("run_id") != run["run_id"] for call in calls):
        raise ValueError("call belongs to another business run")
    steps, owners, observations = [], {}, {}
    previous, system = [], None
    gaps = []

    def add(source, message, reference, **fields):
        if not isinstance(message, str):
            raise ValueError("only recorded text is representable")
        item = {"step_id": len(steps) + 1, "source": source, "message": message,
                "extra": {"mini_hyperknow": {"evidence_ref": reference}}, **fields}
        steps.append(item)
        return item

    for call in calls:
        base = f"model_calls/{call['id']}"
        prompt, messages = call.get("system_prompt"), call.get("messages")
        if not isinstance(prompt, str) or not isinstance(messages, list):
            raise ValueError("missing effective context snapshot")
        same = system == prompt
        if not same and prompt:
            add("system", prompt, base + "/system_prompt")
        prefix = 0
        if same:
            while prefix < min(len(previous), len(messages)) and previous[prefix] == messages[prefix]:
                prefix += 1
        system = prompt
        for index, message in enumerate(messages):
            reference = f"{base}/messages/{index}"
            # Structured generation records only UserMessage.content strings,
            # including explicitly labelled repair requests, not assistant calls.
            if isinstance(message, str):
                if index >= prefix:
                    add("user", message, reference)
                continue
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("unsupported recorded context shape")
            role = message.get("role")
            if role == "user":
                if index >= prefix:
                    add("user", message["content"], reference)
            elif role == "tool_result":
                identity = message.get("tool_call_id")
                if identity in owners:
                    if type(message.get("is_error")) is not bool:
                        raise ValueError("invalid tool error flag")
                    if identity in observations:
                        if observations[identity]["content"] != message["content"]:
                            raise ValueError("conflicting tool observations")
                        continue
                    result = {"source_call_id": identity, "content": message["content"],
                              "extra": {"mini_hyperknow": {"evidence_ref": reference,
                                         "is_error": message["is_error"]}}}
                    owners[identity].setdefault("observation", {"results": []})["results"].append(result)
                    observations[identity] = result
                elif index >= prefix:
                    add("system", "Frozen historical tool context (not a current-run tool action):\n"
                        + json.dumps(message, ensure_ascii=False), reference)
            elif role == "assistant":
                # The effective request remains in evidence. Do not count prior
                # conversation answers as new calls belonging to this run.
                if index >= prefix:
                    add("system", "Frozen historical assistant context (not a current-run model call):\n"
                        + json.dumps(message, ensure_ascii=False), reference)
            else:
                raise ValueError("unsupported context role")
        response = call.get("response")
        if isinstance(response, str):
            content, tools, envelope = response, [], None
        elif isinstance(response, dict) and response.get("role") == "assistant":
            content, envelope = response.get("content"), response
            raw_tools = response.get("tool_calls", [])
            if not isinstance(raw_tools, list):
                raise ValueError("invalid recorded tool calls")
            tools = [{"tool_call_id": tool["id"], "function_name": tool["name"],
                      "arguments": deepcopy(tool["arguments"])} for tool in raw_tools]
            for key in ("model", "usage", "stop_reason"):
                if key in call and key in response and call[key] != response[key]:
                    raise ValueError("conflicting response metadata")
        elif response is None and call.get("stop_reason") == "error":
            gaps.append({"call_id": call["id"], "reason": "provider response missing"})
            add("system", "Recorded provider failure; response unavailable.", base)
            previous = messages
            continue
        else:
            raise ValueError("unsupported recorded response")
        fields = {"llm_call_count": 1}
        if call.get("created_at"):
            fields["timestamp"] = call["created_at"]
        if call.get("model"):
            fields["model_name"] = call["model"]
        metrics = {key: value for key, value in (call.get("usage") or {}).items() if key in METRICS}
        if metrics:
            fields["metrics"] = metrics
        if tools:
            fields["tool_calls"] = tools
        item = add("agent", content, base + "/response", **fields)
        item["extra"]["mini_hyperknow"].update(call_id=call["id"], phase=call.get("phase"),
            recorded_attempt=call.get("attempt"), context_ref=base, stop_reason=call.get("stop_reason"))
        for tool in tools:
            identity = tool["tool_call_id"]
            if identity in owners:
                raise ValueError("duplicate tool call identity")
            owners[identity] = item
        previous = messages + ([envelope] if envelope else [])
    agents = [step for step in steps if step["source"] == "agent"]
    final = {"total_steps": len(steps)}
    for key in METRICS:
        if agents and not gaps and all(key in item.get("metrics", {}) for item in agents):
            final[f"total_{key}"] = sum(item["metrics"][key] for item in agents)
    missing = sorted(set(owners) - set(observations))
    return validate_trajectory({"schema_version": "ATIF-v1.7", "session_id": trial_id,
        "trajectory_id": str(uuid5(NAMESPACE_URL, json.dumps([trial_id, run["run_id"]]))),
        "agent": {"name": "mini-hyperknow-" + run["kind"], "version": "subject-sha256:" + digest(subject)},
        "steps": steps, "final_metrics": final,
        "notes": "Recorded text subset only. Historical request context is not a new model call. "
                 "Completeness concerns provided records, not absence of unrecorded calls or source truncation.",
        "extra": {"mini_hyperknow": {"run_id": run["run_id"], "converter_version": "2",
            "validator_version": "1", "spec_commit": "872da9479f4a2078142d22c49c9ffae0f09e2e63",
            "call_ids": ids, "missing_observations": missing, "gaps": gaps,
            "complete": not missing and not gaps, "source_recording_complete": "unknown"}}})


def export_trial_trajectories(output: Path) -> dict:
    path = output if output.suffix == ".json" else output / "result.json"
    with exclusive(path.parent / ".writer.lock"):
        result = read_json(path)
        runs, calls = {}, {}
        for evidence in result["evidence"]:
            validate_evidence(evidence)
            data = evidence["data"]
            runs.update(data.get("runs", {}))
            for call in data.get("calls", []):
                if call["id"] in calls and calls[call["id"]] != call:
                    raise ValueError("conflicting immutable call snapshots")
                calls[call["id"]] = call
        exports = {}
        for run_id, run in runs.items():
            selected = [call for call in calls.values() if call.get("run_id") == run_id]
            try:
                trajectory = export_recorded_run(run, selected, trial_id=result["trial_id"], subject=result["subject"])
                # Product identifiers are validated by the adapter, but hash paths
                # here as well so evidence can never direct writes outside output.
                relative = "trajectories/" + digest(run_id) + ".json"
                write_json(path.parent / relative, trajectory)
                exports[run_id] = {"path": relative, "sha256": digest(trajectory), "valid": True,
                                  "complete": trajectory["extra"]["mini_hyperknow"]["complete"]}
            except (ValueError, KeyError, TypeError) as exc:
                exports[run_id] = {"valid": False, "complete": False, "error": type(exc).__name__}
        result["trajectories"] = exports
        write_json(path, result)
        return result
