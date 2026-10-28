"""Offline reports over complete trial plans; no execution or network dependencies."""

from collections import Counter, defaultdict
from copy import deepcopy

from .budget import trial_budget_overruns
from .contracts import validate_case
from .grading import (PROMPT_VERSION, _applicable, _missing, _selected_view, _validate_result,
                      evidence_set_hash, evidence_view)
from .store import digest


def _latest(result):
    grades = result.get("grades", [])
    return grades[-1] if isinstance(grades, list) and grades and isinstance(grades[-1], dict) else {}


def _repetition(result):
    binding = result.get("experiment", {})
    if not isinstance(binding, dict):
        raise ValueError("Invalid experiment binding")
    direct, bound = result.get("repetition"), binding.get("repetition")
    if direct is not None and bound is not None and direct != bound:
        raise ValueError("Conflicting repetition identities")
    value = direct if direct is not None else bound if bound is not None else 1
    if type(value) is not int or value < 1:
        raise ValueError("repetition must be a positive integer")
    return value


def _usage(attempts):
    calls = [item for item in attempts if isinstance(item, dict) and item.get("request") is not None]
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    known, complete = {}, {}
    for key in fields:
        values = [item["usage"].get(key) if isinstance(item.get("usage"), dict) else None for item in calls]
        measured = [value for value in values if type(value) is int and value >= 0]
        known[key] = sum(measured) if measured else None
        complete[key] = sum(measured) if values and len(measured) == len(values) else None
    return {"attempts_with_request": len(calls), "unknown_usage_attempts": sum(not item.get("usage") for item in calls),
            "usage": complete, "known_usage": known}


def _business_usage(result):
    """Call identity, not checkpoint count, determines measured business usage."""
    unique, conflicts, gaps = {}, set(), []
    for evidence in result.get("evidence", []):
        data = evidence.get("data", {}) if isinstance(evidence, dict) else {}
        if not isinstance(data, dict):
            continue
        gaps.extend(data.get("gaps", []) if isinstance(data.get("gaps", []), list) else [])
        for call in data.get("calls", []) if isinstance(data.get("calls", []), list) else []:
            if not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]:
                gaps.append("model call lacks a stable id")
                continue
            if call["id"] in unique and unique[call["id"]] != call:
                conflicts.add(call["id"])
            unique[call["id"]] = call
    calls = [{"request": True, "usage": None if identity in conflicts else call.get("usage")}
             for identity, call in unique.items()]
    measured = _usage(calls)
    measured["calls"] = measured.pop("attempts_with_request")
    measured["unknown_usage_calls"] = measured.pop("unknown_usage_attempts")
    return {**measured, "conflicting_call_ids": sorted(conflicts), "coverage": "saved_calls_only",
            "gaps": sorted({str(gap) for gap in gaps}), "reported_trial_usage": deepcopy(result.get("usage"))}


