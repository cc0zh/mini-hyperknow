"""Read-only teaching reports; no migrations, model requests or success-only subsets."""

from collections import Counter
from copy import deepcopy
from html import escape
import json
from pathlib import Path

from .judging import (JUDGE_VERSION, STUDENT_VERSION, judge_definition_hash, parse_judgment,
                      public_settings, response_content, student_definition_hash)
from .schema import DIMENSIONS
from .storage import artifact_path, digest, encode, evidence_hash, validate_record

DISCLAIMER = "模拟学生交互和自动教学判据不证明真人学习收益。Simulated interaction does not establish real human learning gains."
_VERDICTS = ("met", "not_met", "insufficient")
_USAGE = ("prompt_tokens", "completion_tokens", "total_tokens")


def _counts() -> dict:
    return {"met": 0, "not_met": 0, "insufficient": 0, "total": 0}


def _pending(case: dict, reason: str) -> list[dict]:
    return [{"criterion_id": item["id"], "verdict": "insufficient", "reason": reason,
             "evidence_id": "", "quote": ""} for item in case["rubric"]]


def _current_judgment(record: dict) -> tuple[list[dict], dict]:
    attempts = record["judgments"]
    if not attempts:
        return _pending(record["case"], "not judged"), {"status": "unjudged", "error": None}
    attempt = attempts[-1]  # Never fall back to an older, more favorable attempt.
    identity = {key: deepcopy(attempt.get(key)) for key in (
        "attempt_id", "status", "definition_hash", "evidence_hash", "prompt_version", "config", "model", "error",
    )}
    try:
        if attempt.get("prompt_version") != JUDGE_VERSION:
            raise ValueError("judge prompt version changed")
        config = public_settings(attempt.get("config"))
        expected_config = record.get("config", {}).get("judge")
        identity["differs_from_planned"] = expected_config is not None and public_settings(expected_config) != config
        if attempt.get("definition_hash") != judge_definition_hash(record["case"], config):
            raise ValueError("judge definition hash changed")
        if attempt.get("evidence_hash") != evidence_hash(record):
            raise ValueError("frozen evidence hash changed")
        if attempt.get("status") != "completed" or attempt.get("error"):
            identity["status"] = attempt.get("status", "error")
            return _pending(record["case"], "judgment not completed"), identity
        results = parse_judgment(encode({"criteria": attempt.get("results")}), record["case"], record["evidence"])
        raw = attempt.get("raw_response")
        if raw is not None:
            actual = raw.get("model") or "unknown"
            if not isinstance(actual, str) or actual == "unknown" or attempt.get("model") != actual:
                raise ValueError("actual judge model is unknown or inconsistent")
            if attempt.get("usage") != raw.get("usage"):
                raise ValueError("judge usage differs from raw response")
            completion = (raw.get("usage") or {}).get("completion_tokens")
            if type(completion) is int and completion > config["max_output_tokens"]:
                raise ValueError("actual judge output exceeded its requested budget")
            parsed = parse_judgment(response_content(raw), record["case"], record["evidence"])
            if parsed != results:
                raise ValueError("saved criteria differ from the raw model response")
        elif any(item["verdict"] != "insufficient" for item in results):
            raise ValueError("non-insufficient judgment lacks its raw model response")
        return results, identity
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        identity.update(status="invalid_or_stale", validation_error=str(exc))
        return _pending(record["case"], "invalid or stale judgment: " + str(exc)), identity


def _engineering(checks: list[dict]) -> dict:
    checks = [item for item in checks if item.get("category", "engineering") == "engineering"
              and item.get("id") != "remote_cost_finished"]
    counts = _counts()
    for check in checks:
        verdict = check.get("verdict", check.get("status"))
        if "passed" in check:
            verdict = "met" if check["passed"] is True else "not_met" if check["passed"] is False else "insufficient"
        elif "ok" in check:
            verdict = "met" if check["ok"] is True else "not_met" if check["ok"] is False else "insufficient"
        verdict = {"pass": "met", "passed": "met", "fail": "not_met", "failed": "not_met"}.get(verdict, verdict)
        counts[verdict if verdict in _VERDICTS else "insufficient"] += 1
        counts["total"] += 1
    status = "not_met" if counts["not_met"] else "insufficient" if not checks or counts["insufficient"] else "met"
    return {"status": status, **counts, "checks": deepcopy(checks)}


