"""Unified evaluation: prepare fixed tasks, execute trials and inspect saved evidence."""

import argparse
from dataclasses import asdict, replace
import json
import math
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv

from eval_core.artifacts import result_path, run_directory
from eval_core.cases import collect_sample, freeze_benchmark, publish_case
from eval_core.contracts import validate_case
from eval_core.grading import ModelSettings, grade_trial, grading_definition_hash
from eval_core.reporting import (build_experiment, compare_results, report_experiment,
                                 summarize_trial, validate_experiment)
from eval_core.runner import execute_trial
from eval_core.store import digest, read_json, write_json

from .eval_adapter import HyperknowAdapter
from .eval_checks import RULES
from .eval_evidence import export_fixture_manifest
from .eval_legacy import summarize_legacy_result
from .eval_migration import migrate_case
from .eval_trajectories import export_trial_trajectories
from .eval_support import ROOT, private_output


def _review_options(parser):
    parser.add_argument("--review-dir", type=Path, default=ROOT / "data/evals/review",
                        help="private report catalog directory; default: data/evals/review")


def _review_bundle(args):
    from eval_core.html_report import comparison_bundle, report_bundle

    def paths(values):
        return sorted(str(result_path(path).resolve()) for path in values)

    if args.command == "compare":
        sources = {"baseline": paths(args.baseline), "candidate": paths(args.candidate)}
        return comparison_bundle([_result(path) for path in args.baseline],
                                 [_result(path) for path in args.candidate]), sources
    selected = [args.output] if args.command in {"execute", "resume", "regrade"} else args.result
    plan_path = getattr(args, "experiment", None) if args.command in {"report", "review"} else None
    plan = validate_experiment(read_json(plan_path)) if plan_path else None
    return report_bundle([_result(path) for path in selected], plan), {
        "results": paths(selected), "experiment": str(plan_path.resolve()) if plan_path else None}


def _publish_review(args):
    """A viewer export failure must never discard a paid evaluation's outcome."""
    try:
        from eval_core.review import publish_review
        bundle, sources = _review_bundle(args)
        _publish_run_report(bundle, sources)
        directory = private_output(args.review_dir)
        publish_review(directory, bundle, sources)
        _publish_workspace_home(directory)
    except Exception as exc:
        # Paths and arbitrary exception text can contain private material.
        print(f"Review export deferred ({type(exc).__name__}); saved evaluation unchanged. "
              "Use review --result to retry offline.", file=sys.stderr)


def _publish_run_report(bundle, sources):
    from eval_core.review import publish_run_report
    paths = sources.get("results", [])
    if len(paths) == 1 and not sources.get("experiment"):
        directory = run_directory(Path(paths[0]))
        if directory is not None:
            publish_run_report(private_output(directory), bundle)


def _publish_workspace_home(directory):
    if directory == (ROOT / "data/evals/review").resolve():
        from eval_core.review import publish_workspace_home
        publish_workspace_home(directory.parent)


def _result(path: Path, *, allow_legacy: bool = False) -> dict:
    value = read_json(result_path(path))
    if value.get("schema_version") == 1 and not allow_legacy:
        raise ValueError("historical schema-v1 results are read-only; use report --result, "
                         "not resume, regrade, compare or review")
    return value


def _case(path: Path) -> dict:
    value = read_json(path)
    return validate_case(value.get("case", value))