def summarize_trial(result: dict) -> dict:
    """Keep content failures, execution problems and measurement errors distinct."""
    measurement, execution = [], []
    try:
        case = validate_case(result.get("case", {}))
        if result.get("schema_version") != 2 or digest(case) != result.get("case_hash"):
            raise ValueError("Case identity mismatch")
    except (ValueError, TypeError, KeyError):
        case = {"id": None, "version": None, "checks": []}
        measurement.append({"type": "identity_error", "message": "Invalid Case/schema/hash"})
    try:
        view = evidence_view(result)
        current_evidence_hash = evidence_set_hash(result)
    except (ValueError, TypeError, KeyError):
        view = {}
        current_evidence_hash = None
        measurement.append({"type": "evidence_error", "message": "Invalid frozen evidence identity or hash"})
    attempt = _latest(result)
    grading_current = bool(current_evidence_hash and attempt.get("evidence_set_hash") == current_evidence_hash)
    if attempt and not grading_current:
        measurement.append({"type": "stale_grading",
                            "message": "Grading is unbound or frozen evidence changed; explicit regrade required"})
    if not attempt:
        measurement.append({"type": "missing_grading", "message": "No grading attempt is available"})
    elif attempt.get("status") != "completed" or attempt.get("error"):
        measurement.append({"type": "grader_error", "status": attempt.get("status"),
                            "error": deepcopy(attempt.get("error"))})
    if attempt and (not isinstance(attempt.get("attempt_id"), str) or not attempt["attempt_id"].strip()
                    or not isinstance(attempt.get("definition_hash"), str) or not attempt["definition_hash"].strip()):
        measurement.append({"type": "grader_identity_error", "message": "Missing attempt identity or definition hash"})
    if attempt and case["checks"]:
        config = attempt.get("config")
        config = {key: value for key, value in config.items()
                  if key not in {"max_retries", "token_limit_parameter"}} if isinstance(config, dict) else config
        expected = digest({"checks": case["checks"], "reference_facts": case["reference_facts"],
                           "prompt_version": attempt.get("prompt_version"), "config": config})
        if attempt.get("definition_hash") != expected:
            measurement.append({"type": "grader_identity_error", "message": "Grading definition hash mismatch"})
    items = attempt.get("results", [])
    if not isinstance(items, list):
        items = []
        measurement.append({"type": "invalid_grades", "message": "Results are not a list"})
    by_id = defaultdict(list)
    known_ids = {check["check_id"] for check in case["checks"]}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("check_id"), str) or item["check_id"] not in known_ids:
            measurement.append({"type": "invalid_grades", "message": "Unknown or malformed check result"})
        else:
            by_id[item["check_id"]].append(item)
    checks = []
    for check in case["checks"]:
        matches = by_id[check["check_id"]]
        if attempt and not grading_current:
            item = {"verdict": "undetermined", "reason": "stale_grading: explicit regrade required", "evidence_refs": []}
        elif len(matches) != 1:
            item = {"verdict": "undetermined", "reason": "Missing or duplicate check result", "evidence_refs": []}
            measurement.append({"type": "incomplete_grading", "check_id": check["check_id"]})
        else:
            item = matches[0]
        if item.get("verdict") not in ("pass", "fail", "undetermined", "not_applicable"):
            item = {"verdict": "undetermined", "reason": "Invalid verdict", "evidence_refs": []}
            measurement.append({"type": "invalid_grades", "check_id": check["check_id"]})
        elif item.get("verdict") in ("pass", "fail", "not_applicable"):
            try:
                if item["verdict"] == "not_applicable":
                    selected = _selected_view(check, view)
                    if _missing(check, selected) or _applicable(check, selected) is not False:
                        raise ValueError("Unsupported not_applicable")
                else:
                    if _missing(check, _selected_view(check, view)):
                        raise ValueError("Missing required checkpoints or projected fields")
                    _validate_result(item, check, view)
            except (ValueError, TypeError, KeyError):
                measurement.append({"type": "invalid_grade_evidence", "check_id": check["check_id"]})
                item = {"verdict": "undetermined", "reason": "Invalid grading evidence", "evidence_refs": []}
        checks.append({"check_id": check["check_id"], "version": check["version"], "kind": check["kind"],
                       "evaluator": check["evaluator"], "required": check["required"], **deepcopy(item)})
    grades = result.get("grades", []) if isinstance(result.get("grades", []), list) else []
    budgets = [result.get("budget_check", {}), *[grade.get("budget_check", {})
                                               for grade in grades if isinstance(grade, dict)]]
    budget_exceeded = any(isinstance(item, dict) and item.get("status") == "exceeded" for item in budgets)
    if "limits" in case and trial_budget_overruns(result, case["limits"]):
        budget_exceeded = True
    for grade in grades:
        if not isinstance(grade, dict):
            continue
        config, usage = grade.get("config"), grade.get("usage")
        limit = config.get("max_output_tokens") if isinstance(config, dict) else None
        reported = usage.get("completion_tokens") if isinstance(usage, dict) else None
        if type(limit) is int and limit > 0 and type(reported) is int and reported > limit:
            budget_exceeded = True
    budget_error = result.get("error") or {}
    if isinstance(budget_error, dict) and budget_error.get("code") in {"model_call_limit", "action_limit", "wait_timeout"}:
        budget_exceeded = True
    if budget_exceeded:
        measurement.append({"type": "budget_exceeded", "message": "A reported trial/grading budget was exceeded"})
    if result.get("settled") is not True:
        execution.append({"type": "unsettled", "message": "Business execution has not been confirmed settled"})
    if result.get("stage") != "completed":
        execution.append({"type": "execution_incomplete", "stage": result.get("stage"),
                          "error": deepcopy(result.get("error")), "reason": result.get("blocked_reason")})
    failures = [item["check_id"] for item in checks if item["verdict"] == "fail"]
    pending = [item["check_id"] for item in checks if item["required"] and item["verdict"] != "pass"]
    business_status = "failed" if failures else "passed" if checks and not pending else "undetermined"
    passed = business_status == "passed" and not measurement and not execution
    status = "passed" if passed else "failed" if failures else "blocked" if result.get("stage") == "blocked" else "unresolved"
    try:
        repetition = _repetition(result)
    except ValueError:
        repetition = None
        measurement.append({"type": "identity_error", "message": "Invalid repetition identity"})
        passed, status = False, "unresolved"
    return {"trial_id": result.get("trial_id"), "case_id": case["id"], "case_version": case["version"],
            "case_hash": result.get("case_hash"), "subject": deepcopy(result.get("subject")),
            "repetition": repetition, "stage": result.get("stage"), "settled": result.get("settled") is True,
            "status": status, "passed": passed, "business_status": business_status,
            "business_failures": failures, "required_not_passed": pending, "checks": checks,
            "measurement_errors": measurement, "execution_errors": execution,
            "attempt_id": attempt.get("attempt_id"), "definition_hash": attempt.get("definition_hash"),
            "grading_current": grading_current,
            "calibration_status": attempt.get("calibration_status", "unreviewed"),
            "budget_exceeded": budget_exceeded, "grading_usage": _usage(grades),
            "business_usage": _business_usage(result)}


