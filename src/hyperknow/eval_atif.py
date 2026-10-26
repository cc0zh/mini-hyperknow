"""Local ATIF-v1.7 text subset, mapped from RecordedTeachingModel snapshots.

Specification: harbor-framework/harbor@872da9479f4a2078142d22c49c9ffae0f09e2e63.
Evidence references address flattened model_calls entries in the caller's result;
they are not filesystem paths. No provider, hidden reasoning, or grader is used.
"""

from datetime import datetime
import json
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Count = Annotated[int, Field(ge=0)]
Cost = Annotated[float, Field(ge=0)]
METRICS = ("prompt_tokens", "completion_tokens", "cached_tokens", "cost_usd")


class _Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class _Agent(_Model):
    name: Text
    version: Text
    model_name: Text | None = None


class _Tool(_Model):
    tool_call_id: Text
    function_name: Text
    arguments: dict


class _Result(_Model):
    source_call_id: Text
    content: str
    extra: dict | None = None


class _Observation(_Model):
    results: Annotated[list[_Result], Field(min_length=1)]


class _Metrics(_Model):
    prompt_tokens: Count | None = None
    completion_tokens: Count | None = None
    cached_tokens: Count | None = None
    cost_usd: Cost | None = None


class _Final(_Model):
    total_steps: Count
    total_prompt_tokens: Count | None = None
    total_completion_tokens: Count | None = None
    total_cached_tokens: Count | None = None
    total_cost_usd: Cost | None = None


class _Step(_Model):
    step_id: Annotated[int, Field(ge=1)]
    source: Literal["system", "user", "agent"]
    message: str
    timestamp: str | None = None
    model_name: Text | None = None
    llm_call_count: Annotated[int, Field(ge=1, le=1)] | None = None
    tool_calls: Annotated[list[_Tool], Field(min_length=1)] | None = None
    observation: _Observation | None = None
    metrics: _Metrics | None = None
    extra: dict | None = None


class _Trajectory(_Model):
    schema_version: Literal["ATIF-v1.7"]
    session_id: Text
    trajectory_id: Text
    agent: _Agent
    steps: Annotated[list[_Step], Field(min_length=1)]
    final_metrics: _Final
    notes: str | None = None
    extra: dict | None = None


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json(value):
    if isinstance(value, dict):
        _require(all(type(key) is str for key in value), "JSON keys must be strings")
        for item in value.values():
            _json(item)
    elif isinstance(value, list):
        for item in value:
            _json(item)
    else:
        _require(value is None or type(value) in (str, int, float, bool), "Expected plain JSON data")


def _metrics(data):
    _require(data is None or isinstance(data, dict), "usage must be an object or null")
    values = _Metrics.model_validate({k: v for k, v in (data or {}).items() if k in METRICS})
    if values.cached_tokens is not None:
        _require(values.prompt_tokens is not None and values.cached_tokens <= values.prompt_tokens,
                 "cached_tokens must be a subset of prompt_tokens")
    if data and "total_tokens" in data:
        total = data["total_tokens"]
        _require(type(total) is int and total >= 0, "Invalid total_tokens")
        if values.prompt_tokens is not None and values.completion_tokens is not None:
            _require(total == values.prompt_tokens + values.completion_tokens, "Inconsistent total_tokens")
    return values.model_dump(exclude_none=True)


