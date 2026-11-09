"""Run the teacher-led classroom against a real model and isolated SQLite."""

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
from hyperknow.storage import Database, encode, storage_identity


ROOT = Path(__file__).resolve().parents[1]


def save(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_course(source: Path, course_id: str, session_id: str) -> tuple[dict, dict, dict]:
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        row = conn.execute("SELECT data FROM courses WHERE id=?", (course_id,)).fetchone()
        if row is None:
            raise ValueError("source course does not exist")
        course = json.loads(row[0])
        sessions = {s["session_id"]: s for unit in course["units"]
                    for lecture in unit["lectures"] for s in lecture["sessions"]}
        if session_id not in sessions:
            raise ValueError("session does not belong to source course")
        creation = course.get("creation_run_id")
        run = conn.execute("SELECT data FROM runs WHERE id=?", (creation,)).fetchone() if creation else None
    return course, json.loads(run[0]) if run else None, sessions[session_id]


def start_server(data_dir: Path, port: int, log):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    env = {**os.environ, "HK_DATA_DIR": str(data_dir)}
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "hyperknow.main:app",
                             "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)


def stop_server(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def wait_health(client: httpx.Client, process, data_dir: Path):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("owned backend exited during startup")
        try:
            health = client.get("/api/health")
            if health.status_code == 200:
                body = health.json()
                if body.get("storage_id") != storage_identity(data_dir / "hyperknow.sqlite3"):
                    raise RuntimeError("backend storage identity mismatch")
                return body
        except httpx.TransportError:
            pass
        time.sleep(.1)
    raise RuntimeError("backend did not become healthy")


def body(response: httpx.Response):
    response.raise_for_status()
    return response.json()


def wait_run(client: httpx.Client, run_id: str, deadline: float):
    while time.monotonic() < deadline:
        run = body(client.get(f"/api/runs/{run_id}"))
        if run["status"] == "ready":
            return run
        if run["status"] in {"failed", "cancelled", "interrupted"}:
            raise RuntimeError(f"run {run_id} stopped: {run.get('error')}")
        time.sleep(.5)
    raise RuntimeError(f"run {run_id} exceeded the deadline")


def command():
    return str(uuid4())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="authorize real paid model calls")
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8047)
    parser.add_argument("--deadline-seconds", type=int, default=600)
    args = parser.parse_args()
    if not args.execute:
        print("BLOCKED: --execute is required; no model call or database write made")
        return 2
    settings = Settings.load()
    if not settings.api_key:
        print("BLOCKED: real model credentials are not configured")
        return 2
    source = (args.source_db or settings.data_dir / "hyperknow.sqlite3").resolve()
    allowed = (ROOT / "data" / "validation").resolve()
    data_dir = args.data_dir.resolve()
    if not data_dir.is_relative_to(allowed) or data_dir == allowed:
        raise ValueError("data-dir must be a fresh child of data/validation")
    if data_dir.exists() and any(data_dir.iterdir()):
        raise ValueError("data-dir must be empty; do not overwrite earlier evidence")
    course, creation_run, session = read_course(source, args.course_id, args.session_id)
    source_hash = hashlib.sha256(encode(course).encode()).hexdigest()
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / "hyperknow.sqlite3")
    with db.transaction() as conn:
        db._write(conn, "courses", course["course_id"], course)
        if creation_run:
            db._write(conn, "runs", creation_run["run_id"], creation_run)
    evidence_path = data_dir / "teacher-classroom-evidence.json"
    evidence = {"scope": "real model teacher-led classroom; not mastery evidence",
                "model": settings.model, "course_id": args.course_id, "session_id": args.session_id,
                "source_course_sha256": source_hash, "status": "started", "turns": []}
    save(evidence_path, evidence)
    with (data_dir / "backend.log").open("a", encoding="utf-8") as log:
        process = start_server(data_dir, args.port, log)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=30,
                              trust_env=False, follow_redirects=False) as client:
                health = wait_health(client, process, data_dir)
                if not health["model"]["configured"]:
                    raise RuntimeError("isolated backend does not report configured model")
                route = f"/api/sessions/{args.session_id}"
                snapshot = body(client.get(route))
                if snapshot["protocol"] != "teacher_led" or snapshot["teacher"] is not None:
                    raise AssertionError("fresh session did not start in teacher-led unprepared state")
                prepare = {"client_command_id": command()}
                snapshot = body(client.post(route + "/teacher/prepare", json=prepare))
                basis_run = snapshot["generation_run"]
                wait_run(client, basis_run["run_id"], time.monotonic() + args.deadline_seconds)
                snapshot = body(client.get(route))
                if not snapshot["teacher"]["basis"] or not snapshot["teacher"]["basis"]["references"]:
                    raise AssertionError("saved teaching basis has no traceable references")
                evidence["basis_run_id"] = basis_run["run_id"]
                evidence["basis_reference_count"] = len(snapshot["teacher"]["basis"]["references"])
                save(evidence_path, evidence)

                answers = [
                    "我理解暂停点会让出当前执行机会，另一个任务可以继续。",
                    "我觉得 await 就是把线程完全阻塞住，其他任务也不能执行。",
                    "我还是分不清暂停和阻塞分别改变了什么，也不知道下一步看哪里。",
                    "如果暂停只发生在协作式切换点，那么这个例子里的状态变化已经清楚了。",
                ]
                command_for_replay = None
                for index, answer in enumerate(answers):
                    expected = snapshot["teacher"]["version"]
                    payload = {"client_command_id": command(), "expected_version": expected,
                               "student_answer": answer}
                    if index == 0:
                        command_for_replay = dict(payload)
                    snapshot = body(client.post(route + "/teacher/turns", json=payload))
                    run = snapshot["generation_run"]
                    wait_run(client, run["run_id"], time.monotonic() + args.deadline_seconds)
                    snapshot = body(client.get(route))
                    turn = snapshot["teacher"]["turns"][-1]
                    evidence["turns"].append({"index": turn["index"], "student_answer": answer,
                                              "action": turn["action"], "response": turn["response"],
                                              "awaits_student": turn["awaits_student"],
                                              "basis_refs": turn["basis_refs"],
                                              "board_object_ids": turn["board_object_ids"],
                                              "run_id": turn["run_id"]})
                    save(evidence_path, evidence)
                count = len(snapshot["teacher"]["turns"])
                replay = body(client.post(route + "/teacher/turns", json=command_for_replay))
                if len(replay["teacher"]["turns"]) != count:
                    raise AssertionError("same teacher command created a duplicate turn")
                evidence["idempotent_replay"] = True

                expected = snapshot["teacher"]["version"]
                cancel_snapshot = body(client.post(route + "/teacher/turns", json={
                    "client_command_id": command(), "expected_version": expected,
                    "student_answer": "请再从一个具体状态变化开始。"}))
                cancel_run = cancel_snapshot["generation_run"]
                current_run = body(client.get(f"/api/runs/{cancel_run['run_id']}"))
                body(client.post(f"/api/runs/{cancel_run['run_id']}/cancel", json={
                    "client_command_id": command(), "expected_version": current_run["version"]}))
                stopped = body(client.get(route))
                if not stopped["teacher"]["stop_reason"]:
                    raise AssertionError("cancelled turn has no explicit stop reason")
                evidence["cancel_stop_reason"] = stopped["teacher"]["stop_reason"]
                cancelled_run = body(client.get(f"/api/runs/{cancel_run['run_id']}"))
                retry_run = body(client.post(f"/api/runs/{cancel_run['run_id']}/retry", json={
                    "client_command_id": command(), "expected_version": cancelled_run["version"]}))
                retry_state = body(client.get(f"/api/runs/{retry_run['run_id']}"))
                if retry_state["status"] in {"queued", "generating"}:
                    body(client.post(f"/api/runs/{retry_run['run_id']}/cancel", json={
                        "client_command_id": command(), "expected_version": retry_state["version"]}))
                    retry_state = body(client.get(f"/api/runs/{retry_run['run_id']}"))
                if retry_state["status"] not in {"ready", "cancelled"}:
                    raise AssertionError(f"retry ended unexpectedly: {retry_state['status']}")
                retried = body(client.get(route))
                evidence["retry_run_id"] = retry_run["run_id"]
                evidence["retry_status"] = retry_state["status"]
                evidence["retry_completed"] = retry_state["status"] == "ready"
                evidence["retry_stop_reason"] = retried["teacher"]["stop_reason"]
                evidence["retry_turn_count"] = len(retried["teacher"]["turns"])
                save(evidence_path, evidence)
        finally:
            stop_server(process)
    db = Database(data_dir / "hyperknow.sqlite3")
    calls = [call for run in db.list_records("runs") if run.get("session_id") == args.session_id
             for call in db.calls(run["run_id"])]
    evidence["model_call_count"] = len(calls)
    evidence["tool_call_count"] = sum(len(call.get("tool_calls", [])) for call in calls)
    evidence["status"] = "passed"
    evidence["source_unchanged"] = hashlib.sha256(encode(read_course(source, args.course_id, args.session_id)[0]).encode()).hexdigest() == source_hash
    if not evidence["source_unchanged"]:
        raise AssertionError("source course changed")
    with (data_dir / "backend.log").open("a", encoding="utf-8") as log:
        process = start_server(data_dir, args.port, log)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=30,
                              trust_env=False, follow_redirects=False) as client:
                wait_health(client, process, data_dir)
                recovered = body(client.get(f"/api/sessions/{args.session_id}"))
                if len(recovered["teacher"]["turns"]) != evidence["retry_turn_count"]:
                    raise AssertionError("cold restart changed the saved teacher turn count")
                evidence["cold_restart_without_generation"] = True
        finally:
            stop_server(process)
    save(evidence_path, evidence)
    print(f"REAL TEACHER CLASSROOM ACCEPTANCE {evidence_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, AssertionError, httpx.HTTPError, OSError) as exc:
        data_arg = next((sys.argv[index + 1] for index, value in enumerate(sys.argv[:-1])
                         if value == "--data-dir"), None)
        if data_arg:
            evidence_path = Path(data_arg) / "teacher-classroom-evidence.json"
            if evidence_path.exists():
                failed = json.loads(evidence_path.read_text(encoding="utf-8"))
                failed.update(status="failed", error=str(exc))
                save(evidence_path, failed)
        print(f"FAILED: {exc}")
        sys.exit(1)
