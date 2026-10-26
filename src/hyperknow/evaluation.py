"""Sequential real-HTTP evaluation; no alternative business engine or database."""

from contextlib import closing, contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
import httpx

from agent_core.skills import SkillRegistry
from agent_core.tokens import TokenCounter
from .eval_atif import export_trajectory, validate_trajectory
from .eval_cases import (case_hash, classify_result, collect_sample, digest, exclusive,
                         grading_budget, read_json, validate_case, write_json)
from .eval_grading import GraderSettings, grade_once, parse_grading_response
from .storage import encode, now, storage_identity


ROOT = Path(__file__).resolve().parents[2]
ACTIVE = {"queued", "generating"}


def private_output(path: Path) -> Path:
    path = path.resolve()
    if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT / "data"):
        raise ValueError("mutable evaluation evidence must be under ignored data/ or outside the repository")
    return path


def local_origin(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("the evaluation backend must be an explicit loopback HTTP origin")
    return url.rstrip("/")


def isolated_database(data_dir: Path) -> Path:
    directory = data_dir.resolve()
    configured = dotenv_values(ROOT / ".env").get("HK_DATA_DIR")
    protected = {(ROOT / "data").resolve()}
    if configured:
        protected.add((ROOT / configured).resolve())
    if directory in protected:
        raise ValueError("refusing the author's configured/default data directory; start an isolated backend")
    path = directory / "hyperknow.sqlite3"
    if not path.is_file():
        raise ValueError("start the isolated backend first; evaluation never creates or migrates its database")
    return path


@contextmanager
def readonly(path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn


def _row(conn, table: str, identity: str):
    if table not in {"runs", "assistance_conversations"}:
        raise ValueError("unsupported evidence table")
    row = conn.execute(f"SELECT data FROM {table} WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise ValueError(f"missing evidence: {table}/{identity}")
    return json.loads(row["data"])


def receipt(path: Path, command_id: str, expected_payload: dict):
    with readonly(path) as conn:
        row = conn.execute("SELECT * FROM command_receipts WHERE id=?", (command_id,)).fetchone()
    if row is None:
        return None
    expected = hashlib.sha256(encode(expected_payload).encode()).hexdigest()
    if row["resource_type"] != "conversation" or row["fingerprint"] != expected:
        raise ValueError("persisted command receipt does not match this exact command")
    return dict(row)


def check_backend(client: httpx.Client, database: Path, *, require_model: bool = True) -> dict:
    response = client.get("/api/health")
    response.raise_for_status()
    health = response.json()
    if health.get("storage_id") != storage_identity(database):
        raise ValueError("HTTP backend storage identity differs from --data-dir; no write request was sent")
    with readonly(database) as conn:
        if conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]:
            raise ValueError("the evaluation database must not contain courses")
        foreign = conn.execute("SELECT id FROM assistance_conversations WHERE id NOT IN "
                               "(SELECT run_id FROM command_receipts WHERE resource_type='conversation' "
                               "AND id LIKE 'eval-create-%') LIMIT 1").fetchone()
        if foreign:
            raise ValueError("the database contains conversations not created by this evaluation runner")
    if require_model and not health.get("model", {}).get("configured"):
        raise ValueError("the backend has no configured real teaching model")
    return health


def recover_conversation(client, database: Path, state: dict, save) -> str:
    command = state["commands"]["create"]
    payload = {"action": "create_assistance_conversation"}
    saved = receipt(database, command["client_command_id"], payload)
    if saved is None:
        if state.get("conversation_id") or state.get("run_id"):
            raise ValueError("known conversation has no receipt; possible database rollback, refusing to recreate it")
        response = client.post("/api/assistance/conversations", json=command)
        response.raise_for_status()
        saved = receipt(database, command["client_command_id"], payload)
    if saved is None:
        raise ValueError("conversation response has no corresponding receipt in the evaluation database")
    identity = saved["run_id"]  # The existing conversation receipt stores its conversation ID in this column.
    if state.get("conversation_id") not in {None, identity}:
        raise ValueError("conversation identity changed")
    state["conversation_id"] = identity
    save()
    response = client.get(f"/api/assistance/conversations/{identity}")
    response.raise_for_status()
    if response.json().get("conversation_id") != identity:
        raise ValueError("HTTP conversation does not match its saved command")
    return identity


def recover_turn(client, database: Path, state: dict, save) -> str:
    conversation_id = state["conversation_id"]
    route = f"/api/assistance/conversations/{conversation_id}"
    if state["commands"].get("turn") is None:
        response = client.get(route)
        response.raise_for_status()
        conversation = response.json()
        if conversation["turns"]:
            raise ValueError("expected a new empty evaluation conversation")
        state["commands"]["turn"] = {
            "client_command_id": f"eval-turn-{uuid4().hex}", "expected_version": conversation["version"],
            "text": state["case"]["input"], "action": "message",
            "artifact_id": None}
        state["before_turn_ids"] = [t["turn_id"] for t in conversation["turns"]]
        save()  # Persist the exact command BEFORE a potentially billable submission.
    command = state["commands"]["turn"]
    payload = {"command": "assistance_turn", "conversation_id": conversation_id, **command}
    saved = receipt(database, command["client_command_id"], payload)
    if saved is None:
        if state.get("run_id") or state.get("turn_request_started"):
            raise ValueError("teaching receipt is missing after a known/uncertain submission; refusing to POST again")
        state["turn_request_started"] = True
        state["stage"] = "submitting"
        save()
        response = client.post(route + "/turns", json=command)
        response.raise_for_status()
        saved = receipt(database, command["client_command_id"], payload)
    if saved is None or saved["run_id"] != conversation_id:
        raise ValueError("teaching submission has no matching persisted conversation receipt")
    response = client.get(route)
    response.raise_for_status()
    turns = [t for t in response.json()["turns"] if t["turn_id"] not in state["before_turn_ids"]
             and t["user_text"] == command["text"] and t["action"] == command["action"]]
    if len(turns) != 1 or state.get("run_id") not in {None, turns[0]["run_id"]}:
        raise ValueError("cannot unambiguously recover the original teaching run; no new command will be created")
    with readonly(database) as conn:
        run = _row(conn, "runs", turns[0]["run_id"])
    if (run.get("parent_run_id") is not None or run["turn_id"] != turns[0]["turn_id"]
            or run["conversation_id"] != conversation_id or run["input"]["text"] != command["text"]):
        raise ValueError("current turn points to a retry or different execution; refusing to grade a replacement run")
    state.update(run_id=turns[0]["run_id"], turn_id=turns[0]["turn_id"], stage="submitted")
    save()
    return state["run_id"]


def collect_evidence(database: Path, state: dict, http_run: dict, http_turn: dict) -> dict:
    with readonly(database) as conn:
        run = _row(conn, "runs", state["run_id"])
        conversation = _row(conn, "assistance_conversations", state["conversation_id"])
        turns = [t for t in conversation["turns"] if t["turn_id"] == state["turn_id"]]
        calls = [{**json.loads(row["data"]), "id": row["id"], "run_id": row["run_id"]}
                 for row in conn.execute("SELECT id,run_id,data FROM model_calls WHERE run_id=? ORDER BY rowid",
                                         (state["run_id"],))]
        artifacts = [json.loads(row["data"]) for row in conn.execute(
            "SELECT data FROM assistance_artifacts WHERE conversation_id=?", (state["conversation_id"],))]
    if len(turns) != 1:
        raise ValueError("persisted turn association is missing or ambiguous")
    turn = turns[0]
    artifacts = [a for a in artifacts if a["turn_id"] == state["turn_id"]]
    if (run["kind"] != "assistance" or run.get("parent_run_id") is not None or run["conversation_id"] != state["conversation_id"]
            or run["turn_id"] != state["turn_id"] or turn["run_id"] != run["run_id"]
            or run["input"]["text"] != state["case"]["input"] or run["input"]["history"]
            or turn["user_text"] != state["case"]["input"]):
        raise ValueError("saved business execution differs from the fixed single-turn Case")
    if any(turn.get(k) != http_turn.get(k) for k in ("run_id", "response", "artifacts", "skill_uses", "status")):
        raise ValueError("HTTP turn and committed SQLite evidence differ")
    if run["run_id"] != http_run["run_id"] or run["status"] != http_run["status"] or turn["artifacts"] != artifacts:
        raise ValueError("run/artifact evidence is inconsistent")
    return {"source": {"database": str(database), "storage_id": storage_identity(database), "collected_at": now()},
            "run": run, "turn": turn, "calls": calls, "artifacts": artifacts,
            "http_run": http_run, "http_turn": http_turn}


def skill_trace_matches(run: dict, turn: dict, calls: list[dict]) -> bool:
    """Optional uses must match successful load steps, requests and frozen snapshots."""
    try:
        snapshots = SkillRegistry(run["input"]["skill_snapshots"]).snapshot()
        requested = [tool["arguments"]["name"] for call in calls
                     for tool in call.get("response", {}).get("tool_calls", [])
                     if tool.get("name") == "get_skills"]
        loaded = [{key: step[key] for key in ("name", "version", "sha256")}
                  for step in run["steps"] if step.get("tool") == "get_skills" and step.get("status") == "ready"]
        uses = turn["skill_uses"]
        return (uses == loaded and len({use["name"] for use in uses}) == len(uses)
                and all(use["name"] in requested and use == {
                    key: snapshots[use["name"]][key] for key in ("name", "version", "sha256")}
                        for use in uses))
    except (KeyError, TypeError, ValueError):
        return False


def evaluate_rules(state: dict) -> list[dict]:
    evidence = state["evidence"]
    run, turn = evidence["run"], evidence["turn"]
    response = turn.get("response")
    rules = []

    def check(identity, verdict, reason, refs):
        rules.append({"id": identity, "verdict": verdict, "reason": reason, "evidence_refs": refs})

    delivered = run["status"] == "ready" and turn["status"] == "ready" and bool(response and response.get("text"))
    check("delivery", "pass" if delivered else "fail", "run与最终提交回复一致" if delivered else "未完成真实回复交付",
          ["evidence.run", "evidence.turn"])
    check("skill_trace", "pass" if skill_trace_matches(run, turn, evidence["calls"]) else "fail",
          "Skill可选；使用记录须与实际加载及冻结快照一致",
          ["evidence.turn.skill_uses", "evidence.run.steps", "evidence.calls", "evidence.run.input.skill_snapshots"])
    check("no_artifacts", "pass" if turn["artifacts"] == [] else "fail", "Case明确不创建教学产物",
          ["evidence.turn.artifacts"])
    no_questions = response and response["questions"] == [] and response["waiting_for"] == "none" and response["plan"] == []
    check("no_questions", "pass" if no_questions else "fail" if response else "undetermined",
          "Case要求一次解释，不提问、不等待或展开完整计划", ["final_response"])
    complete = state.get("trajectory_validation", {}).get("valid") and state.get("trajectory_validation", {}).get("complete")
    check("trajectory", "pass" if complete else "undetermined", "ATIF格式及已知调用／反馈完整性",
          ["trajectory.json", "trajectory_validation"])
    return rules


def finalize_evidence(state: dict, output: Path) -> dict:
    """Deterministic processing can resume without another HTTP/model request."""
    evidence = state["evidence"]
    run, calls = evidence["run"], evidence["calls"]
    state["final_response"] = deepcopy(evidence["turn"].get("response"))
    configuration = {"prompts": [c.get("system_prompt") for c in calls],
                     "tools": [c.get("tools") for c in calls], "skills": run["input"]["skill_snapshots"]}
    state["subject"] = {"model": run["model"], "configuration_sha256": digest(configuration),
                        "backend_code_version": None, "code_version_note": "not advertised by backend"}
    try:
        trajectory = export_trajectory(run, calls, execution_id=state["execution_id"],
                                       agent_version="configuration-sha256:" + digest(configuration))
        validate_trajectory(trajectory)
        write_json(output / "trajectory.json", trajectory)
        state["trajectory_validation"] = {"valid": True,
            "complete": trajectory["extra"]["mini_hyperknow"]["complete"],
            "schema_version": "ATIF-v1.7", "exporter_version": 1}
    except (ValueError, KeyError) as exc:
        state["trajectory_validation"] = {"valid": False, "complete": False, "error": str(exc)}
    counter = TokenCounter()
    for call in calls:
        counter.record(call.get("usage"))
    state["subject_usage"] = counter.snapshot()
    state["rules"] = evaluate_rules(state)
    state.update(stage="collected", error=None)
    write_json(output / "result.json", state)
    return state


def run_business(case: dict, *, base_url: str, data_dir: Path, output: Path,
                 execute: bool, resume: bool = False, wait_seconds: float = 420) -> dict:
    if not execute:
        raise ValueError("--execute is required for a real, potentially billable teaching run")
    if not 0 < wait_seconds <= 900:
        raise ValueError("wait_seconds must be within (0, 900]")
    case = validate_case(case)
    base_url = local_origin(base_url)
    database = isolated_database(data_dir)
    output = private_output(output)
    result_path = output / "result.json"
    with exclusive(output / ".writer.lock"):
        if result_path.exists():
            if not resume:
                raise ValueError("result already exists; use --resume or a new explicit output directory")
            state = read_json(result_path)
            if (state["case_hash"] != case_hash(case) or state["target"] != {
                    "base_url": base_url, "database": str(database), "storage_id": storage_identity(database)}):
                raise ValueError("resume Case or backend identity differs from the original execution")
            if state.get("evidence"):
                return finalize_evidence(state, output)
        else:
            if resume:
                raise ValueError("no persisted execution exists to resume")
            state = {"schema_version": 1, "execution_id": f"eval-{uuid4().hex}", "created_at": now(),
                     "case": case, "case_hash": case_hash(case), "stage": "prepared", "grades": [], "rules": [],
                     "target": {"base_url": base_url, "database": str(database), "storage_id": storage_identity(database)},
                     "commands": {"create": {"client_command_id": f"eval-create-{uuid4().hex}"}, "turn": None},
                     "conversation_id": None, "run_id": None, "evidence": {}, "final_response": None}

        def save():
            write_json(result_path, state)

        save()
        try:
            with httpx.Client(base_url=base_url, trust_env=False, timeout=15) as client:
                command = state["commands"].get("turn")
                submitted = command and state.get("conversation_id") and receipt(database,
                    command["client_command_id"], {"command": "assistance_turn",
                    "conversation_id": state["conversation_id"], **command})
                state["health"] = check_backend(client, database, require_model=not submitted)
                save()
                recover_conversation(client, database, state, save)
                run_id = recover_turn(client, database, state, save)
                deadline = time.monotonic() + wait_seconds
                while True:
                    response = client.get(f"/api/runs/{run_id}")
                    response.raise_for_status()
                    run = response.json()
                    if run["status"] not in ACTIVE:
                        break
                    if time.monotonic() >= deadline:
                        state.update(stage="waiting", error={"type": "wait_timeout", "message": "backend may still be running; resume this execution"})
                        save()
                        return state
                    time.sleep(0.3)
                response = client.get(f"/api/assistance/conversations/{state['conversation_id']}")
                response.raise_for_status()
                turn = next(t for t in response.json()["turns"] if t["turn_id"] == state["turn_id"])
                state["evidence"] = collect_evidence(database, state, run, turn)
            state["stage"] = "evidence_collected"
            save()
            return finalize_evidence(state, output)
        except Exception as exc:
            state.update(stage="blocked_or_unknown", error={"type": type(exc).__name__, "message": str(exc)})
            save()
            raise


def grade_result(output: Path, *, settings: GraderSettings, execute: bool, regrade: bool = False) -> dict:
    if not execute:
        raise ValueError("--execute is required for a billable grading request")
    output = private_output(output)
    path = output / "result.json"
    with exclusive(output / ".writer.lock"):
        state = read_json(path)
        validate_case(state["case"])
        if state["case_hash"] != case_hash(state["case"]):
            raise ValueError("stored Case was modified")
        if (state.get("final_response") is not None and state["final_response"] !=
                state.get("evidence", {}).get("turn", {}).get("response")):
            raise ValueError("grading output differs from the saved business evidence")
        grades = state["grades"]
        if grades and not regrade:
            last = grades[-1]
            last["budget_check"] = grading_budget(last)
            if last["status"] in {"prepared", "in_flight"}:
                raw = last.get("raw_response")
                if raw and raw.get("stop_reason") == "stop" and not raw.get("tool_calls") and not raw.get("error_message"):
                    try:
                        last["results"] = parse_grading_response(raw["content"], state["case"], state["final_response"])
                        last.update(status="completed", error=None)
                    except ValueError as exc:
                        last.update(status="error", error={"type": "invalid_response", "message": str(exc)},
                                    results=[{"rubric_id": r["id"], "verdict": "undetermined",
                                              "reason": "grader_error: invalid_response", "evidence_refs": ["final_response"]}
                                             for r in state["case"]["rubric"]])
                else:
                    last.update(status="unknown", error={"type": "response_unknown", "message": "no automatic retry; explicit regrade required"},
                                results=[{"rubric_id": r["id"], "verdict": "undetermined",
                                          "reason": "grader_response_unknown", "evidence_refs": ["final_response"]}
                                         for r in state["case"]["rubric"]])
            write_json(path, state)
            return state
        if not state.get("final_response") or not state.get("trajectory_validation", {}).get("valid"):
            return state
        attempt_id = f"grade-{uuid4().hex}"
        grades.append({"attempt_id": attempt_id, "status": "prepared", "calibration_status": "unreviewed"})
        write_json(path, state)

        def checkpoint(record):
            grades[-1] = {**deepcopy(record), "attempt_id": attempt_id}
            write_json(path, state)

        grade_once(state["case"], state["final_response"], settings=settings, checkpoint=checkpoint)
        return state


def collect_result(output: Path, library: Path) -> Path:
    path = private_output(output) / "result.json"
    return collect_sample(read_json(path), private_output(library), path)


def summary(state: dict) -> dict:
    return {"execution_id": state["execution_id"], "run_id": state.get("run_id"), "stage": state["stage"],
            "label": classify_result(state), "rules": state.get("rules", []),
            "grades": [{**{k: grade.get(k) for k in ("attempt_id", "status", "model", "results", "usage", "calibration_status")},
                        "budget_check": grading_budget(grade)}
                       for grade in state.get("grades", [])], "subject_usage": state.get("subject_usage"),
            "error": state.get("error")}