def validate_trajectory(data: dict) -> dict:
    """Validate only this project's v1.7 text subset; return independent plain data."""
    _json(data)
    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, OverflowError) as exc:
        raise ValueError("Invalid JSON data") from exc
    trajectory = _Trajectory.model_validate(data)
    agents, seen = [], set()
    for index, step in enumerate(trajectory.steps, 1):
        _require(step.step_id == index, "step_id must be sequential from 1")
        if step.timestamp is not None:
            parsed = datetime.fromisoformat(step.timestamp.replace("Z", "+00:00"))
            _require("T" in step.timestamp and parsed.tzinfo is not None, "Expected ISO timestamp with timezone")
        if step.source != "agent":
            _require(all(getattr(step, key) is None for key in
                         ("model_name", "llm_call_count", "tool_calls", "observation", "metrics")),
                     "Agent-only fields on a non-agent step")
            continue
        _require(type(step.llm_call_count) is int and step.llm_call_count == 1,
                 "This subset requires exactly one inference per agent step")
        agents.append(step)
        ids = [tool.tool_call_id for tool in step.tool_calls or []]
        _require(len(ids) == len(set(ids)) and not seen.intersection(ids), "Conflicting tool identity")
        seen.update(ids)
        results = [result.source_call_id for result in step.observation.results] if step.observation else []
        _require(len(results) == len(set(results)) and set(results) <= set(ids),
                 "Observation must reference a unique tool call on the same step")
        _metrics(step.metrics.model_dump(exclude_none=True) if step.metrics else None)
    _require(agents, "No representable model calls")
    _require(trajectory.final_metrics.total_steps == len(trajectory.steps), "Incorrect total_steps")
    for key in METRICS:
        total = getattr(trajectory.final_metrics, f"total_{key}")
        if total is not None:
            values = [getattr(step.metrics, key) if step.metrics else None for step in agents]
            _require(all(value is not None for value in values) and total == sum(values),
                     f"Incomplete or incorrect total_{key}")
    return trajectory.model_dump(mode="json", exclude_unset=True)


def _response(response):
    _require(isinstance(response, dict) and response.get("role") == "assistant", "Expected recorded assistant response")
    _require(isinstance(response["content"], str), "Only text responses are supported")
    _require(isinstance(response["tool_calls"], list) and
             response["stop_reason"] in ("stop", "tool_use", "error", "aborted"), "Invalid recorded response envelope")
    tools = [_Tool.model_validate({"tool_call_id": tool["id"], "function_name": tool["name"],
                                   "arguments": tool["arguments"]}).model_dump()
             for tool in response["tool_calls"]]
    return response["content"], tools


def export_trajectory(run: dict, calls: list[dict], *, execution_id: str, agent_version: str) -> dict:
    """Export flattened snapshots in SQLite rowid order, cross-checked against attempts.

    Completeness covers supplied calls/observations only. Original tool output and
    provider-wire context completeness remain unknown; raw snapshots stay in result evidence.
    """
    try:
        return _export(run, calls, execution_id, agent_version)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError(f"Malformed recorded call: {exc}") from exc


