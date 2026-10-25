"""Real SQLite and HTTP deletion checks; explicit domain inputs, no model calls."""

from concurrent.futures import ThreadPoolExecutor
import asyncio
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

import httpx

from hyperknow.blueprint_domain import BlueprintDraft
from hyperknow.config import Settings
from hyperknow.domain import AppError, CourseDraft
from hyperknow.lesson_domain import BoardScriptDraft, LessonAnswer
from hyperknow.research_domain import ResearchReport
from hyperknow.runtime import CourseService, EventHub
from hyperknow.storage import Database
from test_blueprint import blueprint_input
from test_course import course_data
from test_lesson import script_input
from test_quiz import persisted_quiz
from test_research import page_input, read_step, report_input, search_step


def create_course(db, prefix):
    parent = db.create_run(prefix + "-create", "理解协程", "stored-model")
    parent = db.transition(parent["run_id"], {"queued"}, status="cancelled")
    run = db.retry_run(prefix + "-retry", parent["run_id"], parent["version"], search_configured=True)
    db.transition(run["run_id"], {"queued"}, status="generating")
    run = db.finish_course(run["run_id"], CourseDraft.model_validate(course_data()))
    return db.get_course(run["course_id"])


def populate_course(db, prefix):
    course = create_course(db, prefix)
    session = course["units"][0]["lectures"][0]["sessions"][0]["session_id"]
    exam = course["units"][0]["exams"][0]["exam_id"]
    lesson = db.prepare_lesson(session, prefix + "-lesson", "stored-model", True)
    run = lesson["generation_run"]
    db.transition(run["run_id"], {"queued"}, status="generating")
    db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(script_input()))
    lesson = db.get_lesson(session)
    lesson = db.ask_question(session, {"client_command_id": prefix + "-question",
        "expected_version": lesson["progress"]["version"], "script_id": lesson["script"]["script_id"],
        "cursor": -1, "question": "如何恢复？", "was_playing": False}, "stored-model", True)
    question = lesson["interactions"][0]["run_id"]
    db.transition(question, {"queued"}, status="generating")
    db.finish_lesson(question, LessonAnswer(answer="条件满足后由调度器恢复。"))
    for kind, target in (("practice", session), ("exam", exam)):
        quiz = persisted_quiz(db, kind, target, prefix + "-quiz-" + kind)["quiz"]
        snapshot = db.create_attempt(quiz["quiz_id"], prefix + "-attempt-" + kind)
        for index, question in enumerate(quiz["questions"]):
            attempt = snapshot["attempt"]
            snapshot = db.answer_quiz(attempt["attempt_id"], {
                "client_command_id": f"{prefix}-{kind}-answer-{index}",
                "expected_version": attempt["version"], "question_id": question["question_id"],
                "option_ids": [], "skipped": True, "elapsed_ms": 0})
            if index < len(quiz["questions"]) - 1:
                snapshot = db.next_question(attempt["attempt_id"], {
                    "client_command_id": f"{prefix}-{kind}-next-{index}",
                    "expected_version": snapshot["attempt"]["version"]})
        db.submit_quiz(snapshot["attempt"]["attempt_id"], {
            "client_command_id": prefix + "-submit-" + kind,
            "expected_version": snapshot["attempt"]["version"]})
        db.create_attempt(quiz["quiz_id"], prefix + "-again-" + kind)
    runs = db.list_records("runs")
    related = {run["run_id"] for run in runs if run.get("course_id") == course["course_id"]}
    related.update(run["parent_run_id"] for run in runs if run["run_id"] in related and run.get("parent_run_id"))
    for run in runs:
        if run["run_id"] in related:
            db.record_call(run["run_id"], {"input": "explicit storage input", "usage": {"total_tokens": 1}})
    return db.get_course(course["course_id"])


def blueprint_course(db, prefix):
    run = db.create_run(prefix + "-create", "理解异步任务", "stored-model")
    db.transition(run["run_id"], {"queued"}, status="generating", stage="research", answers_submitted=True)
    db.research_step(run["run_id"], search_step())
    source = db.research_step(run["run_id"], read_step(), page_input())
    db.finish_research(run["run_id"], ResearchReport.model_validate(report_input(source["source_id"])))
    return db.finish_blueprint(run["run_id"], BlueprintDraft.model_validate(blueprint_input()))


class CourseDeletionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hyperknow-delete-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "hyperknow.sqlite3"
        self.db = Database(self.path)

    def delete(self, course, command="delete-course-command"):
        return self.db.delete_course(course["course_id"], {
            "client_command_id": command, "expected_version": course["version"]})

    def rows(self):
        with self.db.transaction() as conn:
            tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
                    for table in tables if table != "command_receipts"}

    def assert_error(self, code, action):
        with self.assertRaises(AppError) as raised:
            action()
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_cleanup_is_scoped_and_persists_after_reopening(self):
        survivor = populate_course(self.db, "survivor")
        research = self.db.create_research("independent-research", "独立主题", "", "stored-model",
                                           configured=True, search_configured=True)
        baseline = self.rows()
        deleted = populate_course(self.db, "removed")
        self.assertEqual(self.delete(deleted), {"course_id": deleted["course_id"], "deleted": True})
        self.db = Database(self.path)
        self.assertEqual(self.rows(), baseline)
        self.assertEqual(self.db.get_course(survivor["course_id"]), survivor)
        self.assertEqual(self.db.get_run(research["run_id"]), research)
        self.assert_error("not_found", lambda: self.db.get_course(deleted["course_id"]))
        self.assertEqual(self.delete(deleted), {"course_id": deleted["course_id"], "deleted": True})

    def test_stale_unknown_and_conflicting_commands_do_not_report_success(self):
        course = create_course(self.db, "versions")
        before = self.rows()
        error = self.assert_error("version_conflict", lambda: self.delete({**course, "version": 0}))
        self.assertEqual((error.status, error.latest_version), (409, course["version"]))
        self.assertEqual(self.rows(), before)
        self.assert_error("not_found", lambda: self.delete({**course, "course_id": "missing"}))
        self.delete(course)
        self.assert_error("command_conflict", lambda: self.delete({**course, "version": 99}))
        self.assert_error("command_conflict", lambda: self.delete({**course, "course_id": "missing"}))
        self.assert_error("not_found", lambda: self.delete(course, "different-delete-command"))

    def test_deleted_resources_and_old_commands_cannot_recreate_course(self):
        course = populate_course(self.db, "replays")
        runs = self.db.list_records("runs")
        lesson = next(r for r in runs if r["kind"] == "lesson")
        parent = next(r for r in runs if r.get("parent_run_id") is None and r["kind"] == "course")
        self.delete(course)
        self.assert_error("not_found", lambda: self.db.create_run("replays-create", "理解协程", "stored-model"))
        self.assert_error("command_conflict", lambda: self.db.create_run("replays-create", "不同目标", "stored-model"))
        self.assert_error("not_found", lambda: self.db.retry_run(
            "replays-retry", parent["run_id"], parent["version"], search_configured=True))
        self.assert_error("not_found", lambda: self.db.prepare_lesson(
            lesson["session_id"], "replays-lesson", "stored-model", True))
        self.assert_error("not_found", lambda: self.db.prepare_quiz(
            "practice", lesson["session_id"], "replays-quiz-practice", "stored-model", True))
        quiz_run = next(r for r in runs if r["kind"] == "quiz" and r["target_type"] == "practice")
        self.assert_error("not_found", lambda: self.db.create_attempt(quiz_run["quiz_id"], "replays-attempt-practice"))
        self.assertEqual(self.db.list_records("courses"), [])
        self.assertEqual(self.db.list_records("runs"), [])

    def test_all_active_related_statuses_require_stop_first(self):
        course = create_course(self.db, "active")
        session = course["units"][0]["lectures"][0]["sessions"][0]["session_id"]
        run = self.db.prepare_lesson(session, "active-lesson", "stored-model", True)["generation_run"]
        for status in ("queued", "clarifying", "generating", "awaiting_answers", "awaiting_blueprint"):
            with self.subTest(status=status):
                run = self.db.transition(run["run_id"], {run["status"]}, status=status)
                before = self.rows()
                error = self.assert_error("course_active", lambda: self.delete(course))
                self.assertEqual(error.status, 409)
                self.assertIn("停止", error.message)
                self.assertEqual(self.rows(), before)
        self.db.transition(run["run_id"], {run["status"]}, status="cancelled")
        self.assertTrue(self.delete(course)["deleted"])

    def test_blueprint_cancel_delete_discards_late_results_and_evidence(self):
        run = blueprint_course(self.db, "blueprint")
        course = self.db.get_course(run["course_id"])
        self.assert_error("course_active", lambda: self.delete(course))
        run = self.db.blueprint_command(run["run_id"], {"client_command_id": "blueprint-revision",
            "expected_version": run["version"], "approve": False, "feedback": "调整任务取消内容"})
        run = self.db.transition(run["run_id"], {"generating"}, status="cancelled")
        course = self.db.get_course(course["course_id"])
        self.delete(course)
        self.db.record_call(run["run_id"], {"output": "late cancelled response"})
        self.assert_error("not_found", lambda: self.db.finish_blueprint(
            run["run_id"], BlueprintDraft.model_validate(blueprint_input())))
        self.assert_error("not_found", lambda: self.db.research_step(run["run_id"], search_step()))
        self.assert_error("not_found", lambda: self.db.finish_course(
            run["run_id"], CourseDraft.model_validate(course_data())))
        self.assertEqual(self.db.calls(run["run_id"]), [])
        self.assertEqual(self.db.list_records("courses"), [])
        self.assertEqual(self.db.list_records("runs"), [])

    def test_failed_storage_transaction_rolls_back_cleanup_and_receipt(self):
        course = populate_course(self.db, "rollback")
        before = self.rows()
        with self.db.transaction() as conn:
            conn.execute("CREATE TRIGGER refuse_delete BEFORE DELETE ON courses "
                         "BEGIN SELECT RAISE(ABORT, 'storage failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.delete(course)
        self.assertEqual(self.rows(), before)
        with self.db.transaction() as conn:
            self.assertIsNone(conn.execute("SELECT id FROM command_receipts WHERE id=?",
                                           ("delete-course-command",)).fetchone())
            conn.execute("DROP TRIGGER refuse_delete")
        self.assertTrue(self.delete(course)["deleted"])

    def test_concurrent_same_command_deletes_once(self):
        course = create_course(self.db, "concurrent")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.delete(course), range(2)))
        self.assertEqual(results, [{"course_id": course["course_id"], "deleted": True}] * 2)
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM command_receipts "
                "WHERE resource_type='course_deletion'").fetchone()[0], 1)

    def test_cancelled_lesson_late_result_and_stale_worker_queue_cannot_resurrect(self):
        course = create_course(self.db, "stale-worker")
        session = course["units"][0]["lectures"][0]["sessions"][0]["session_id"]
        run = self.db.prepare_lesson(session, "stale-worker-lesson", "stored-model", True)["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.transition(run["run_id"], {"generating"}, status="cancelled")
        self.delete(course)
        self.assert_error("not_found", lambda: self.db.finish_lesson(
            run["run_id"], BoardScriptDraft.model_validate(script_input())))
        self.db.record_call(run["run_id"], {"output": "late lesson response"})

        async def consume_stale_entry():
            service = CourseService(Settings(data_dir=self.path.parent), self.db, EventHub())
            service.enqueue(run)
            service.start()
            try:
                await asyncio.wait_for(service.queue.join(), timeout=3)
                self.assertFalse(service.worker.done())
                self.assertEqual(service.enqueued, set())
            finally:
                await service.close()

        asyncio.run(consume_stale_entry())
        self.assertEqual(self.db.list_records("courses"), [])
        self.assertEqual(self.db.list_records("runs"), [])
        self.assertEqual(self.db.calls(run["run_id"]), [])


class CourseDeletionHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="hyperknow-delete-http-")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "HK_DATA_DIR": cls.directory.name, "OPENAI_API_KEY": "", "TAVILY_API_KEY": ""}
        cls.process = subprocess.Popen([sys.executable, "-m", "uvicorn", "hyperknow.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.client = httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    raise RuntimeError("real HTTP server exited before startup")
                try:
                    if cls.client.get("/api/health").status_code == 200:
                        cls.db = Database(Path(cls.directory.name) / "hyperknow.sqlite3")
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            raise RuntimeError("real HTTP server did not start")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.directory.cleanup()

    def test_real_http_deletion_replays_and_queries(self):
        course = populate_course(self.db, "http-delete")
        path = f"/api/courses/{course['course_id']}/delete"
        body = {"client_command_id": "http-delete-command", "expected_version": course["version"]}
        stale = self.client.post(path, json={**body, "expected_version": course["version"] - 1})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["latest_version"], course["version"])
        for _ in range(2):
            response = self.client.post(path, json=body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"course_id": course["course_id"], "deleted": True})
        self.assertEqual(self.client.get(f"/api/courses/{course['course_id']}").status_code, 404)
        self.assertNotIn(course["course_id"], [c["course_id"] for c in self.client.get("/api/courses").json()["courses"]])
        self.assertEqual(self.client.post(path, json={**body, "expected_version": 99}).status_code, 409)
        self.assertEqual(self.client.post(path, json={**body, "client_command_id": "another-delete-command"}).status_code, 404)
        replay = self.client.post("/api/course-runs", json={"client_command_id": "http-delete-create", "goal": "理解协程"})
        self.assertEqual(replay.status_code, 404)
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_http_active_missing_and_invalid_are_errors(self):
        run = blueprint_course(self.db, "http-active")
        course = self.db.get_course(run["course_id"])
        body = {"client_command_id": "http-active-delete", "expected_version": course["version"]}
        path = f"/api/courses/{course['course_id']}/delete"
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "course_active")
        self.assertEqual(self.client.post(path, json={"client_command_id": "missing-version"}).status_code, 422)
        self.assertEqual(self.client.post("/api/courses/missing/delete", json=body).status_code, 404)
        cancel = self.client.post(f"/api/runs/{run['run_id']}/cancel",
            json={"client_command_id": "http-active-cancel", "expected_version": run["version"]})
        self.assertEqual(cancel.status_code, 200)
        body["expected_version"] = self.client.get(f"/api/courses/{course['course_id']}").json()["version"]
        self.assertEqual(self.client.post(path, json=body).status_code, 200)
