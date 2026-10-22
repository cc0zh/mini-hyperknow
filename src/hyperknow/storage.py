"""Real SQLite transactions; no in-memory persistence substitute."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable

from .domain import AppError, CourseDraft, materialize_course, uid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS command_receipts(
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS model_calls(
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL);
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _get(conn, table: str, key: str) -> dict:
        row = conn.execute(f"SELECT data FROM {table} WHERE id = ?", (key,)).fetchone()
        if row is None:
            raise AppError("not_found", "找不到这条记录", 404)
        return json.loads(row["data"])

    def get_run(self, run_id: str) -> dict:
        with self.transaction() as conn:
            return self._get(conn, "runs", run_id)

    def get_course(self, course_id: str) -> dict:
        with self.transaction() as conn:
            return self._get(conn, "courses", course_id)

    def list_records(self, table: str) -> list[dict]:
        if table not in {"runs", "courses"}:
            raise ValueError("unknown collection")
        with self.transaction() as conn:
            rows = [json.loads(r["data"]) for r in conn.execute(f"SELECT data FROM {table}")]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    @staticmethod
    def _save_run(conn, run: dict):
        conn.execute("INSERT OR REPLACE INTO runs(id, data) VALUES (?, ?)", (run["run_id"], encode(run)))

    def command(self, command_id: str, payload: dict, action: Callable) -> dict:
        fingerprint = hashlib.sha256(encode(payload).encode()).hexdigest()
        with self.transaction() as conn:
            old = conn.execute("SELECT * FROM command_receipts WHERE id = ?", (command_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise AppError("command_conflict", "相同命令标识不能提交不同内容", 409)
                return self._get(conn, "runs", old["run_id"])
            run = action(conn)
            conn.execute("INSERT INTO command_receipts VALUES (?, ?, ?)", (command_id, fingerprint, run["run_id"]))
            return run

    def create_run(self, command_id: str, goal: str, model: str) -> dict:
        def create(conn):
            run = self._new_run(goal, model)
            self._save_run(conn, run)
            return run
        return self.command(command_id, {"action": "create", "goal": goal}, create)

    @staticmethod
    def _new_run(goal: str, model: str) -> dict:
        timestamp = now()
        return {"run_id": uid("run"), "goal": goal, "status": "queued", "version": 1,
                "questions": [], "answers": [], "skipped": False, "answers_submitted": False,
                "course_id": None, "error": None, "model": model, "usage": None,
                "created_at": timestamp, "updated_at": timestamp, "parent_run_id": None}

    def mutate_command(self, command_id: str, run_id: str, expected_version: int,
                       payload: dict, mutate: Callable) -> dict:
        def update(conn):
            run = self._get(conn, "runs", run_id)
            if run["version"] != expected_version:
                raise AppError("version_conflict", "记录已更新，请刷新后再试", 409, True,
                               latest_version=run["version"])
            result = mutate(run)
            result["version"] += 1
            result["updated_at"] = now()
            self._save_run(conn, result)
            return result
        return self.command(command_id, {"run_id": run_id, "version": expected_version, **payload}, update)

    def retry_run(self, command_id: str, run_id: str, expected_version: int) -> dict:
        def retry(conn):
            parent = self._get(conn, "runs", run_id)
            if parent["version"] != expected_version:
                raise AppError("version_conflict", "记录已更新，请刷新后再试", 409, True,
                               latest_version=parent["version"])
            if parent["status"] not in {"failed", "cancelled", "interrupted"}:
                raise AppError("state_conflict", "只有失败、取消或中断的任务可以重试", 409)
            run = self._new_run(parent["goal"], parent["model"])
            for key in ("questions", "answers", "skipped", "answers_submitted"):
                run[key] = parent[key]
            run["parent_run_id"] = run_id
            self._save_run(conn, run)
            return run
        return self.command(command_id, {"action": "retry", "run_id": run_id, "version": expected_version}, retry)

    def transition(self, run_id: str, allowed: set[str], **patch) -> dict | None:
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if run["status"] not in allowed:
                return None
            run.update(patch)
            run["version"] += 1
            run["updated_at"] = now()
            self._save_run(conn, run)
            return run

    def finish_course(self, run_id: str, draft: CourseDraft) -> dict | None:
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if run["status"] != "generating":
                return None
            course = materialize_course(draft, run, now())
            conn.execute("INSERT INTO courses VALUES (?, ?)", (course["course_id"], encode(course)))
            run.update(status="ready", course_id=course["course_id"], error=None,
                       version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run

    def interrupt_inflight(self):
        with self.transaction() as conn:
            for row in conn.execute("SELECT data FROM runs").fetchall():
                run = json.loads(row["data"])
                if run["status"] in {"queued", "clarifying", "generating"}:
                    run.update(status="interrupted", version=run["version"] + 1, updated_at=now(),
                               error={"code": "interrupted", "message": "服务重启中断了生成，请手动重试", "retryable": True})
                    self._save_run(conn, run)

    def record_call(self, run_id: str, record: dict):
        with self.transaction() as conn:
            conn.execute("INSERT INTO model_calls VALUES (?, ?, ?)", (uid("call"), run_id, encode(record)))

    def calls(self, run_id: str) -> list[dict]:
        with self.transaction() as conn:
            return [json.loads(r["data"]) for r in conn.execute("SELECT data FROM model_calls WHERE run_id = ?", (run_id,))]
