"""Run authored evaluator controls through the same judge, never through the tutor."""

from pathlib import Path

from .judging import JUDGE_VERSION, judge_trial, output_budget_exceeded, public_settings
from .schema import validate_case
from .storage import (add_evidence, artifact_path, digest, exclusive, new_trial, read_json,
                      save_trial, utcnow, write_json)


def load_controls(path: Path) -> dict:
    value = read_json(path)
    if (set(value) != {"schema_version", "purpose", "controls"} or value["schema_version"] != 3
            or value["purpose"] != "authored-controls-not-human-alignment"
            or not isinstance(value["controls"], list) or not value["controls"]):
        raise ValueError("invalid calibration controls")
    seen = set()
    for control in value["controls"]:
        case = validate_case(control["case"])
        expected = control["expected"]
        if (not isinstance(control["id"], str) or control["id"] in seen
                or not control["id"].replace("-", "").isalnum()
                or not expected or set(expected) - {item["id"] for item in case["rubric"]}
                or any(result not in {"met", "not_met", "insufficient"} for result in expected.values())):
            raise ValueError("invalid control identity or expected verdicts")
        if any(turn.get("role") not in {"student", "tutor"} or not isinstance(turn.get("text"), str)
               or not turn["text"].strip() for turn in control["turns"]):
            raise ValueError("invalid control transcript")
        seen.add(control["id"])
    return value


def calibrate(controls: dict, output: Path, settings, *, execute=False) -> dict:
    if not execute:
        raise ValueError("--execute is required for evaluator calibration calls")
    output = artifact_path(output)
    output.mkdir(parents=True, exist_ok=False)
    summary = {"schema_version": 3, "created_at": utcnow(), "judge_version": JUDGE_VERSION,
               "settings": public_settings(settings), "controls_hash": digest(controls),
               "scope": "authored-controls-only; independent human alignment unmeasured",
               "results": [], "false_acceptances": 0, "false_rejections": 0, "errors": 0, "not_run": 0}
    write_json(output / "controls.json", controls)
    halted = False
    for control in controls["controls"]:
        directory = output / control["id"]
        record = new_trial(directory, control["case"], config={"kind": "evaluator-control"})
        record["status"] = "completed"
        record["subject"] = {"identity": "authored-control", "kind": "not-a-product-run"}
        for turn in control["turns"]:
            item = dict(turn)
            if turn["role"] == "tutor":
                item["evidence_id"] = add_evidence(record, "tutor_turn", {"text": turn["text"]},
                                                    {"kind": "authored-evaluator-control"})
            record["transcript"].append(item)
        if control.get("source_excerpt"):
            add_evidence(record, "source", {"excerpt": control["source_excerpt"]},
                         {"kind": "authored-evaluator-control"})

        def checkpoint():
            save_trial(directory, record)

        with exclusive(directory):
            if halted:
                record["status"] = "not_run"
            checkpoint()
            attempt = ({"status": "not_run", "results": []} if halted
                       else judge_trial(record, settings, checkpoint, execute=True))
        if output_budget_exceeded(record):
            halted = True
            summary["stop_reason"] = "evaluator_output_budget_exceeded"
        summary["not_run"] += int(attempt.get("status") == "not_run")
        actual = {item["criterion_id"]: item["verdict"] for item in attempt.get("results", [])}
        comparisons = []
        for criterion, expected in control["expected"].items():
            observed = actual.get(criterion, "insufficient")
            comparisons.append({"criterion_id": criterion, "expected": expected,
                                "observed": observed, "matched": observed == expected})
            summary["false_acceptances"] += int(expected == "not_met" and observed == "met")
            summary["false_rejections"] += int(expected == "met" and observed == "not_met")
        error = attempt.get("status") == "error" or attempt.get("status") == "in_flight"
        summary["errors"] += int(error)
        summary["results"].append({"control_id": control["id"], "trial": f"{control['id']}/trial.json",
                                   "attempt_id": attempt.get("attempt_id"), "status": attempt.get("status"),
                                   "comparisons": comparisons, "passed": attempt.get("status") == "completed"
                                   and not error and all(item["matched"] for item in comparisons)})
        write_json(output / "calibration.json", summary)
    summary["passed"] = bool(summary["results"]) and all(item["passed"] for item in summary["results"])
    summary["finished_at"] = utcnow()
    write_json(output / "calibration.json", summary)
    return summary
