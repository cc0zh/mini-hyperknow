"""Offline, read-only review bundles. Verdicts remain owned by reporting.py."""

import base64
from collections import Counter
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re

from .evidence import validate_evidence
from .reporting import (compare_results, report_experiment, summarize_trial,
                        validate_experiment)
from .store import digest, now


NOTES = [
    "仅本地只读：不连接业务服务、不调用模型、不修改证据或成绩。",
    "包含原始任务、用户内容与私有判据；不是脱敏报告，请勿直接分享或提交 Git。",
    "unknown 身份不能归因到某次代码提交；自动通过不等于独立真人校准。",
    "未知用量不是零；已记录调用不代表供应商全部调用或费用硬封顶。",
    "证据及模型 HTML 均作为文本展示，不执行脚本、不加载外部资源。",
]


def _entry(result, *, key, side, summary, status=None, reason=None):
    evidence = []
    records = result.get("evidence", [])
    for item in records if isinstance(records, list) else [records]:
        try:
            validate_evidence(item)
            integrity = {"valid": True}
        except (ValueError, TypeError, KeyError) as exc:
            integrity = {"valid": False, "error": str(exc)}
        record = deepcopy(item) if isinstance(item, dict) else {"data": deepcopy(item)}
        record["integrity"] = integrity
        evidence.append(record)
    # Full grader requests/responses duplicate evidence and are not needed for review.
    grade_keys = ("attempt_id", "definition_hash", "evidence_set_hash", "prompt_version",
                  "created_at", "finished_at", "status", "config", "results", "error",
                  "usage", "elapsed_ms", "budget_check", "context_budget", "calibration_status")
    records = result.get("grades", [])
    grades = ([{key: deepcopy(value[key]) for key in grade_keys if key in value}
               for value in records if isinstance(value, dict)] if isinstance(records, list) else
              [{"status": "invalid", "error": {"type": "invalid_grading_records", "value": deepcopy(records)}}])
    invalid_fields = {name: deepcopy(result.get(name)) for name, kind in
                      (("trial_id", str), ("case", dict), ("subject", dict), ("actions", list))
                      if name in result and not isinstance(result[name], kind)}
    trial_id, case, subject, actions = (result.get(name) for name in ("trial_id", "case", "subject", "actions"))
    return {"key": key, "side": side,
            "trial_id": trial_id if isinstance(trial_id, str) and trial_id else "（缺失或无效 Trial ID）",
            "case": deepcopy(case) if isinstance(case, dict) else None,
            "subject": deepcopy(subject) if isinstance(subject, dict) else None,
            "status": status or summary["status"], "reason": reason,
            "summary": deepcopy(summary), "evidence": evidence,
            "actions": deepcopy(actions) if isinstance(actions, list) else [], "grades": grades,
            "invalid_fields": invalid_fields,
            "environment": deepcopy(result.get("environment")), "budget": deepcopy(result.get("budget"))}


def _bundle(kind, report, entries):
    return {"schema_version": 1, "kind": kind, "generated_at": now(),
            "report": report, "entries": entries, "notes": list(NOTES)}


def report_bundle(results: list[dict], experiment: dict | None = None) -> dict:
    """Retain the full plan, and never attach an invalid result to a planned task."""
    if experiment is None:
        summaries = [summarize_trial(result) for result in results]
        report = {"scope": "selected_results", "trials": summaries, "counts": {"planned": len(results), "received": len(results),
                  "invalid": 0, "by_status": dict(Counter(item["status"] for item in summaries))}}
        entries = [_entry(result, key=f"report:{index}", side="report", summary=summary)
                   for index, (result, summary) in enumerate(zip(results, summaries))]
        return _bundle("report", report, entries)
    experiment = validate_experiment(experiment)
    report = report_experiment(experiment, results)
    plans = {trial["trial_id"]: trial for trial in experiment["trials"]}
    invalid_ids = [item["trial_id"] for item in report["invalid_results"]]
    valid = {}
    for result in results:
        if result.get("trial_id") in invalid_ids:
            continue
        binding = result.get("experiment") or {}
        target = binding.get("planned_trial_id", result.get("trial_id"))
        valid[target] = result
    entries = []
    for index, row in enumerate(report["trials"]):
        if row["summary"] is not None:
            entry = _entry(valid[row["trial_id"]], key=f"report:{index}", side="report",
                           summary=row["summary"])
        else:
            plan = plans[row["trial_id"]]
            entry = _entry({"trial_id": row["trial_id"], "case": plan["case"], "subject": plan["subject"]},
                           key=f"report:{index}", side="report", summary=None, status="pending",
                           reason=row.get("reason"))
        entries.append(entry)
    for index, item in enumerate(report["invalid_results"]):
        entries.append(_entry(item["result"], key=f"invalid:{index}", side="report", summary=None,
                              status="invalid", reason=", ".join(item["reasons"])))
    # The review bundle has an explicit entry for invalid material; do not duplicate raw records.
    report = {**report, "invalid_results": [{key: deepcopy(value) for key, value in item.items()
                                            if key != "result"} for item in report["invalid_results"]]}
    return _bundle("report", report, entries)


def comparison_bundle(baseline: list[dict], candidate: list[dict]) -> dict:
    report = compare_results(baseline, candidate)
    entries = [_entry(result, key=f"{side}:{index}", side=side, summary=summarize_trial(result))
               for side, results in (("baseline", baseline), ("candidate", candidate))
               for index, result in enumerate(results)]
    return _bundle("comparison", report, entries)


def render_html(bundle: dict) -> str:
    """Embed JSON as data, never markup; authorize only the fixed viewer script."""
    digest(bundle)  # Reject non-finite or non-JSON data before serialization.
    template = files("eval_core").joinpath("report_template.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", template, flags=re.DOTALL)
    if len(scripts) != 1 or template.count("__EVAL_REPORT_DATA__") != 1 or template.count("__EVAL_REPORT_CSP__") != 1:
        raise ValueError("Invalid HTML report template")
    script_hash = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode("ascii")
    policy = ("default-src 'none'; script-src 'sha256-" + script_hash + "'; "
              "style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; "
              "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
    data = json.dumps(bundle, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for character, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                               ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        data = data.replace(character, escaped)
    # Substitute the template first, so token-like strings inside user data remain untouched.
    return template.replace("__EVAL_REPORT_CSP__", policy).replace("__EVAL_REPORT_DATA__", data)


def write_html(path: Path, bundle: dict) -> Path:
    """Write a new private artifact; never overwrite a source or an earlier report."""
    path = Path(path)
    if path.suffix.lower() != ".html":
        raise ValueError("HTML report output must have a .html suffix")
    content = render_html(bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return path
