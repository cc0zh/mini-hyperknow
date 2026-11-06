"""Opt-in real classroom acceptance against an isolated copy of a saved course.

No model doubles, response replay, fake course or source-database writes. The
source course must already exist; this checks classroom generation, not course
planning. Commands and unknown outcomes are recorded before any paid request.
"""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

import httpx

from hyperknow.config import Settings
from hyperknow.lesson_domain import BoardScript
from hyperknow.storage import Database, encode, storage_identity


ROOT = Path(__file__).resolve().parents[1]


def write_evidence(path: Path, evidence: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_source(source: Path, course_id: str, session_ids: list[str]):
    """Read only the selected genuine course and its creation receipt."""
    if not source.is_file():
        raise ValueError("source database does not exist")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        row = conn.execute("SELECT data FROM courses WHERE id=?", (course_id,)).fetchone()
        if row is None:
            raise ValueError("selected course does not exist in the source database")
        course = json.loads(row[0])
        sessions = {s["session_id"]: s for u in course["units"]
                    for lecture in u["lectures"] for s in lecture["sessions"]}
        if not session_ids or len(set(session_ids)) != len(session_ids) or any(s not in sessions for s in session_ids):
            raise ValueError("select distinct session ids from this actual saved course")
        run_id = course.get("creation_run_id")
        run = conn.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone() if run_id else None
    return course, json.loads(run[0]) if run else None, sessions


def command_payload(snapshot: dict):
    return {"client_command_id": str(uuid4()), "script_id": snapshot["script"]["script_id"],
            "expected_version": snapshot["progress"]["version"]}


def json_response(response: httpx.Response):
    response.raise_for_status()
    return response.json()


def wait_run(client: httpx.Client, run_id: str, deadline: float):
    while time.monotonic() < deadline:
        run = json_response(client.get(f"/api/runs/{run_id}"))
        if run["status"] == "ready":
            return run
        if run["status"] in {"failed", "cancelled", "interrupted"}:
            raise RuntimeError(f"real run {run_id} ended as {run['status']}: {run.get('error')}")
        time.sleep(1)
    raise RuntimeError(f"run {run_id} exceeded acceptance deadline; no retry was sent")


def start_server(data_dir: Path, port: int, log):
    # Refuse to use or stop any process we do not own.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    env = {**os.environ, "HK_DATA_DIR": str(data_dir)}
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "hyperknow.main:app",
                                "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT,
                               env=env, stdout=log, stderr=subprocess.STDOUT)
    return process


def wait_health(client: httpx.Client, process, data_dir: Path):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("owned backend exited during startup; inspect backend.log")
        try:
            response = client.get("/api/health")
            if response.status_code == 200:
                health = response.json()
                if health.get("storage_id") != storage_identity(data_dir / "hyperknow.sqlite3"):
                    raise RuntimeError("backend storage identity mismatch; no command sent")
                return health
        except httpx.TransportError:
            pass
        time.sleep(.1)
    raise RuntimeError("owned backend did not become healthy")


