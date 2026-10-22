"""Opt-in real model/API acceptance. Missing configuration exits blocked (2)."""

import argparse
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

import httpx


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--goal", default="我会 Python 基础，想用两周理解 asyncio，并完成一个并发请求小工具。")
    parser.add_argument("--skip", action="store_true", help="Explicitly skip clarification")
    parser.add_argument("--output", default="data/validation/real-course.json")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=15, trust_env=False) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        if not health.json()["model"]["configured"]:
            print("BLOCKED: configure OPENAI_API_KEY in the local .env and restart the backend. No model call made.")
            return 2
        created = client.post("/api/course-runs", json={"goal": args.goal, "client_command_id": str(uuid4())})
        created.raise_for_status()
        run = wait_for(client, created.json()["run_id"], {"awaiting_answers"}, time.monotonic() + 260)
        answers = [] if args.skip else [{"question_id": q["id"], "option_ids": [q["options"][0]["id"]],
                                        "custom_text": ""} for q in run["questions"]]
        submitted = client.post(f"/api/runs/{run['run_id']}/answers", json={
            "client_command_id": str(uuid4()), "expected_version": run["version"], "skip": args.skip, "answers": answers})
        submitted.raise_for_status()
        result = wait_for(client, run["run_id"], {"ready"}, time.monotonic() + 260)
        course_response = client.get(f"/api/courses/{result['course_id']}")
        course_response.raise_for_status()
        course = course_response.json()
        assert course["session_count"] > 0 and course["units"]
        assert any(c["course_id"] == course["course_id"] for c in client.get("/api/courses").json()["courses"])
        assert client.get(f"/api/courses/{course['course_id']}").json() == course
        evidence = {"scope": "real model and HTTP course-generation slice; not browser or restart acceptance",
                    "health": health.json(), "run": result, "course": course, "answers_sent": answers}
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"REAL MODEL/API SLICE PASSED: {course['course_id']} ({course['session_count']} sessions). Evidence: {path}")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (httpx.HTTPError, RuntimeError, AssertionError) as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)
