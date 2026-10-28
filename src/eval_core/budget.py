"""Known Trial overruns, independent of product semantics or provider guarantees."""

import math


def trial_budget_overruns(result: dict, limits: dict, *, elapsed=None) -> list[str]:
    """Check measured facts, not just a previously emitted error/budget flag.

    Persisted calls are a lower bound; absent records never prove zero usage.
    Equality permits completion, while the runner separately gates new actions.
    """
    budget = result.get("budget") or {}
    budget = budget if isinstance(budget, dict) else {}
    counts = [value for key in ("model_calls", "last_reported_model_calls")
              if type(value := budget.get(key)) is int and value >= 0]
    call_ids = set()
    for evidence in result.get("evidence", []):
        data = evidence.get("data", {}) if isinstance(evidence, dict) else {}
        calls = data.get("calls", []) if isinstance(data, dict) else []
        if isinstance(calls, list):
            call_ids.update(call["id"] for call in calls if isinstance(call, dict)
                            and isinstance(call.get("id"), str) and call["id"])
    if call_ids:
        counts.append(len(call_ids))
    errors = []
    if counts and max(counts) > limits["max_model_calls"]:
        errors.append("model_call_limit")
    actions = result.get("actions", [])
    if isinstance(actions, list) and len(actions) > limits["max_actions"]:
        errors.append("action_limit")
    elapsed = budget.get("elapsed_seconds") if elapsed is None else elapsed
    if (type(elapsed) in (int, float) and math.isfinite(elapsed)
            and elapsed > limits["wait_seconds"]):
        errors.append("wait_timeout")
    return errors