def _policy(result):
    if "environment_policy" in result:
        return result["environment_policy"]
    environment = result.get("environment", {})
    return environment.get("policy", environment) if isinstance(environment, dict) else None


def _comparison_identity(result):
    case = validate_case(result["case"])
    if result.get("schema_version") != 2 or result.get("case_hash") != digest(case):
        raise ValueError("invalid_case_identity")
    definition = _latest(result).get("definition_hash") or result.get("grading_definition_hash")
    if not isinstance(definition, str) or not definition.strip():
        raise ValueError("missing_grading_definition")
    prerequisites = digest(case["prerequisites"])
    if result.get("prerequisites_hash", prerequisites) != prerequisites:
        raise ValueError("prerequisite_identity_mismatch")
    policy = _policy(result)
    if not policy or policy == "unknown":
        raise ValueError("unknown_environment_policy")
    environment = result.get("environment") or {}
    fixture = environment.get("fixture_snapshot_sha256") or result.get("fixture_snapshot_sha256")
    if not fixture and case["prerequisites"]:
        raise ValueError("unknown_fixture_identity")
    return {"case_hash": result["case_hash"], "prerequisites_hash": prerequisites, "fixture_hash": fixture,
            "grading_definition_hash": definition, "environment_policy_hash": digest(policy),
            "repetition": _repetition(result)}


def compare_results(baseline: list[dict], candidate: list[dict]) -> dict:
    """Pair fixed conditions, not subjects; retain every failed, blocked and unmatched trial."""
    sides = {"baseline": baseline, "candidate": candidate}
    groups = {name: defaultdict(list) for name in sides}
    unpaired, pairs = [], []
    identities = {}
    for side, results in sides.items():
        for index, result in enumerate(results):
            summary = summarize_trial(result)
            try:
                identity = _comparison_identity(result)
                key = digest(identity)
                groups[side][key].append((index, result, summary))
                identities[key] = identity
            except (ValueError, TypeError, KeyError) as exc:
                unpaired.append({"side": side, "trial_id": result.get("trial_id"),
                                 "reasons": [str(exc)], "summary": summary})
    for key in sorted(set(groups["baseline"]) | set(groups["candidate"])):
        left, right = groups["baseline"].get(key, []), groups["candidate"].get(key, [])
        if len(left) == len(right) == 1:
            before, after = left[0][2], right[0][2]
            change = "unchanged"
            if before["status"] == "failed" and after["passed"]:
                change = "improved"
            elif before["passed"] and after["status"] == "failed":
                change = "regressed"
            elif not before["passed"] or not after["passed"]:
                change = "unresolved" if before["status"] != after["status"] else "unchanged"
            pairs.append({**identities[key], "baseline": before, "candidate": after, "change": change})
            continue
        for side, entries, opposite in (("baseline", left, candidate), ("candidate", right, baseline)):
            for _, result, summary in entries:
                reasons = []
                if len(left) > 1 or len(right) > 1:
                    reasons.append("ambiguous_duplicate_pair")
                for other in opposite:
                    if other.get("case", {}).get("id") != result.get("case", {}).get("id"):
                        continue
                    try:
                        other_identity = _comparison_identity(other)
                    except (ValueError, TypeError, KeyError):
                        continue
                    reasons.extend(f"{field}_mismatch" for field in identities[key]
                                   if identities[key][field] != other_identity[field])
                unpaired.append({"side": side, "trial_id": result.get("trial_id"),
                                 "reasons": sorted(set(reasons)) or ["missing_counterpart"], "summary": summary})
    return {"schema_version": 2, "pairs": pairs, "unpaired": unpaired,
            "counts": {"baseline": len(baseline), "candidate": len(candidate), "paired": len(pairs),
                       "unpaired": len(unpaired), "changes": dict(Counter(pair["change"] for pair in pairs))},
            "notes": ["Paired observations only; no statistical significance or automatic version acceptance.",
                      "Subject snapshots are compared, not required to have equal hashes."]}