def _business_calls(record: dict) -> tuple[list[dict], list[str]]:
    latest = {}
    for evidence in record["evidence"]:
        if evidence.get("kind") != "model_calls":
            continue
        run_id = evidence.get("source", {}).get("run_id")
        if isinstance(run_id, str) and isinstance(evidence.get("content"), list):
            latest[run_id] = evidence["content"]
    # References to these snapshots are not a second billable call inventory.
    references = {}
    for request in record.get("model_requests", []):
        if request.get("role") == "business" and isinstance(request.get("run_id"), str):
            references.setdefault(request["run_id"], []).append(request)
    indexed = []
    for run_id in sorted(set(latest) | set(references)):
        unique = {}
        for position, call in enumerate(latest.get(run_id, references.get(run_id, []))):
            if not isinstance(call, dict):
                continue
            key = call.get("call_index", call.get("call_id", call.get("id", position)))
            unique[encode(key)] = call
        indexed.extend(unique.values())
    missing = [run for run in record.get("business_runs", []) if run not in latest]
    return indexed, missing


def _usage(calls: list[dict], *, missing_inventory: list[str] | None = None) -> dict:
    known, totals = {}, {}
    for field in _USAGE:
        measured = [(call.get("usage") or {}).get(field) for call in calls]
        values = [value for value in measured if type(value) is int and value >= 0]
        known[field] = sum(values) if values else None
        totals[field] = known[field] if calls and len(values) == len(calls) and not missing_inventory else None
    return {"observed_calls": len(calls), "unknown_usage_calls": sum(
                any(type((call.get("usage") or {}).get(field)) is not int
                    or (call.get("usage") or {}).get(field, -1) < 0 for field in _USAGE) for call in calls),
            "usage": totals, "known_usage": known, "missing_inventory_runs": missing_inventory or [],
            "models": sorted({call.get("model") or "unknown" for call in calls}),
            "providers": sorted({call.get("provider") or "unknown" for call in calls}),
            "completion_cost": "unknown"}


def _sent(call: dict) -> bool:
    return bool(call.get("sent_at") or call.get("raw_response") is not None or call.get("status") == "in_flight")


def _budget_violations(calls: list[dict]) -> list[dict]:
    violations = []
    for call in calls:
        measured = (call.get("usage") or {}).get("completion_tokens")
        limit = (call.get("config") or {}).get("max_output_tokens")
        if type(measured) is int and type(limit) is int and measured > limit:
            violations.append({"request_id": call.get("request_id"), "requested_output_tokens": limit,
                               "reported_completion_tokens": measured})
    return violations


def summarize(record: dict) -> dict:
    validate_record(record)
    results, judgment = _current_judgment(record)
    by_id = {item["criterion_id"]: item for item in results}
    dimensions = {name: _counts() for name in DIMENSIONS}
    critical_failures = []
    for criterion in record["case"]["rubric"]:
        verdict = by_id[criterion["id"]]["verdict"]
        dimensions[criterion["dimension"]][verdict] += 1
        dimensions[criterion["dimension"]]["total"] += 1
        if criterion["critical"] and verdict == "not_met":
            critical_failures.append(criterion["id"])
    verdicts = [item["verdict"] for item in results]
    teaching_status = ("not_met" if critical_failures else "insufficient" if not verdicts or "insufficient" in verdicts
                       else "not_met" if "not_met" in verdicts else "met")
    business, missing = _business_calls(record)
    student = [call for call in record.get("model_requests", []) if call.get("role") == "student" and _sent(call)]
    judge = [call for call in record["judgments"] if _sent(call)]
    return {
        "trial_id": record["trial_id"], "case_id": record["case"]["id"], "case_hash": record["case_hash"],
        "subject": deepcopy(record.get("subject", {"identity": "unknown"})),
        "execution": {"status": record["status"], "error": deepcopy(record.get("error"))},
        "engineering": _engineering(record["checks"]),
        "observations": [deepcopy(item) for item in record["checks"]
                         if item.get("category", "engineering") != "engineering"
                         or item.get("id") == "remote_cost_finished"],
        "teaching": {"status": teaching_status, "critical_veto": bool(critical_failures),
                     "critical_not_met": critical_failures, "dimensions": dimensions, "criteria": results},
        "judgment": judgment, "calibration_status": "unreviewed",
        "coverage": {"domain": record["case"]["domain"], "workflow": record["case"]["workflow"],
                     "interaction_mode": record["case"]["task"]["mode"]},
        "usage": {"business": _usage(business, missing_inventory=missing), "student": _usage(student),
                  "judge": _usage(judge), "business_inventory_scope": "saved_calls_only",
                  "remote_or_in_flight_cost": "unknown"},
        "output_budget_violations": _budget_violations(student + judge), "disclaimer": DISCLAIMER,
    }


