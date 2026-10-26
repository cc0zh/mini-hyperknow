"""Opt-in real model/API acceptance. Missing configuration exits blocked (2)."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

import httpx

from hyperknow.research_domain import ResearchReport, validate_report
from hyperknow.storage import Database


def wait_for(client, run_id, wanted, deadline):
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["status"] in wanted:
            return run
        if run["status"] in {"failed", "cancelled", "interrupted"}:
            raise RuntimeError(f"real run ended as {run['status']}: {run.get('error')}")
        time.sleep(1)
    raise RuntimeError("real model acceptance timed out; inspect the run before retrying")


def verify_research(run):
    research = run["research"]
    validate_report(ResearchReport.model_validate(research["report"]), research)
    for source in research["sources"]:
        assert hashlib.sha256(source["text"].encode("utf-8")).hexdigest() == source["content_sha256"]


def verify_planning_calls(data_dir, run, course):
    """Optional local evidence audit; never invokes or substitutes a provider."""
    db = Database(Path(data_dir) / "hyperknow.sqlite3")
    calls = db.calls(run["run_id"])
    sources = {source["source_id"]: source for source in run["research"]["sources"]}
    planning = [call for call in calls if call["phase"] in {"blueprint", "units"} and call.get("validated")]
    assert any(call["phase"] == "blueprint" for call in planning)
    assert len([call for call in planning if call["phase"] == "units"]) == len(course["units"])
    for call in planning:
        basis = call["input_basis"]
        assert basis["research_report"] == run["research"]["report"]
        assert len(json.dumps(basis, ensure_ascii=False).encode("utf-8")) <= basis["budget_bytes"]
        assert basis["sources"] and any(source["context_excerpt"] for source in basis["sources"])
        for source in basis["sources"]:
            saved = sources[source["source_id"]]
            assert source["content_sha256"] == saved["content_sha256"]
            assert saved["text"].startswith(source["context_excerpt"])
        if call["phase"] == "units":
            assert basis["approved_blueprint_version"] == course["blueprint_version"]
    return [{key: call.get(key) for key in ("phase", "model", "usage", "elapsed_ms", "validated")}
            for call in calls]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--goal", default="我会 Python 基础，想用两周理解 asyncio，并完成一个并发请求小工具。")
    parser.add_argument("--skip", action="store_true", help="Explicitly skip clarification")
    parser.add_argument("--approve-blueprint", action="store_true",
                        help="Explicitly approve the real generated blueprint and expand every unit")
    parser.add_argument("--output", default="data/validation/real-course.json")
    parser.add_argument("--data-dir", help="Optionally audit actual local model_calls from this server's data directory")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=15, trust_env=False) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        if not health.json()["model"]["configured"]:
            print("BLOCKED: configure OPENAI_API_KEY in the local .env and restart the backend. No model call made.")
            return 2
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        command = {"goal": args.goal, "client_command_id": str(uuid4())}
        pending = {"scope": "real course acceptance; no automatic replay", "create_command": command,
                   "status": "unconfirmed", "run_id": None}
        path.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
        created = client.post("/api/course-runs", json=command)
        if created.status_code == 503 and created.json().get("error", {}).get("code") == "search_not_configured":
            print("BLOCKED: configure TAVILY_API_KEY locally and restart the backend. No run was created.")
            return 2
        created.raise_for_status()
        pending.update(run_id=created.json()["run_id"], status="accepted")
        path.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
        run = wait_for(client, created.json()["run_id"],
                       {"awaiting_answers", "generating", "awaiting_blueprint"}, time.monotonic() + 260)
        answers = []
        clarification_mode = "not_required"
        if run["status"] == "awaiting_answers":
            assert run["questions"], "An empty clarification must advance automatically"
            clarification_mode = "skipped" if args.skip else "answered"
            answers = [] if args.skip else [{"question_id": q["id"], "option_ids": [q["options"][0]["id"]],
                                            "custom_text": ""} for q in run["questions"]]
            submitted = client.post(f"/api/runs/{run['run_id']}/answers", json={
                "client_command_id": str(uuid4()), "expected_version": run["version"], "skip": args.skip, "answers": answers})
            submitted.raise_for_status()
        else:
            assert run["questions"] == [] and run["answers_submitted"] and not run["skipped"]
            assert run["stage"] in {"research", "blueprint"}
        blueprint_run = wait_for(client, run["run_id"], {"awaiting_blueprint"}, time.monotonic() + 600)
        verify_research(blueprint_run)
        blueprint = client.get(f"/api/courses/{blueprint_run['course_id']}").json()
        assert blueprint["structure_status"] == "blueprint" and blueprint["session_count"] == 0
        assert all(not unit["lectures"] for unit in blueprint["units"])
        # A second GET cannot approve the blueprint or start unit generation.
        assert client.get(f"/api/runs/{run['run_id']}").json()["status"] == "awaiting_blueprint"
        if not args.approve_blueprint:
            path.write_text(json.dumps({"scope": "blueprint saved; awaiting explicit approval, not complete course acceptance",
                                        "create_command": command, "clarification_mode": clarification_mode,
                                        "run": blueprint_run, "blueprint": blueprint}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"WAITING: blueprint saved for {run['run_id']}; approve in the UI. Use --approve-blueprint only for explicit automated acceptance.")
            return 2
        confirmed = client.post(f"/api/runs/{run['run_id']}/blueprint", json={
            "client_command_id": str(uuid4()), "expected_version": blueprint_run["version"],
            "approve": True, "feedback": ""})
        confirmed.raise_for_status()
        result = wait_for(client, run["run_id"], {"ready"}, time.monotonic() + 900)
        course_response = client.get(f"/api/courses/{result['course_id']}")
        course_response.raise_for_status()
        course = course_response.json()
        assert course["session_count"] > 0 and course["units"] and course["structure_status"] == "ready"
        assert all(unit["generation_status"] == "ready" for unit in course["units"])
        assert any(c["course_id"] == course["course_id"] for c in client.get("/api/courses").json()["courses"])
        assert client.get(f"/api/courses/{course['course_id']}").json() == course
        evidence = {"scope": "real model and HTTP course-generation slice; not browser or restart acceptance",
                    "health": health.json(), "run": result, "course": course, "answers_sent": answers,
                    "blueprint_before_confirmation": blueprint, "confirmation": confirmed.json(),
                    "create_command": command, "clarification_mode": clarification_mode}
        if args.data_dir:
            evidence["audited_model_calls"] = verify_planning_calls(args.data_dir, result, course)
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"REAL MODEL/API SLICE PASSED: {course['course_id']} ({course['session_count']} sessions). Evidence: {path}")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (httpx.HTTPError, RuntimeError, AssertionError) as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)