def _settings(args) -> ModelSettings:
    load_dotenv(ROOT / ".env", override=False)
    return ModelSettings(
        model=args.grader_model or os.getenv("HK_EVAL_GRADER_MODEL", ""),
        api_key=os.getenv("HK_EVAL_GRADER_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        base_url=args.grader_base_url or os.getenv("HK_EVAL_GRADER_BASE_URL")
                 or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        timeout=args.grader_timeout, max_output_tokens=args.grader_max_output_tokens,
        context_budget=args.grader_context_budget)


def _grader_options(parser):
    parser.add_argument("--execute", action="store_true", help="authorize this command's potentially billable calls")
    parser.add_argument("--grader-model")
    parser.add_argument("--grader-base-url")
    parser.add_argument("--grader-timeout", type=float, default=90)
    parser.add_argument("--grader-max-output-tokens", type=int, default=2048)
    parser.add_argument("--grader-context-budget", type=int, default=16384,
                        help="explicit input estimate plus output reserve; part of the frozen grading identity")


def _public_grading_config(value: dict) -> dict:
    """Validate offline settings without inventing credentials or constructing a provider."""
    keys = {"model", "base_url", "timeout", "max_output_tokens", "context_budget"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("grading-config must contain exactly the five public ModelSettings fields, never api_key")
    if not isinstance(value["model"], str) or not value["model"].strip():
        raise ValueError("grading-config requires an explicit model")
    url = value["base_url"]
    parsed = urlsplit(url)
    if (not isinstance(url, str) or any(c.isspace() for c in url)
            or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or "?" in url or "#" in url):
        raise ValueError("invalid public grader endpoint")
    parsed.port
    if (type(value["timeout"]) not in (int, float) or not math.isfinite(value["timeout"])
            or value["timeout"] <= 0):
        raise ValueError("grading-config timeout must be positive and finite")
    if any(type(value[key]) is not int or value[key] < 1 for key in ("max_output_tokens", "context_budget")):
        raise ValueError("grading-config token budgets must be positive integers")
    return value


def _settings_for_plan(settings: ModelSettings | None, frozen: dict | None) -> ModelSettings | None:
    """Match numeric values, then retain the frozen representation for its exact hash.

    Do not change the global digest algorithm or rebuild historical experiment IDs.
    Timeout is the only public setting that accepts both int and float.
    """
    if settings is None or frozen is None:
        return settings
    frozen = _public_grading_config(frozen)
    public = {key: value for key, value in asdict(settings).items() if key != "api_key"}
    if public != frozen:
        raise ValueError("Grader settings differ from the frozen experiment; no business command was sent")
    return replace(settings, timeout=frozen["timeout"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "publish", "migrate"):
        command = commands.add_parser(name)
        command.add_argument("--case", type=Path, required=True)
        if name == "publish":
            command.add_argument("--library", type=Path, default=ROOT / "data/evals/v2")
            command.add_argument("--reviewed-by", required=True, help="actual reviewer; does not imply independent calibration")
        if name == "migrate":
            command.add_argument("--output", type=Path, required=True)
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--manifest", type=Path, required=True)
    benchmark.add_argument("--library", type=Path, default=ROOT / "data/evals/v2")
    fixture = commands.add_parser("fixture", help="export provenance from an already isolated consistent real snapshot")
    fixture.add_argument("--data-dir", type=Path, required=True)
    fixture.add_argument("--origin", required=True, help="opaque real backup/source identifier, not a path")
    fixture.add_argument("--bindings", type=Path, required=True)
    fixture.add_argument("--resource-sources", type=Path, required=True)
    fixture.add_argument("--output", type=Path, required=True)
    experiment = commands.add_parser("experiment")
    experiment.add_argument("--benchmark", type=Path, required=True)
    experiment.add_argument("--subjects", type=Path, required=True, help="JSON array of actual subject snapshots")
    experiment.add_argument("--library", type=Path, default=ROOT / "data/evals/v2")
    experiment.add_argument("--grading-config", type=Path, help="fixed five public ModelSettings fields; no api_key")
    experiment.add_argument("--repetitions", type=int, default=1)
    experiment.add_argument("--output", type=Path, required=True)
    for name in ("execute", "resume"):
        command = commands.add_parser(name)
        command.add_argument("--case", type=Path)
        command.add_argument("--base-url", default="http://127.0.0.1:8039")
        command.add_argument("--data-dir", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True,
                             help="run directory: report.html + details/; existing legacy directories stay unchanged")
        command.add_argument("--fixture-manifest", type=Path)
        command.add_argument("--library", type=Path, default=ROOT / "data/evals/v2")
        command.add_argument("--subject", type=Path, help="trusted service assembly snapshot, not CLI Git HEAD")
        command.add_argument("--experiment", type=Path, help="frozen experiment plan containing this trial")
        command.add_argument("--trial-id")
        command.add_argument("--repetition", type=int, default=1)
        _grader_options(command)
        _review_options(command)
    grade = commands.add_parser("regrade")
    grade.add_argument("--output", type=Path, required=True)
    grade.add_argument("--library", type=Path, default=ROOT / "data/evals/v2")
    _grader_options(grade)
    _review_options(grade)
    report = commands.add_parser("report")
    report.add_argument("--result", action="append", type=Path, default=[])
    report.add_argument("--experiment", type=Path)
    report.add_argument("--html", type=Path, help="export a new private, offline read-only HTML report")
    _review_options(report)
    compare = commands.add_parser("compare")
    compare.add_argument("--baseline", action="append", type=Path, required=True)
    compare.add_argument("--candidate", action="append", type=Path, required=True)
    compare.add_argument("--html", type=Path, help="export a new private, offline read-only HTML comparison")
    _review_options(compare)
    review = commands.add_parser("review", help="rebuild the fixed offline index or import explicit saved results")
    review.add_argument("--result", action="append", type=Path, default=[])
    review.add_argument("--experiment", type=Path)
    _review_options(review)
    return parser


def _trial_input(args) -> tuple[dict, dict, dict]:
    previous = _result(args.output) if args.command == "resume" else None
    selection = {}
    if args.experiment:
        plan = validate_experiment(read_json(args.experiment))
        matches = [item for item in plan["trials"] if item["trial_id"] == args.trial_id]
        if len(matches) != 1:
            raise ValueError("--trial-id must identify exactly one frozen experiment trial")
        selection = matches[0]
    case = validate_case(selection["case"]) if selection else (
        _case(args.case) if args.case else validate_case(previous["case"]) if previous else None)
    if case is None:
        raise ValueError("--case or a frozen --experiment trial is required")
    if previous and digest(case) != previous["case_hash"]:
        raise ValueError("resume must use the original fixed Case")
    if selection and args.case and digest(_case(args.case)) != digest(case):
        raise ValueError("explicit Case differs from the frozen experiment member")
    subject = selection.get("subject") or (read_json(args.subject) if args.subject else (
        previous.get("subject") if previous else {"identity": "unknown", "note": "service build identity not advertised"}))
    if not isinstance(subject, dict) or not subject:
        raise ValueError("subject must be a nonempty JSON object")
    if selection and args.subject and read_json(args.subject) != subject:
        raise ValueError("explicit subject differs from the frozen experiment member")
    identity = {"trial_id": selection.get("trial_id", args.trial_id),
                "repetition": selection.get("repetition", previous.get("repetition", args.repetition)
                                             if previous else args.repetition),
                "environment_policy": selection.get("environment_policy",
                    previous.get("environment_policy", "isolated") if previous else "isolated")}
    if selection:
        identity["planned_definition_hash"] = selection["grading_definition_hash"]
        identity["planned_grading_config"] = plan.get("grading_config")
    return case, subject, identity


def _run(args) -> dict:
    if not args.execute:
        raise ValueError("--execute is required for execution or resume with potentially unsent actions")
    output = private_output(result_path(args.output))
    library = private_output(args.library)
    case, subject, identity = _trial_input(args)
    unknown = [item["evaluator"] for item in case["checks"]
               if item["kind"] == "rule" and item["evaluator"] not in RULES]
    if unknown:
        raise ValueError("unregistered deterministic checks: " + ", ".join(unknown))
    # Grader configuration is validated BEFORE submitting teaching work.
    settings = _settings(args) if any(item["kind"] == "llm" for item in case["checks"]) else None
    planned_definition = identity.pop("planned_definition_hash", None)
    settings = _settings_for_plan(settings, identity.pop("planned_grading_config", None))
    if planned_definition and planned_definition != grading_definition_hash(case, settings):
        raise ValueError("Grader settings differ from the frozen experiment; no business command was sent")
    with HyperknowAdapter(args.base_url, args.data_dir, fixture_manifest=args.fixture_manifest) as adapter:
        state = execute_trial(case, adapter, output, execute=True, resume=args.command == "resume",
                              subject=subject, **identity)
    export_trial_trajectories(output)
    # A partial Trial may contain useful evidence. The scorer owns missing-output handling.
    state = grade_trial(output, rules=RULES, settings=settings, execute=True)
    collect_sample(state, library)
    return summarize_trial(state)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = _parser()
    arguments = sys.argv[1:] if argv is None else argv
    removed = {"prepare": "validate / publish", "run": "execute / resume",
               "grade": "regrade", "show": "report --result"}
    if arguments and arguments[0] in removed:
        parser.error(f"{arguments[0]} was removed; use {removed[arguments[0]]}. "
                     "Historical schema-v1 results support only report --result; "
                     "migrate converts Cases, not saved executions.")
    args = parser.parse_args(arguments)
    try:
        if args.command == "validate":
            case = _case(args.case)
            result = {"case_id": case["id"], "case_hash": digest(case), "schema_version": 2,
                      "calls": 0, "review_status": "not_inferred", "checks": len(case["checks"])}
        elif args.command == "migrate":
            if args.output.exists():
                raise ValueError("migration never overwrites an existing file")
            case = migrate_case(read_json(args.case))
            write_json(args.output, case)
            result = {"case_hash": digest(case), "path": str(args.output), "calls": 0}
        elif args.command == "publish":
            path = publish_case(_case(args.case), private_output(args.library), reviewed_by=args.reviewed_by)
            result = {"path": str(path), "calls": 0}
        elif args.command == "benchmark":
            path = freeze_benchmark(read_json(args.manifest), private_output(args.library))
            result = {"path": str(path), "calls": 0}
        elif args.command == "fixture":
            if args.output.exists():
                raise ValueError("fixture manifests are immutable; use a new output path")
            manifest = export_fixture_manifest(args.data_dir, origin=args.origin,
                bindings=read_json(args.bindings), resource_sources=read_json(args.resource_sources))
            write_json(private_output(args.output), manifest)
            result = {"path": str(args.output), "calls": 0, "manifest_hash": digest(manifest)}
        elif args.command == "experiment":
            if args.output.exists():
                raise ValueError("an experiment definition is immutable; use a new output path")
            record = read_json(args.benchmark)
            benchmark = record.get("benchmark", record)
            if "members" in benchmark:
                cases = []
                for member in benchmark["members"]:
                    case = _case(args.library / "cases" / f"{member['case_hash']}.json")
                    if (digest(case) != member["case_hash"] or case["id"] != member["id"]
                            or case["version"] != member["version"]):
                        raise ValueError("published Benchmark member identity differs from its fixed content")
                    cases.append(case)
                benchmark = {**benchmark, "cases": cases,
                             "source_benchmark_hash": record.get("benchmark_hash", digest(benchmark))}
            if args.grading_config:
                benchmark = {**benchmark, "grading_config": _public_grading_config(read_json(args.grading_config))}
            elif any(check["kind"] == "llm" for member in benchmark["cases"]
                     for check in member.get("case", member)["checks"]):
                raise ValueError("LLM-graded experiment requires --grading-config before its matrix is frozen")
            result = build_experiment(benchmark, read_json(args.subjects), args.repetitions)
            write_json(private_output(args.output), result)
        elif args.command in {"execute", "resume"}:
            result = _run(args)
        elif args.command == "regrade":
            state = _result(args.output)
            settings = _settings(args) if any(c["kind"] == "llm" for c in state["case"]["checks"]) else None
            library = private_output(args.library)
            state = grade_trial(private_output(result_path(args.output)), rules=RULES, settings=settings,
                                execute=args.execute, regrade=True)
            collect_sample(state, library)
            result = summarize_trial(state)
        elif args.command == "report":
            values = [_result(path, allow_legacy=True) for path in args.result]
            legacy = any(value.get("schema_version") == 1 for value in values)
            if legacy and (args.experiment or args.html):
                raise ValueError("historical schema-v1 results support only read-only JSON report; "
                                 "no v2 experiment binding or HTML conversion")
            experiment = validate_experiment(read_json(args.experiment)) if args.experiment else None
            if args.experiment:
                result = report_experiment(experiment, values)
            elif values:
                result = {"trials": [summarize_legacy_result(value) if value.get("schema_version") == 1
                                     else summarize_trial(value) for value in values], "calls": 0}
                if legacy:
                    result["legacy_read_only"] = True
            else:
                raise ValueError("report requires --result or --experiment")
            if args.html:
                from eval_core.html_report import report_bundle, write_html
                write_html(private_output(args.html), report_bundle(values, experiment))
        elif args.command == "review":
            from eval_core.review import publish_review, refresh_review
            directory = private_output(args.review_dir)
            snapshot = None
            if args.result or args.experiment:
                bundle, sources = _review_bundle(args)
                _publish_run_report(bundle, sources)
                snapshot = publish_review(directory, bundle, sources)
            index = refresh_review(directory)
            _publish_workspace_home(directory)
            result = {"index": str(index), "snapshot": str(snapshot) if snapshot else None, "calls": 0}
        else:
            baseline, candidate = ([_result(path) for path in paths]
                                   for paths in (args.baseline, args.candidate))
            result = compare_results(baseline, candidate)
            if args.html:
                from eval_core.html_report import comparison_bundle, write_html
                write_html(private_output(args.html), comparison_bundle(baseline, candidate))
        if args.command in {"execute", "resume", "regrade", "report", "compare"} and not result.get("legacy_read_only"):
            _publish_review(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if args.command in {"execute", "resume", "regrade"}:
            return 0 if result.get("passed") else 1 if result.get("status") == "failed" else 2
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__, "message": str(exc)},
                         ensure_ascii=False))
        return 2
    except Exception as exc:
        # Transport/provider exceptions can contain secrets. Preserve type, never arbitrary text.
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        return 2