def aggregate(records: list[dict]) -> dict:
    summaries = [summarize(record) for record in records]
    dimensions = {name: _counts() for name in DIMENSIONS}
    for summary in summaries:
        for dimension in DIMENSIONS:
            for field in dimensions[dimension]:
                dimensions[dimension][field] += summary["teaching"]["dimensions"][dimension][field]
    usage = {}
    business, missing, students, judges = [], [], [], []
    for record in records:
        calls, unknown = _business_calls(record)
        business.extend(calls)
        missing.extend(unknown)
        students.extend(call for call in record.get("model_requests", []) if call.get("role") == "student" and _sent(call))
        judges.extend(call for call in record["judgments"] if _sent(call))
    for role, calls in (("business", business), ("student", students), ("judge", judges)):
        usage[role] = _usage(calls, missing_inventory=missing if role == "business" else None)
    return {"trials": len(records), "execution": dict(Counter(item["execution"]["status"] for item in summaries)),
            "engineering": dict(Counter(item["engineering"]["status"] for item in summaries)),
            "teaching": {"statuses": dict(Counter(item["teaching"]["status"] for item in summaries)),
                         "dimensions": dimensions},
            "coverage": {field: dict(Counter(item["coverage"][field] for item in summaries))
                         for field in ("domain", "workflow", "interaction_mode")},
            "usage": usage, "calibration_status": "unreviewed", "records": summaries, "disclaimer": DISCLAIMER}


def _comparison_identity(record: dict) -> dict:
    config, case = record.get("config", {}), record["case"]
    mode = case["task"]["mode"]
    if config.get("interaction_mode", mode) != mode:
        raise ValueError("record interaction mode differs from its case")
    student = None
    if mode == "simulated":
        settings = public_settings(config.get("student"))
        student = student_definition_hash(record, settings)
        if config.get("student_definition_hash") != student:
            raise ValueError("student definition hash missing or changed")
        for request in record.get("model_requests", []):
            if request.get("role") == "student" and (request.get("definition_hash") != student
                    or request.get("prompt_version") != STUDENT_VERSION or public_settings(request.get("config")) != settings):
                raise ValueError("student model configuration or prompt changed within trial")
    settings = record["judgments"][-1].get("config") if record["judgments"] else config.get("judge")
    judge = judge_definition_hash(case, settings) if settings is not None else None
    latest = record["judgments"][-1] if record["judgments"] else None
    if latest is not None and (latest.get("definition_hash") != judge or latest.get("prompt_version") != JUDGE_VERSION):
        raise ValueError("judge definition or model configuration is not comparable")
    return {"case_hash": record["case_hash"], "interaction_mode": mode, "student_definition_hash": student,
            "judge_definition_hash": judge}


def _actual_model(record: dict, role: str) -> set[str]:
    requests = record["judgments"][-1:] if role == "judge" else record.get("model_requests", [])
    actual = set()
    for call in requests:
        if call.get("role") == role and call.get("raw_response") is not None:
            model = call["raw_response"].get("model")
            if isinstance(model, str) and model and model != "unknown":
                actual.add(model)
    return actual


def _student_model_integrity(record: dict) -> None:
    """Historical student replies cannot silently acquire a different model identity."""
    for call in record.get("model_requests", []):
        if call.get("role") != "student" or call.get("raw_response") is None:
            continue
        actual = call["raw_response"].get("model") or "unknown"
        if call.get("model") != actual:
            raise ValueError("student actual model differs from its raw response")


def _pairing_index(records: list[dict], repeated: set[str]) -> dict:
    result, trials = {}, set()
    for record in records:
        validate_record(record)
        if record["trial_id"] in trials:
            raise ValueError("duplicate trial_id in comparison set")
        trials.add(record["trial_id"])
        repetition = record.get("config", {}).get("repetition")
        if repetition is not None and (type(repetition) is not int or repetition < 1):
            raise ValueError("repetition must be a positive integer")
        unit = ("repetition", repetition) if repetition is not None else (
            ("trial_id", record["trial_id"]) if record["case_hash"] in repeated else ("repetition", 1))
        key = (record["case_hash"], *unit)
        if key in result:
            raise ValueError("duplicate case/repetition comparison unit")
        result[key] = record
    return result


