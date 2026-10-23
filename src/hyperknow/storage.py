"""Real SQLite transactions; no in-memory persistence substitute."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable

from .domain import AppError, CourseDraft, materialize_course, uid
from .lesson_storage import LessonStorage
from .quiz_storage import QuizStorage
from .research_storage import ResearchStorage


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Database(ResearchStorage, QuizStorage, LessonStorage):
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _migrate(self):
        # sqlite backup copies a consistent database, including committed WAL data.
        # The application must still be stopped before upgrading a user database.
        with closing(sqlite3.connect(self.path)) as source:
            version = source.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise AppError("database_version_unsupported", "数据库来自更新版本，拒绝降级打开", 503)
            if version in {1, 2}:
                backup = self.path.with_name(f"{self.path.name}.v{version}-{uid('backup')}.bak")
                with closing(sqlite3.connect(backup)) as target:
                    source.backup(target)
        with self.transaction() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise AppError("database_version_unsupported", "数据库来自更新版本，拒绝降级打开", 503)
            if version == 0:
                for sql in (
                    "CREATE TABLE runs(id TEXT PRIMARY KEY, data TEXT NOT NULL)",
                    "CREATE TABLE courses(id TEXT PRIMARY KEY, data TEXT NOT NULL)",
                    "CREATE TABLE command_receipts(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL)",
                    "CREATE TABLE model_calls(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL)",
                ):
                    conn.execute(sql)
                conn.execute("PRAGMA user_version = 1")
                version = 1
            if version == 1:
                for sql in (
                    "ALTER TABLE command_receipts ADD COLUMN resource_type TEXT NOT NULL DEFAULT 'run'",
                    "CREATE TABLE lesson_scripts(id TEXT PRIMARY KEY, session_id TEXT NOT NULL UNIQUE, data TEXT NOT NULL)",
                    "CREATE TABLE lesson_states(id TEXT PRIMARY KEY, data TEXT NOT NULL)",
                    "CREATE TABLE lesson_interactions(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, data TEXT NOT NULL)",
                    "CREATE INDEX interactions_session ON lesson_interactions(session_id)",
                    "CREATE TABLE activity_progress(id TEXT PRIMARY KEY, data TEXT NOT NULL)",
                ):
                    conn.execute(sql)
                for row in conn.execute("SELECT id,data FROM runs").fetchall():
                    run = json.loads(row["data"])
                    run.setdefault("kind", "course")
                    for key in ("session_id", "script_id", "interaction_id"):
                        run.setdefault(key, None)
                    conn.execute("UPDATE runs SET data=? WHERE id=?", (encode(run), row["id"]))
                conn.execute("PRAGMA user_version = 2")
                version = 2
            if version == 2:
                for sql in (
                    "CREATE TABLE quizzes(id TEXT PRIMARY KEY,target_type TEXT NOT NULL,target_id TEXT NOT NULL,data TEXT NOT NULL,UNIQUE(target_type,target_id))",
                    "CREATE TABLE quiz_states(id TEXT PRIMARY KEY,data TEXT NOT NULL)",
                    "CREATE TABLE quiz_attempts(id TEXT PRIMARY KEY,quiz_id TEXT NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL)",
                    "CREATE UNIQUE INDEX one_open_attempt ON quiz_attempts(quiz_id) WHERE status='in_progress'",
                ):
                    conn.execute(sql)
                conn.execute("PRAGMA user_version = 3")

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
            return self._course(conn, course_id)

    def list_records(self, table: str) -> list[dict]:
        if table not in {"runs", "courses"}:
            raise ValueError("unknown collection")
        with self.transaction() as conn:
            rows = [json.loads(r["data"]) for r in conn.execute(f"SELECT data FROM {table}")]
            if table == "courses":
                from .lesson_domain import derive_course
                completed = self._completed(conn)
                rows = [derive_course(course, completed) for course in rows]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    def _save_run(self, conn, run: dict):
        conn.execute("INSERT INTO runs(id, data) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                     (run["run_id"], encode(run)))
        if run.get("kind") == "quiz":
            self._quiz_run_changed(conn, run)
        elif run.get("kind") != "research":
            self._run_changed(conn, run)

    def command(self, command_id: str, payload: dict, action: Callable, *, resource_type: str = "run") -> dict:
        fingerprint = hashlib.sha256(encode(payload).encode()).hexdigest()
        with self.transaction() as conn:
            old = conn.execute("SELECT * FROM command_receipts WHERE id = ?", (command_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise AppError("command_conflict", "相同命令标识不能提交不同内容", 409)
                readers = {"session": lambda: self._lesson(conn, old["run_id"]),
                           "quiz_target": lambda: self._quiz_target(conn, *old["run_id"].split(":", 1)),
                           "attempt": lambda: self._attempt_snapshot(conn, old["run_id"]),
                           "run": lambda: self._get(conn, "runs", old["run_id"])}
                return readers[old["resource_type"]]()
            result = action(conn)
            if resource_type == "session":
                result_id = result["session"]["session_id"]
            elif resource_type == "quiz_target":
                result_id = self._target_key(result["target_type"], result["target_id"])
            elif resource_type == "attempt":
                result_id = result["attempt"]["attempt_id"]
            else:
                result_id = result["run_id"]
            conn.execute("INSERT INTO command_receipts VALUES (?, ?, ?, ?)",
                         (command_id, fingerprint, result_id, resource_type))
            return result

    def create_run(self, command_id: str, goal: str, model: str, *, configured: bool = True) -> dict:
        def create(conn):
            self._model_configured(configured)
            run = self._new_run(goal, model)
            self._save_run(conn, run)
            return run
        return self.command(command_id, {"action": "create", "goal": goal}, create)

    @staticmethod
    def _new_run(goal: str, model: str) -> dict:
        timestamp = now()
        return {"run_id": uid("run"), "goal": goal, "status": "queued", "version": 1,
                "kind": "course", "session_id": None, "script_id": None, "interaction_id": None,
                "quiz_id": None, "target_type": None, "target_id": None,
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

    def retry_run(self, command_id: str, run_id: str, expected_version: int, *, configured: bool = True,
                  search_configured: bool = False) -> dict:
        def retry(conn):
            parent = self._get(conn, "runs", run_id)
            if parent["version"] != expected_version:
                raise AppError("version_conflict", "记录已更新，请刷新后再试", 409, True,
                               latest_version=parent["version"])
            if parent["status"] not in {"failed", "cancelled", "interrupted"}:
                raise AppError("state_conflict", "只有失败、取消或中断的任务可以重试", 409)
            if parent.get("kind", "course") in {"course", "research"} and any(
                json.loads(row["data"]).get("parent_run_id") == run_id
                for row in conn.execute("SELECT data FROM runs")
            ):
                raise AppError("state_conflict", "该任务已有重试，请继续已有的重试任务", 409)
            self._model_configured(configured)
            run = self._new_run(parent["goal"], parent["model"])
            for key in ("questions", "answers", "skipped", "answers_submitted"):
                run[key] = parent[key]
            run["parent_run_id"] = run_id
            if parent.get("kind") == "research":
                self._search_configured(search_configured)
                run.update(kind="research", input=parent["input"],
                           research={"steps": [], "sources": [], "report": None})
            elif parent.get("kind") == "quiz":
                self._retry_quiz(conn, parent, run)
            elif parent.get("kind", "course") != "course":
                self._retry_lesson(conn, parent, run)
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
            if run["status"] != "generating" or run.get("kind", "course") != "course":
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
