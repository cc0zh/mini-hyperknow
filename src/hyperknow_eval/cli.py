"""Learning evaluation: validate, run, judge, calibrate, report and compare."""

import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv

from .cases import DEFAULT_SUITE, ROOT, inventory, load_case, load_suite
from .schema import validate_case
from .storage import (artifact_path, digest, exclusive, load_trial, make_record, read_json,
                      save_trial, utcnow, write_json)


def _models(parser, role):
    parser.add_argument(f"--{role}-model", help=f"explicit {role} model; no tutor-model fallback")
    parser.add_argument(f"--{role}-base-url")
    parser.add_argument(f"--{role}-max-output-tokens", type=int, default=16384 if role == "judge" else 1024)
    parser.add_argument(f"--{role}-context-budget", type=int, default=96000 if role == "judge" else 32000)
    parser.add_argument(f"--{role}-timeout", type=float, default=120)


def _settings(args, role):
    from .judging import ModelSettings
    load_dotenv(ROOT / ".env", override=False)
    prefix = f"HK_EVAL_{role.upper()}_"
    return ModelSettings(
        model=getattr(args, f"{role}_model") or os.getenv(prefix + "MODEL", ""),
        api_key=os.getenv(prefix + "API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        base_url=getattr(args, f"{role}_base_url") or os.getenv(prefix + "BASE_URL")
                 or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        timeout=getattr(args, f"{role}_timeout"),
        max_output_tokens=getattr(args, f"{role}_max_output_tokens"),
        context_budget=getattr(args, f"{role}_context_budget"),
    )


def _selection(args):
    if args.case:
        return None, [load_case(args.case)]
    return load_suite(args.suite or DEFAULT_SUITE)


def _input(path: Path) -> list[dict]:
    """Only explicitly named artifacts; never recursively scan another user's results."""
    path = artifact_path(path)
    batch_path = path / "batch.json" if path.is_dir() else path
    if batch_path.name != "batch.json" or not batch_path.is_file():
        return [load_trial(path)]
    batch = read_json(batch_path)
    if batch.get("schema_version") != 3 or not batch.get("entries"):
        raise ValueError("invalid batch manifest")
    records = []
    for entry in batch["entries"]:
        case = validate_case(entry["case"])
        if digest(case) != entry["case_hash"]:
            raise ValueError("planned task identity mismatch")
        trial_path = artifact_path(batch_path.parent / entry["path"])
        if not trial_path.is_relative_to(batch_path.parent.resolve()):
            raise ValueError("batch member escapes its directory")
        if (trial_path / "trial.json").is_file():
            record = load_trial(trial_path)
            if record["case_hash"] != entry["case_hash"] or record["config"]["repetition"] != entry["repetition"]:
                raise ValueError("trial does not match planned batch cell")
        else:
            record = make_record(case, config={**batch.get("config", {}), "repetition": entry["repetition"]})
            record.update(trial_id=f"not-run-{case['id']}-{entry['repetition']}", status="not_run",
                          created_at=batch["created_at"], error={"type": "not_run", "message": "planned cell has no trial record"})
        records.append(record)
    return records


def _all_inputs(paths) -> list[dict]:
    return [record for path in paths for record in _input(path)]


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run"):
        command = commands.add_parser(name)
        group = command.add_mutually_exclusive_group()
        group.add_argument("--case", type=Path)
        group.add_argument("--suite", type=Path)
        if name == "run":
            command.add_argument("--output", type=Path, required=True, help="new private directory; never reuse a run")
            command.add_argument("--execute", action="store_true")
            command.add_argument("--with-judge", action="store_true", help="also judge saved outputs; otherwise collect only")
            command.add_argument("--base-url", help="optional existing isolated backend; otherwise start a fresh real server per trial")
            command.add_argument("--data-dir", type=Path)
            command.add_argument("--repetitions", type=int, default=1)
            _models(command, "judge")
            _models(command, "student")
    judge = commands.add_parser("judge", help="append a new judgment to frozen evidence; never runs the product")
    judge.add_argument("--input", type=Path, required=True, help="one trial directory")
    judge.add_argument("--execute", action="store_true")
    _models(judge, "judge")
    calibrate = commands.add_parser("calibrate", help="actual judge calls on authored positive/negative controls")
    calibrate.add_argument("--controls", type=Path, default=ROOT / "evals" / "calibration.json")
    calibrate.add_argument("--output", type=Path, required=True)
    calibrate.add_argument("--execute", action="store_true")
    _models(calibrate, "judge")
    report = commands.add_parser("report", help="read-only; no models, no writes unless --html is given")
    report.add_argument("--input", type=Path, action="append", required=True)
    report.add_argument("--html", type=Path)
    compare = commands.add_parser("compare", help="read-only strict paired comparison, not a leaderboard")
    compare.add_argument("--baseline", type=Path, action="append", required=True)
    compare.add_argument("--candidate", type=Path, action="append", required=True)
    return parser


def _run(args):
    from .judging import output_budget_exceeded, public_settings
    from .reporting import aggregate, write_report
    from .runner import private_path, run_trial
    if not args.execute:
        raise ValueError("--execute is required; validation alone never starts a model")
    suite, cases = _selection(args)
    if not 1 <= args.repetitions <= 20:
        raise ValueError("repetitions must be between 1 and 20")
    matrix = [(case, repetition) for repetition in range(1, args.repetitions + 1) for case in cases]
    if (args.base_url or args.data_dir) and len(matrix) != 1:
        raise ValueError("external backend is only supported for a single fresh trial")
    # Validate every evaluator configuration before any product request is authorized.
    judge_settings = _settings(args, "judge") if args.with_judge or args.judge_model else None
    simulated = any(case["task"]["mode"] == "simulated" for case in cases)
    student_settings = _settings(args, "student") if simulated else None
    output = private_path(args.output)
    if len(matrix) == 1 and args.case:
        case, repetition = matrix[0]
        records = [run_trial(case, output, execute=True, judge_settings=judge_settings,
                             student_settings=student_settings, base_url=args.base_url,
                             data_dir=args.data_dir, repetition=repetition)]
    else:
        output.mkdir(parents=True, exist_ok=False)
        config = {"judge": public_settings(judge_settings) if judge_settings else None,
                  "student": public_settings(student_settings) if student_settings else None}
        batch = {"schema_version": 3, "created_at": utcnow(), "suite": suite, "config": config,
                 "entries": [{"case": case, "case_hash": digest(case), "repetition": repetition,
                              "path": f"{case['id']}/r{repetition:02d}"} for case, repetition in matrix]}
        write_json(output / "batch.json", batch)
        with exclusive(output):
            for entry in batch["entries"]:
                record = run_trial(entry["case"], output / entry["path"], execute=True,
                          judge_settings=judge_settings, student_settings=student_settings if entry["case"]["task"]["mode"] == "simulated" else None,
                          base_url=args.base_url, data_dir=args.data_dir, repetition=entry["repetition"])
                if output_budget_exceeded(record):
                    batch["stop_reason"] = "evaluator_output_budget_exceeded"
                    write_json(output / "batch.json", batch)
                    break
        records = _input(output)
    write_report(output / "report.html", records)
    return aggregate(records)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            _, cases = _selection(args)
            result = inventory(cases)
        elif args.command == "run":
            result = _run(args)
        elif args.command == "judge":
            from .judging import judge_trial
            from .reporting import summarize, write_report
            from .runner import private_path
            if not args.execute:
                raise ValueError("--execute is required for a new paid judgment attempt")
            directory = private_path(args.input)
            settings = _settings(args, "judge")
            with exclusive(directory):
                record = load_trial(directory)
                attempt = judge_trial(record, settings, lambda: save_trial(directory, record), execute=True)
            write_report(directory / f"report-{attempt.get('attempt_id', uuid4().hex)}.html", [record])
            result = summarize(record)
        elif args.command == "calibrate":
            from .calibration import calibrate, load_controls
            from .runner import private_path
            if not args.execute:
                raise ValueError("--execute is required for calibration model calls")
            controls = load_controls(args.controls)
            result = calibrate(controls, private_path(args.output), _settings(args, "judge"), execute=True)
        elif args.command == "report":
            from .reporting import aggregate, write_report
            records = _all_inputs(args.input)
            result = aggregate(records)
            if args.html:
                from .runner import private_path
                write_report(private_path(args.html), records)
        else:
            from .reporting import compare
            result = compare(_all_inputs(args.baseline), _all_inputs(args.candidate))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if args.command == "calibrate":
            return 0 if result["passed"] else 1
        if args.command == "run":
            if any(status != "completed" for status in result["execution"]):
                return 2
            if result["engineering"].get("not_met") or result["teaching"]["statuses"].get("not_met"):
                return 1
            if (args.with_judge or args.judge_model) and result["teaching"]["statuses"].get("insufficient"):
                return 2
        if args.command == "judge":
            if result["teaching"]["status"] == "not_met":
                return 1
            if result["teaching"]["status"] != "met":
                return 2
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