def _export(run, calls, execution_id, agent_version):
    _json(run)
    _json(calls)
    json.dumps([run, calls], allow_nan=False)
    _require(run["kind"] == "assistance" and isinstance(run["input"], dict), "Only assistance runs are supported")
    _require(isinstance(calls, list) and calls, "No representable model calls")
    _require(all(isinstance(run[key], str) and run[key] for key in ("run_id", "conversation_id", "turn_id")),
             "Missing business identity")
    _require(all(type(call["attempt"]) is int and call["attempt"] > 0 for call in calls), "Invalid call attempt")
    _require(all(left["attempt"] < right["attempt"] for left, right in zip(calls, calls[1:])),
             "Calls must retain SQLite insertion order with increasing attempts")
    _require(all(isinstance(call["id"], str) and call["id"] for call in calls)
             and len({call["id"] for call in calls}) == len(calls), "Conflicting call identity")
    steps, owners, observations, responses = [], {}, {}, []
    previous, system = [], None

    def add(source, message, ref, **fields):
        step = {"step_id": len(steps) + 1, "source": source, "message": message,
                "extra": {"mini_hyperknow": {"evidence_ref": ref}}, **fields}
        steps.append(step)
        return step

    for call in calls:
        base = f"model_calls/{call['id']}"
        _require(call["kind"] == "assistance" and call["input_basis"] == run["input"], "Call/run identity conflict")
        for key in ("run_id", "conversation_id", "turn_id"):
            _require(key not in call or call[key] == run[key], f"Conflicting {key}")
        _require(isinstance(call["system_prompt"], str) and isinstance(call["messages"], list)
                 and isinstance(call["tools"], list), "Invalid context snapshot")
        same_system = system == call["system_prompt"]
        if not same_system and call["system_prompt"]:
            add("system", call["system_prompt"], f"{base}/system_prompt")
        prefix = 0
        if same_system:
            while prefix < min(len(previous), len(call["messages"])) and previous[prefix] == call["messages"][prefix]:
                prefix += 1
        system, result_ids = call["system_prompt"], set()
        for index, message in enumerate(call["messages"]):
            ref = f"{base}/messages/{index}"
            _require(isinstance(message["content"], str), "Only text context is supported")
            if message["role"] == "user":
                if index >= prefix:
                    add("user", message["content"], ref)
            elif message["role"] == "assistant":
                _require(_response(message) in responses, "Unrecorded or conflicting historical assistant action")
            elif message["role"] == "tool_result":
                tool_id = message["tool_call_id"]
                _require(tool_id in owners and tool_id not in result_ids, "Orphan or duplicate tool result")
                _require(type(message["is_error"]) is bool, "Invalid tool error flag")
                result_ids.add(tool_id)
                if tool_id in observations:
                    saved = observations[tool_id]
                    _require((saved["content"], saved["extra"]["mini_hyperknow"]["is_error"]) ==
                             (message["content"], message["is_error"]), "Conflicting tool observations")
                    saved["extra"]["mini_hyperknow"]["evidence_refs"].append(ref)
                else:
                    saved = {"source_call_id": tool_id, "content": message["content"],
                             "extra": {"mini_hyperknow": {"evidence_refs": [ref], "is_error": message["is_error"],
                                                         "original_truncation": "unknown"}}}
                    owners[tool_id].setdefault("observation", {"results": []})["results"].append(saved)
                    observations[tool_id] = saved
            else:
                raise ValueError("Unsupported context role")
        response = call["response"]
        content, tools = _response(response)
        for key in ("model", "provider", "usage", "stop_reason"):
            _require(key not in call or key not in response or call[key] == response[key],
                     f"Conflicting response {key}")
        metrics = _metrics(call["usage"])
        step = add("agent", content, f"{base}/response", timestamp=call["created_at"], llm_call_count=1)
        metadata = step["extra"]["mini_hyperknow"]
        metadata.update(call_id=call["id"], attempt=call["attempt"],
                        context_refs={key: f"{base}/{key}" for key in ("system_prompt", "messages", "tools", "input_basis")},
                        skill_uses_ref=f"{base}/skill_uses", stop_reason=response["stop_reason"])
        if response.get("error_message") is not None:
            metadata["error_message"] = response["error_message"]
        model = response.get("model") or call.get("model")
        if model is not None:
            step["model_name"] = model
        if metrics:
            step["metrics"] = metrics
        if tools:
            step["tool_calls"] = tools
        for tool in tools:
            _require(tool["tool_call_id"] not in owners, "Reused tool call identity")
            owners[tool["tool_call_id"]] = step
        responses.append((content, tools))
        previous = call["messages"] + [response]
    agents = [step for step in steps if step["source"] == "agent"]
    final = {"total_steps": len(steps)}
    for key in METRICS:
        if all(key in step.get("metrics", {}) for step in agents):
            final[f"total_{key}"] = sum(step["metrics"][key] for step in agents)
    missing = [tool_id for tool_id in owners if tool_id not in observations]
    attempts = {call["attempt"] for call in calls}
    gaps = sorted(set(range(1, max(attempts) + 1)) - attempts)
    return validate_trajectory({
        "schema_version": "ATIF-v1.7", "session_id": execution_id,
        "trajectory_id": str(uuid5(NAMESPACE_URL, json.dumps([execution_id, run["run_id"]]))),
        "agent": {"name": "mini-hyperknow-assistance", "version": agent_version},
        "steps": steps, "final_metrics": final,
        "notes": "Recorded text only; effective context is referenced per call, not inferred from the step prefix. "
                 "Completeness is relative to supplied records; original tool text truncation is unknown.",
        "extra": {"mini_hyperknow": {
            **{key: run[key] for key in ("run_id", "conversation_id", "turn_id")},
            "converter_version": "1", "validator_version": "1",
            "spec_commit": "872da9479f4a2078142d22c49c9ffae0f09e2e63",
            "call_ids": [call["id"] for call in calls], "missing_observations": missing,
            "missing_call_attempts": gaps, "complete": not missing and not gaps,
            "usage_complete": all(f"total_{key}" in final for key in METRICS[:2]),
        }},
    })