def compare(baseline: list[dict], candidate: list[dict]) -> dict:
    """Require the entire same task matrix; failures and unjudged trials stay in it."""
    if not baseline or not candidate:
        raise ValueError("comparison requires two nonempty trial sets")
    repeated = {identity for side in (baseline, candidate) for identity, count in Counter(
        record["case_hash"] for record in side).items() if count > 1}
    left, right = _pairing_index(baseline, repeated), _pairing_index(candidate, repeated)
    if set(left) != set(right):
        missing_baseline, missing_candidate = sorted(set(right) - set(left)), sorted(set(left) - set(right))
        raise ValueError(f"incomparable trial matrices; missing baseline={missing_baseline}; missing candidate={missing_candidate}")
    pairs, warnings = [], set()
    transitions = {}
    for key in sorted(left):
        old, new = left[key], right[key]
        if old["trial_id"] == new["trial_id"]:
            raise ValueError("the same trial_id rejudged is not two subject executions")
        if _comparison_identity(old) != _comparison_identity(new):
            raise ValueError("case, interaction, student or judge definition/configuration changed")
        _student_model_integrity(old)
        _student_model_integrity(new)
        for role in ("judge", "student"):
            old_models, new_models = _actual_model(old, role), _actual_model(new, role)
            if old_models and new_models and old_models != new_models:
                raise ValueError(f"actual {role} model changed between comparison sides")
            if old_models != new_models:
                warnings.add(f"{role} actual model unavailable on one side; no model-specific attribution")
        old_subject, new_subject = old.get("subject", {}).get("identity"), new.get("subject", {}).get("identity")
        if not old_subject or old_subject == "unknown" or not new_subject or new_subject == "unknown":
            warnings.add("subject identity unknown; any difference has unknown attribution")
        elif old_subject == new_subject:
            warnings.add("same source identity: repetition or negative control, not a source-version change")
        if old.get("subject", {}).get("model") != new.get("subject", {}).get("model"):
            warnings.add("subject model differs; source identity alone cannot attribute changes to code")
        old_summary, new_summary = summarize(old), summarize(new)
        if any(item["judgment"]["status"] == "invalid_or_stale" for item in (old_summary, new_summary)):
            raise ValueError("stale or invalid judgment is not comparable; explicitly rejudge first")
        old_criteria = {item["criterion_id"]: item["verdict"] for item in old_summary["teaching"]["criteria"]}
        new_criteria = {item["criterion_id"]: item["verdict"] for item in new_summary["teaching"]["criteria"]}
        for criterion in old["case"]["rubric"]:
            dimension = criterion["dimension"]
            transition = old_criteria[criterion["id"]] + " -> " + new_criteria[criterion["id"]]
            transitions.setdefault(dimension, Counter())[transition] += 1
        pairs.append({"case_hash": key[0], "pairing": {key[1]: key[2]},
                      "baseline_trial_id": old["trial_id"], "candidate_trial_id": new["trial_id"],
                      "baseline": old_summary, "candidate": new_summary})
    return {"paired_trials": len(pairs), "baseline": aggregate(baseline), "candidate": aggregate(candidate),
            "criterion_transitions": {name: dict(counts) for name, counts in transitions.items()},
            "pairs": pairs, "warnings": sorted(warnings), "calibration_status": "unreviewed",
            "disclaimer": DISCLAIMER}


def _section(title: str, value) -> str:
    return "<h3>" + escape(title) + "</h3><pre>" + escape(json.dumps(
        value, ensure_ascii=False, indent=2, allow_nan=False)) + "</pre>"


def write_report(path: Path, records: list[dict]) -> None:
    """Create a new, self-contained text-only HTML file without overwriting artifacts."""
    path = artifact_path(path)
    if path.suffix.lower() != ".html":
        raise ValueError("report output must be a new .html file")
    summary = aggregate(records)
    sections = [_section("Aggregate / 汇总", summary)]
    for record in records:
        sections.append("<article><h2>" + escape(record["case"]["title"]) + " — " + escape(record["trial_id"]) + "</h2>")
        for title, value in (
            ("Task, learner and private reference / 任务与参考", record["case"]),
            ("Identity, configuration and execution / 身份与执行", {key: record.get(key) for key in
             ("trial_id", "case_hash", "subject", "config", "environment", "status", "error", "checks", "actions", "business_runs")}),
            ("Turn-by-turn transcript / 逐轮", record["transcript"]),
            ("Frozen evidence / 冻结证据", record["evidence"]),
            ("Judgments and errors / 判断及评分错误", record["judgments"]),
            ("Model request/response audit / 模型请求响应", record["model_requests"]),
        ):
            sections.append(_section(title, value))
        sections.append("</article>")
    document = (
        '<!doctype html><html lang="zh"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; '
        'style-src &apos;unsafe-inline&apos;; base-uri &apos;none&apos;; form-action &apos;none&apos;">'
        "<title>Learning evaluation / 教学评测</title><style>body{max-width:1100px;margin:2em auto;"
        "padding:1em;font:16px system-ui;color:#222}pre{white-space:pre-wrap;overflow-wrap:anywhere;"
        "border:1px solid #ccc;padding:1em}article{border-top:3px solid #345;margin-top:2em}</style>"
        "</head><body><h1>Learning evaluation / 教学评测</h1><p>" + escape(DISCLAIMER)
        + "</p><p>Calibration: unreviewed. Private evidence: review before sharing.</p>"
        + "".join(sections) + "</body></html>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(document)