def build_experiment(benchmark: dict, subjects: list[dict], repetitions: int) -> dict:
    """Build a fixed full case × subject × repetition plan without executing anything.

    benchmark: {id, version, cases: [Case | {case: Case, case_hash?: str}],
                environment_policy?: str (default isolated), grading_config?: public ModelSettings fields}.
    Model-graded experiments must supply all public settings to pin the same definition hash as grading.
    subjects: nonempty JSON snapshot objects supplied by a trusted assembler (or explicit unknown).
    """
    if (not isinstance(benchmark, dict) or any(not isinstance(benchmark.get(key), str)
                                             or not benchmark[key].strip() for key in ("id", "version"))
            or not isinstance(benchmark.get("cases"), list) or not benchmark["cases"]):
        raise ValueError("A fixed benchmark id/version and nonempty cases are required")
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    if not isinstance(subjects, list) or not subjects or any(not isinstance(subject, dict) or not subject for subject in subjects):
        raise ValueError("Nonempty explicit subject snapshots are required")
    if len({digest(subject) for subject in subjects}) != len(subjects):
        raise ValueError("Duplicate subject snapshots")
    cases = []
    for member in benchmark["cases"]:
        case = validate_case(member["case"] if isinstance(member, dict) and "case" in member else member)
        if "case" in member and member.get("case_hash", digest(case)) != digest(case):
            raise ValueError("Benchmark member hash mismatch")
        cases.append(case)
    if len({digest(case) for case in cases}) != len(cases):
        raise ValueError("Duplicate benchmark Case")
    policy = deepcopy(benchmark.get("environment_policy", "isolated"))
    config = deepcopy(benchmark.get("grading_config")) or None
    if config is not None and (not isinstance(config, dict) or "api_key" in config):
        raise ValueError("Only public grading settings may be saved in an experiment")
    fixed_benchmark = {"id": benchmark["id"], "version": benchmark["version"],
                       "cases": [{"id": case["id"], "version": case["version"], "case_hash": digest(case)} for case in cases]}
    identity = {"benchmark": fixed_benchmark, "subjects": subjects, "repetitions": repetitions,
                "environment_policy": policy, "grading_config": config}
    experiment_id = "experiment-" + digest(identity)[:24]
    trials = []
    for case in cases:
        case_config = config if any(check["kind"] == "llm" for check in case["checks"]) else None
        for subject in subjects:
            for repetition in range(1, repetitions + 1):
                key = {"experiment_id": experiment_id, "case_hash": digest(case),
                       "subject_hash": digest(subject), "repetition": repetition}
                definition = digest({"checks": case["checks"], "reference_facts": case["reference_facts"],
                                     "prompt_version": PROMPT_VERSION, "config": case_config})
                trials.append({"trial_id": "trial-" + digest(key)[:24], **key, "case": deepcopy(case),
                               "subject": deepcopy(subject), "prerequisites_hash": digest(case["prerequisites"]),
                               "grading_definition_hash": definition, "environment_policy": deepcopy(policy)})
    return {"schema_version": 2, "experiment_id": experiment_id, **identity,
            "benchmark_hash": digest(fixed_benchmark), "trials": trials}


def validate_experiment(experiment: dict) -> dict:
    """Rebuild every identity before execution, not only when reporting results.

    Hashes detect partial edits and stale matrix bindings; they are not signatures
    or authorization to run arbitrary newly authored experiments.
    """
    if (not isinstance(experiment, dict) or experiment.get("schema_version") != 2
            or not isinstance(experiment.get("trials"), list)
            or not isinstance(experiment.get("benchmark"), dict)):
        raise ValueError("invalid frozen experiment")
    by_hash = {}
    for trial in experiment["trials"]:
        case = validate_case(trial["case"])
        if digest(case) != trial.get("case_hash"):
            raise ValueError("frozen experiment Case hash mismatch")
        by_hash[trial["case_hash"]] = case
    fixed = experiment["benchmark"]
    cases = []
    for member in fixed["cases"]:
        case = by_hash.get(member["case_hash"])
        if case is None or case["id"] != member["id"] or case["version"] != member["version"]:
            raise ValueError("frozen Benchmark member does not match its embedded Case")
        cases.append(case)
    rebuilt = build_experiment({"id": fixed["id"], "version": fixed["version"], "cases": cases,
        "environment_policy": experiment["environment_policy"], "grading_config": experiment.get("grading_config")},
        experiment["subjects"], experiment["repetitions"])
    if rebuilt != experiment:
        raise ValueError("frozen experiment identity, subject, repetition or matrix was changed")
    return deepcopy(experiment)