def stop_server(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def verify_session(client, session_id, item, path, evidence, deadline_seconds, advance_all):
    route = f"/api/sessions/{session_id}"
    snapshot = json_response(client.get(route))
    if snapshot["script"] is None:
        if not snapshot["generation_run"]:
            if item.get("prepare_command"):
                raise RuntimeError("prior prepare outcome unknown; inspect evidence, do not automatically replay")
            item["prepare_command"] = {"client_command_id": str(uuid4())}
            item["status"] = "prepare_in_flight"
            write_evidence(path, evidence)
            snapshot = json_response(client.post(route + "/prepare", json=item["prepare_command"]))
        run = snapshot["generation_run"]
        if run is None:
            raise RuntimeError("prepare returned no actual generation run")
        item.update(status="generating", run_id=run["run_id"])
        write_evidence(path, evidence)
        wait_run(client, run["run_id"], time.monotonic() + deadline_seconds)
        snapshot = json_response(client.get(route))
    script = BoardScript.model_validate(snapshot["script"]).model_dump()
    if script["schema_version"] != 2:
        raise AssertionError("new classroom protocol required; no compatibility path")
    item.update(script_id=script["script_id"], run_id=snapshot["generation_run"]["run_id"],
                steps=len(script["steps"]), roadmap=script["roadmap"],
                operation_kinds=sorted({o["kind"] for s in script["steps"] for o in s["operations"]}),
                status="generated")
    # Reading the real snapshot must not advance or enqueue model work.
    assert json_response(client.get(route)) == snapshot
    early = client.post(route + "/complete", json=command_payload(snapshot)) if snapshot["progress"]["cursor"] == -1 else None
    if early is not None:
        assert early.status_code == 409 and early.json()["error"]["code"] == "lesson_incomplete"
        item["early_completion_rejected"] = True
    write_evidence(path, evidence)
    # Confirm every step through the actual command API; never jump the cursor.
    if advance_all:
        for cursor in range(snapshot["progress"]["cursor"] + 1, len(script["steps"])):
            payload = {**command_payload(snapshot), "cursor": cursor, "play_intent": "paused"}
            snapshot = json_response(client.put(route + "/progress", json=payload))
    assert script["steps"][-1]["stage"] == "summary"
    item["summary_reached"] = snapshot["progress"]["cursor"] == len(script["steps"]) - 1
    item["confirmed_cursor"] = snapshot["progress"]["cursor"]
    item["snapshot_version"] = snapshot["version"]
    item["status"] = "ready_for_browser"
    write_evidence(path, evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicit authorization for real paid model calls")
    parser.add_argument("--source-db", type=Path, help="Read-only source; defaults to configured HK_DATA_DIR")
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--session-id", action="append", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8046)
    parser.add_argument("--deadline-seconds", type=int, default=600)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keep-first-unplayed", action="store_true",
                        help="Leave the first real lesson at its opening for browser player acceptance")
    args = parser.parse_args()
    if not args.execute:
        print("BLOCKED: --execute is required; no database or model command was written")
        return 2
    settings = Settings.load()
    args.source_db = args.source_db or settings.data_dir / "hyperknow.sqlite3"
    if not settings.api_key:
        print("BLOCKED: local model credentials are not configured; no model call made")
        return 2
    data_dir = args.data_dir.resolve()
    allowed = (ROOT / "data" / "validation").resolve()
    if not data_dir.is_relative_to(allowed) or data_dir == allowed:
        raise ValueError("data-dir must be a dedicated child of data/validation")
    if args.source_db.resolve() == data_dir / "hyperknow.sqlite3":
        raise ValueError("source database must never be the acceptance database")
    course, run, sessions = read_source(args.source_db, args.course_id, args.session_id)
    source_hash = hashlib.sha256(encode(course).encode()).hexdigest()
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "classroom-acceptance.json"
    if path.exists():
        if not args.resume:
            raise ValueError("evidence exists; use --resume rather than issuing duplicate generation commands")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence["course_sha256"] != source_hash or list(evidence["sessions"]) != args.session_id:
            raise ValueError("resume source or session selection changed")
    else:
        if (data_dir / "hyperknow.sqlite3").exists():
            raise ValueError("unowned database already exists; select a fresh acceptance directory")
        db = Database(data_dir / "hyperknow.sqlite3")
        with db.transaction() as conn:
            db._write(conn, "courses", course["course_id"], course)
            if run:
                db._write(conn, "runs", run["run_id"], run)
        evidence = {"scope": "real saved course + real new classroom HTTP generation; not course-planning or mastery evidence",
                    "course_id": course["course_id"], "course_sha256": source_hash,
                    "status": "started", "model": settings.model,
                    "sessions": {sid: {"title": sessions[sid]["title"], "status": "not_run"} for sid in args.session_id}}
        write_evidence(path, evidence)
    with (data_dir / "backend.log").open("a", encoding="utf-8") as log:
        process = start_server(data_dir, args.port, log)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=20,
                              trust_env=False, follow_redirects=False) as client:
                health = wait_health(client, process, data_dir)
                assert health["model"]["configured"]
                for index, (sid, item) in enumerate(evidence["sessions"].items()):
                    if item["status"] == "ready_for_browser":
                        continue
                    try:
                        verify_session(client, sid, item, path, evidence, args.deadline_seconds,
                                       not (args.keep_first_unplayed and index == 0))
                    except (httpx.HTTPError, ValueError, AssertionError, RuntimeError) as exc:
                        item.update(status="failed", error=str(exc))
                        write_evidence(path, evidence)
                evidence["status"] = "passed" if all(s["status"] == "ready_for_browser" for s in evidence["sessions"].values()) else "failed"
                write_evidence(path, evidence)
        finally:
            stop_server(process)
    db = Database(data_dir / "hyperknow.sqlite3")
    calls = [c for item in evidence["sessions"].values() if item.get("run_id")
             for c in db.calls(item["run_id"])]
    evidence["model_calls"] = [{k: c.get(k) for k in ("kind", "phase", "attempt", "model", "usage", "validated", "error")}
                               for c in calls]
    # Cold-start the actual server, not an in-memory substitute, and prove
    # ordinary reads neither advance a lesson nor enqueue paid model work.
    with (data_dir / "backend.log").open("a", encoding="utf-8") as log:
        process = start_server(data_dir, args.port, log)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=20,
                              trust_env=False, follow_redirects=False) as client:
                wait_health(client, process, data_dir)
                for sid, item in evidence["sessions"].items():
                    if item["status"] == "ready_for_browser":
                        recovered = json_response(client.get(f"/api/sessions/{sid}"))
                        assert recovered["script"]["script_id"] == item["script_id"]
                        assert recovered["progress"]["cursor"] == item["confirmed_cursor"]
        finally:
            stop_server(process)
    assert sum(len(db.calls(item["run_id"])) for item in evidence["sessions"].values() if item.get("run_id")) == len(calls)
    evidence["cold_restart_without_generation"] = True
    evidence["source_course_unchanged"] = hashlib.sha256(encode(read_source(args.source_db, args.course_id, args.session_id)[0]).encode()).hexdigest() == source_hash
    assert evidence["source_course_unchanged"]
    write_evidence(path, evidence)
    print(f"REAL CLASSROOM ACCEPTANCE {evidence['status'].upper()}: {path}")
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, AssertionError, httpx.HTTPError, OSError) as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)
