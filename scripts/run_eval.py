"""Prepare one Case, run the real backend, grade saved output, or show saved results."""

import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

from hyperknow.eval_cases import collect_sample, grading_budget, load_case, prepare_case, read_json
from hyperknow.eval_grading import GraderSettings
from hyperknow.evaluation import (collect_result, grade_result, private_output,
                                 run_business, summary)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE = ROOT / "evals/concept-explanation/case.json"
DEFAULT_LIBRARY = ROOT / "data/evals/cases"


def grader_settings(args) -> GraderSettings:
    load_dotenv(ROOT / ".env", override=False)
    return GraderSettings(
        model=args.grader_model or os.getenv("HK_EVAL_GRADER_MODEL", ""),
        api_key=os.getenv("HK_EVAL_GRADER_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        base_url=args.grader_base_url or os.getenv("HK_EVAL_GRADER_BASE_URL")
                 or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        timeout=args.grader_timeout, max_output_tokens=args.grader_max_output_tokens)


def add_grader_options(parser):
    parser.add_argument("--grader-model", help="explicit grader model; or HK_EVAL_GRADER_MODEL")
    parser.add_argument("--grader-base-url", help="or HK_EVAL_GRADER_BASE_URL; otherwise the configured OPENAI endpoint")
    parser.add_argument("--grader-timeout", type=float, default=90)
    parser.add_argument("--grader-max-output-tokens", type=int, default=2048)
    parser.add_argument("--execute", action="store_true", help="authorize this command's real, potentially billable calls")


def collect_after_error(args):
    if args.command != "run" or not (args.output / "result.json").is_file():
        return
    try:
        collect_result(args.output, args.library)
    except Exception:
        print("Result retained locally; sample collection is deferred", file=sys.stderr)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="data Pipeline: validate/freeze a Case or collect an existing result; no model call")
    source = prepare.add_mutually_exclusive_group()
    source.add_argument("--case", type=Path, default=None)
    source.add_argument("--from-result", type=Path)
    prepare.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    run = commands.add_parser("run", help="business Pipeline: one real teaching run followed by one LLM grade")
    run.add_argument("--case", type=Path, default=DEFAULT_CASE)
    run.add_argument("--base-url", default="http://127.0.0.1:8039")
    run.add_argument("--data-dir", type=Path, required=True, help="data directory of the separately started isolated backend")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    run.add_argument("--resume", action="store_true", help="recover the persisted command/run; never create a new attempt")
    run.add_argument("--wait-seconds", type=float, default=420)
    add_grader_options(run)
    grade = commands.add_parser("grade", help="one explicitly authorized regrade of saved evidence, never reruns teaching")
    grade.add_argument("--output", type=Path, required=True)
    grade.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    add_grader_options(grade)
    show = commands.add_parser("show", help="read/reprint saved results, with no backend/provider request")
    show.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            library = private_output(args.library)
            if args.from_result:
                path = collect_sample(read_json(args.from_result), library, args.from_result)
            else:
                path = prepare_case(load_case(args.case or DEFAULT_CASE), library)
            print(json.dumps({"case_record": str(path), "calls": 0}, ensure_ascii=False))
            return 0
        if args.command == "show":
            print(json.dumps(summary(read_json(args.output / "result.json")), ensure_ascii=False, indent=2))
            return 0
        if not args.execute:
            raise ValueError("--execute is required; prepare and show are the no-fee commands")
        private_output(args.library)
        previous = None
        if args.command == "run" and args.resume and (args.output / "result.json").exists():
            previous = read_json(args.output / "result.json")
        # Settings must be usable before a new teaching run can incur costs.
        settings = None if previous and previous.get("grades") else grader_settings(args)
        if args.command == "run":
            case = previous["case"] if previous else load_case(args.case)
            prepare_case(case, private_output(args.library))
            state = run_business(case, base_url=args.base_url, data_dir=args.data_dir, output=args.output,
                                 execute=True, resume=args.resume, wait_seconds=args.wait_seconds)
            if state["stage"] == "collected":
                state = grade_result(args.output, settings=settings, execute=True)
        else:
            state = grade_result(args.output, settings=settings, execute=True, regrade=True)
        collect_result(args.output, args.library)
        print(json.dumps(summary(state), ensure_ascii=False, indent=2))
        if state["stage"] != "collected" or not state.get("grades") or state["grades"][-1]["status"] != "completed":
            return 2
        if grading_budget(state["grades"][-1])["status"] == "exceeded":
            return 2
        return 1 if summary(state)["label"] == "bad" else 0 if summary(state)["label"] == "good" else 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        collect_after_error(args)
        print(f"Evaluation blocked: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        collect_after_error(args)
        # Provider/transport exceptions can contain credentials; do not echo arbitrary exception text.
        print(f"Evaluation failed: {type(exc).__name__}; inspect the private result file if present", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