def report_experiment(experiment: dict, results: list[dict]) -> dict:
    """Reject misattribution; absent or invalid results leave their planned task pending.

    A runner's independent trial_id can be bound explicitly using
    result.experiment={experiment_id, planned_trial_id, repetition}. Otherwise trial_id must match.
    """
    if experiment.get("schema_version") != 2 or not isinstance(experiment.get("trials"), list):
        raise ValueError("Invalid experiment plan")
    planned = {trial["trial_id"]: trial for trial in experiment["trials"]}
    if len(planned) != len(experiment["trials"]):
        raise ValueError("Duplicate planned trial identity")
    associated, invalid = defaultdict(list), []
    actual_ids = Counter(result.get("trial_id") for result in results if isinstance(result.get("trial_id"), str))
    for result in results:
        reasons = []
        if not isinstance(result.get("trial_id"), str) or not result["trial_id"].strip():
            reasons.append("missing_trial_identity")
        elif actual_ids[result["trial_id"]] > 1:
            reasons.append("duplicate_trial_identity")
        binding = result.get("experiment", {})
        if not isinstance(binding, dict):
            binding = {}
            reasons.append("invalid_experiment_binding")
        target = binding.get("planned_trial_id", result.get("trial_id"))
        trial = planned.get(target) if isinstance(target, str) else None
        if trial is None:
            reasons.append("unplanned_trial")
        elif binding and binding.get("experiment_id") != experiment["experiment_id"]:
            reasons.append("experiment_identity_mismatch")
        if trial:
            try:
                case = validate_case(result["case"])
                if result.get("schema_version") != 2 or digest(case) != trial["case_hash"] or result.get("case_hash") != trial["case_hash"]:
                    reasons.append("case_identity_mismatch")
                if digest(result.get("subject")) != trial["subject_hash"]:
                    reasons.append("subject_identity_mismatch")
                if _repetition(result) != trial["repetition"]:
                    reasons.append("repetition_mismatch")
                if digest(case["prerequisites"]) != trial["prerequisites_hash"]:
                    reasons.append("prerequisite_identity_mismatch")
                if trial["environment_policy"] != "unknown" and _policy(result) != trial["environment_policy"]:
                    reasons.append("environment_policy_mismatch")
                definition = _latest(result).get("definition_hash") or result.get("grading_definition_hash")
                if definition is not None and definition != trial["grading_definition_hash"]:
                    reasons.append("grading_definition_mismatch")
            except (ValueError, TypeError, KeyError):
                reasons.append("invalid_result_identity")
        if reasons:
            invalid.append({"trial_id": result.get("trial_id"), "planned_trial_id": target,
                            "reasons": reasons, "result": deepcopy(result)})
        else:
            associated[target].append(result)
    rows = []
    for trial_id, trial in planned.items():
        matches = associated[trial_id]
        if len(matches) != 1:
            rows.append({"trial_id": trial_id, "case_hash": trial["case_hash"], "subject_hash": trial["subject_hash"],
                         "repetition": trial["repetition"], "status": "pending", "summary": None,
                         "reason": "duplicate_results" if matches else "missing_result"})
            for result in matches:
                invalid.append({"trial_id": result.get("trial_id"), "planned_trial_id": trial_id,
                                "reasons": ["duplicate_results"], "result": deepcopy(result)})
        else:
            summary = summarize_trial(matches[0])
            rows.append({"trial_id": trial_id, "case_hash": trial["case_hash"], "subject_hash": trial["subject_hash"],
                         "repetition": trial["repetition"], "status": summary["status"], "summary": summary})
    return {"schema_version": 2, "experiment_id": experiment["experiment_id"], "trials": rows,
            "counts": {"planned": len(rows), "received": len(results), "invalid": len(invalid),
                       "by_status": dict(Counter(row["status"] for row in rows))}, "invalid_results": invalid,
            "notes": ["Every planned task is retained; pending, blocked and failed trials are not excluded.",
                      "No statistical significance, pass@k or automatic version acceptance is inferred."]}
