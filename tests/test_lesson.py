"""Direct domain inputs and real disk SQLite; NOT model-generation evidence."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from hyperknow.config import Settings
from hyperknow.domain import AppError, CourseDraft
from hyperknow.generation import Generator
from hyperknow.lesson_domain import (
    BoardOperation, BoardScriptDraft, LessonAnswer, LessonSnapshot, derive_course, lesson_context,
    question_context, validate_lesson_coverage,
)
from hyperknow.main import AskQuestion
from hyperknow.runtime import CourseService, EventHub
from hyperknow.storage import Database, encode
from test_course import course_data


def script_input():
    # Deliberate function input, never a provider response or acceptance fixture.
    return {"schema_version": 2, "title": "暂停与恢复", "objectives": ["解释await让出控制权与恢复的条件"],
        "roadmap": [{"keypoint_id": "await", "source_keypoint_index": 0, "title": "协作式切换", "question": "等待时谁持有控制权？"}], "steps": [
        {"title": "调用", "narration": "普通调用在返回前保持控制权。", "page": 1, "column": 1,
         "stage": "opening", "operations": [{"object_id": "call", "kind": "text", "content": "普通调用"}]},
        {"title": "暂停", "narration": "await允许调度器安排其他任务。", "page": 1, "column": 2,
         "stage": "explain", "keypoint_id": "await",
         "operations": [{"object_id": "pause", "kind": "code", "content": "await work()", "language": "python"}]},
        {"title": "恢复", "narration": "条件满足后继续执行。", "page": 2, "column": 1,
         "stage": "example", "keypoint_id": "await",
         "operations": [{"object_id": "resume", "kind": "arrow", "content": "暂停 → 恢复"}]},
        {"title": "检查", "narration": "请预测等待网络返回时其他任务能否前进，并用课堂提问说明理由。", "page": 2, "column": 2,
         "stage": "check", "keypoint_id": "await", "check": {"question": "await等待期间其他任务能否前进？", "expected_answer": "能，控制权交回调度器。"},
         "operations": [{"object_id": "question", "kind": "text", "content": "等待时其他任务会怎样？"}]},
        {"title": "总结", "narration": "await是协作式让出控制权，不是任务结束。", "page": 3, "column": 1,
         "stage": "summary", "focus_ids": ["pause", "resume"],
         "operations": [{"object_id": "summary", "kind": "box", "content": "让出 → 等待 → 恢复"}]},
    ]}


def persist_domain_input(db):
    run = db.create_run("domain-course-input", "理解协程", "stored-model")
    db.transition(run["run_id"], {"queued"}, status="generating")
    ready = db.finish_course(run["run_id"], CourseDraft.model_validate(course_data()))
    course = db.get_course(ready["course_id"])
    session_id = course["units"][0]["lectures"][0]["sessions"][0]["session_id"]
    return course, session_id


class LessonSchemaTests(unittest.TestCase):
    def test_lesson_context_and_steps_are_limited_to_selected_source_claims(self):
        course = course_data()
        course.update(course_id="course-evidence", goal="Understand asyncio",
            clarification={"questions": [], "answers": [], "skipped": False},
            language="zh-CN", research_claims=[{
            "claim_id": "claim_await", "question_ids": ["q-await"],
            "title": "await pauses", "summary": "await pauses the coroutine."}],
            research_evidence=[{"evidence_id": "evidence-1", "claim_id": "claim_await",
                "question_ids": ["q-await"], "source_id": "source-1", "relation": "supports",
                "quote": "await suspends a coroutine", "start_char": 0, "end_char": 26,
                "url": "https://docs.python.org/asyncio", "title": "Asyncio", "fetched_at": "now",
                "content_sha256": "a" * 64, "provider": "exa", "content_mode": "highlights"}])
        unit = course["units"][0]
        unit["research_claim_ids"] = ["claim_await"]
        lecture = unit["lectures"][0]
        session = lecture["sessions"][0]
        session["session_id"] = "session-evidence"
        session["research_claim_ids"] = ["claim_await"]
        context = lesson_context(course, unit, lecture, session)
        self.assertEqual(context["research_claims"][0]["evidence"][0]["quote"],
                         "await suspends a coroutine")
        data = script_input()
        data["steps"][1]["research_claim_ids"] = ["claim_await"]
        draft = BoardScriptDraft.model_validate(data)
        self.assertIs(validate_lesson_coverage(draft, context), None)
        data["steps"][1]["research_claim_ids"] = ["not-selected"]
        with self.assertRaises(ValueError):
            validate_lesson_coverage(BoardScriptDraft.model_validate(data), context)
        data["steps"][1]["research_claim_ids"] = []
        with self.assertRaises(ValueError):
            validate_lesson_coverage(BoardScriptDraft.model_validate(data), context)

    def test_all_supported_operations_are_preserved(self):
        for kind in ("text", "code", "formula", "box", "arrow", "highlight", "mermaid"):
            op = BoardOperation(object_id="object", kind=kind, content="具体内容")
            self.assertEqual(op.content, "具体内容")
        self.assertEqual(BoardOperation(object_id="object", kind="list", items=["知识点"]).items, ["知识点"])

    def test_invalid_operations_are_not_silently_dropped(self):
        for payload in ({"kind": "html", "content": "x"}, {"kind": "box"},
                        {"kind": "arrow", "content": "x", "items": ["x"]},
                        {"kind": "text", "content": "x", "language": "html"},
                        {"kind": "list", "items": [" "]}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                BoardOperation.model_validate({"object_id": "object", **payload})

    def test_script_limits_and_order(self):
        for mutate in (
            lambda d: d.update(steps=d["steps"] * 8),
            lambda d: d["steps"][0].update(operations=[]),
            lambda d: d["steps"][0].update(operations=[{"kind": "text", "content": "x"}] * 7),
            lambda d: d["steps"][0].update(column=3),
            lambda d: d["steps"][0].update(page=0),
            lambda d: d.update(steps=list(reversed(d["steps"]))),
        ):
            data = script_input()
            mutate(data)
            with self.assertRaises(ValidationError):
                BoardScriptDraft.model_validate(data)
        self.assertEqual(len(BoardScriptDraft.model_validate(script_input()).steps), 5)

    def test_code_and_mermaid_whitespace_is_not_normalized(self):
        source = "  print('保留缩进')\n"
        self.assertEqual(BoardOperation(object_id="code", kind="code", content=source, language="python").content, source)
        with self.assertRaises(ValidationError):
            BoardOperation(object_id="text", kind="text", content="  ")

    def test_question_is_trimmed_before_length_validation(self):
        base = {"client_command_id": "question-input", "expected_version": 1,
                "script_id": "script", "cursor": -1, "was_playing": False}
        self.assertEqual(AskQuestion(**base, question="  为什么  ").question, "为什么")
        for question in (" ", "a", "a" * 2001):
            with self.assertRaises(ValidationError):
                AskQuestion(**base, question=question)
        self.assertEqual(len(AskQuestion(**base, question="字" * 2000).question), 2000)


class LessonStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hyperknow-lesson-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "lessons.sqlite3"
        self.db = Database(self.path)
        self.course, self.sid = persist_domain_input(self.db)

    def prepare(self, command="prepare-lesson"):
        return self.db.prepare_lesson(self.sid, command, "stored-model", True)

    def ready(self):
        run = self.prepare()["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(script_input()))
        return self.db.get_lesson(self.sid)

    def command(self, snapshot, identity="lesson-command", **patch):
        return {"client_command_id": identity, "expected_version": snapshot["progress"]["version"],
                "script_id": snapshot["script"]["script_id"], **patch}

    def progress(self, snapshot, cursor, identity="progress-command", play_intent="paused"):
        return self.db.save_progress(self.sid, self.command(snapshot, identity, cursor=cursor,
                                                          play_intent=play_intent))

    def ask(self, snapshot, identity="question-command"):
        return self.db.ask_question(self.sid, self.command(snapshot, identity,
            cursor=snapshot["progress"]["cursor"], question="为什么会暂停？", was_playing=True),
            "stored-model", True)

    def cancel(self, run):
        def mutate(current):
            current.update(status="cancelled", error=None)
            return current
        return self.db.mutate_command("cancel-" + run["run_id"], run["run_id"], run["version"],
                                      {"action": "cancel"}, mutate)

    def test_initial_snapshot_and_prepare_are_idempotent(self):
        initial = self.db.get_lesson(self.sid)
        LessonSnapshot.model_validate(initial)
        self.assertEqual((initial["progress"]["cursor"], initial["progress"]["version"]), (-1, 1))
        self.assertIsNone(initial["script"])
        first = self.prepare()
        self.assertEqual(first, self.prepare())
        self.assertEqual(first, self.prepare("another-prepare"))
        self.assertEqual(first["generation_run"]["kind"], "lesson")
        self.assertEqual(first["generation_run"]["input"]["session"]["outline"], "比较同步调用和协程暂停")

    def test_ready_script_reopens_with_authoritative_intent_and_without_model_config(self):
        snapshot = self.ready()
        script = snapshot["script"]
        self.assertEqual(snapshot["progress"]["cursor"], -1)
        self.assertEqual(len({s["step_id"] for s in script["steps"]}), 5)
        saved = self.progress(snapshot, 0, play_intent="playing")
        reopened = Database(self.path)
        restored = reopened.get_lesson(self.sid)
        self.assertEqual(restored["progress"]["play_intent"], "playing")
        self.assertEqual(restored, saved)
        self.assertEqual(reopened.get_lesson(self.sid), restored)
        self.assertEqual(restored["script"], script)
        prepared = reopened.prepare_lesson(self.sid, "prepare-existing", "changed-default", False)
        self.assertEqual(prepared["script"], script)
        self.assertEqual(prepared, restored)
        self.assertEqual(prepared["generation_run"]["model"], "stored-model")
        self.assertEqual(reopened.calls(prepared["generation_run"]["run_id"]), [])

    def test_prepare_without_configuration_does_not_leave_receipt(self):
        with self.assertRaises(AppError):
            self.db.prepare_lesson(self.sid, "prepare-correctable", "model", False)
        self.assertIsNotNone(self.db.prepare_lesson(self.sid, "prepare-correctable", "model", True)["generation_run"])

    def test_retry_and_course_command_replay_need_no_configuration(self):
        original = self.db.create_run("domain-course-input", "理解协程", "new-default", configured=False)
        self.assertEqual(original["course_id"], self.course["course_id"])
        run = self.prepare()["generation_run"]
        cancelled = self.cancel(run)
        retry = self.db.retry_run("retry-then-unconfigured", run["run_id"], cancelled["version"])
        replay = self.db.retry_run("retry-then-unconfigured", run["run_id"], cancelled["version"], configured=False)
        self.assertEqual(retry, replay)

    def test_progress_only_advances_one_and_replay_returns_latest(self):
        initial = self.ready()
        payload = self.command(initial, "progress-first", cursor=0, play_intent="playing")
        first = self.db.save_progress(self.sid, payload)
        second = self.progress(first, 1, "progress-second")
        self.assertEqual(self.db.save_progress(self.sid, payload), second)
        self.assertEqual(second["progress"]["cursor"], 1)
        for cursor in (-1, 3, 20):
            with self.subTest(cursor=cursor), self.assertRaises(AppError):
                self.progress(second, cursor, "bad-position")
        with self.assertRaises(AppError) as raised:
            self.progress(initial, 0, "stale-position")
        self.assertEqual(raised.exception.latest_version, second["progress"]["version"])

    def test_concurrent_progress_writes_have_single_winner(self):
        snapshot = self.ready()
        def save(i):
            try:
                return self.progress(snapshot, 0, f"concurrent-{i}")
            except AppError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, range(2)))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertIn("version_conflict", results)

    def test_question_context_is_confirmed_prefix_not_future_and_keeps_question(self):
        snapshot = self.progress(self.ready(), 0)
        asked = self.ask(snapshot)
        interaction = asked["interactions"][0]
        run = self.db.get_run(interaction["run_id"])
        self.assertEqual(len(run["input"]["displayed_steps"]), 1)
        self.assertEqual(run["input"]["question"], "为什么会暂停？")
        self.assertEqual(interaction["step_id"], snapshot["script"]["steps"][0]["step_id"])
        self.assertEqual(asked["progress"]["play_intent"], "paused")
        self.assertEqual(self.ask(snapshot), asked)
        with self.assertRaises(AppError) as raised:
            self.ask(asked, "second-question")
        self.assertEqual(raised.exception.code, "question_active")
        with self.assertRaises(AppError):
            self.progress(asked, 1, "progress-while-answering")

    def test_cancel_retry_and_old_result_barrier(self):
        asked = self.ask(self.ready())
        old = self.db.get_run(asked["interactions"][0]["run_id"])
        old = self.db.transition(old["run_id"], {"queued"}, status="generating")
        cancelled = self.cancel(old)
        self.assertEqual(self.db.get_lesson(self.sid)["interactions"][0]["status"], "cancelled")
        retry = self.db.retry_run("question-retry", old["run_id"], cancelled["version"])
        current = self.db.get_lesson(self.sid)
        self.assertEqual(current["interactions"][0]["run_id"], retry["run_id"])
        self.assertEqual(current["interactions"][0]["status"], "pending")
        self.assertEqual(retry["model"], "stored-model")
        self.assertIsNone(self.db.finish_lesson(old["run_id"], LessonAnswer(answer="旧结果")))
        self.db.transition(retry["run_id"], {"queued"}, status="generating")
        self.db.finish_lesson(retry["run_id"], LessonAnswer(answer="新的明确回答"))
        interaction = self.db.get_lesson(self.sid)["interactions"][0]
        self.assertEqual((interaction["status"], interaction["answer"]), ("ready", "新的明确回答"))
        with self.assertRaises(AppError):
            self.db.retry_run("obsolete-retry", old["run_id"], cancelled["version"])

    def test_retry_cannot_occupy_slot_held_by_another_question(self):
        asked = self.ask(self.ready())
        old = self.db.get_run(asked["interactions"][0]["run_id"])
        cancelled = self.cancel(old)
        self.ask(self.db.get_lesson(self.sid), "new-question")
        with self.assertRaises(AppError) as raised:
            self.db.retry_run("blocked-retry", old["run_id"], cancelled["version"])
        self.assertEqual(raised.exception.code, "question_active")
        self.assertEqual(self.db.get_lesson(self.sid)["interactions"][0]["run_id"], old["run_id"])

    def test_restart_marks_interaction_interrupted_and_does_not_regenerate(self):
        asked = self.ask(self.ready())
        run_id = asked["interactions"][0]["run_id"]
        self.db.interrupt_inflight()
        reopened = Database(self.path)
        snapshot = reopened.get_lesson(self.sid)
        self.assertEqual(snapshot["interactions"][0]["status"], "interrupted")
        self.assertEqual(snapshot["script"], asked["script"])
        self.assertEqual(reopened.calls(run_id), [])
        with self.assertRaises(AppError):
            Generator(Settings(data_dir=Path(self.directory.name)), reopened).require_active(run_id, "generating")

    def test_failure_preserves_question_and_script(self):
        asked = self.ask(self.ready())
        run_id = asked["interactions"][0]["run_id"]
        self.db.transition(run_id, {"queued"}, status="failed", error={"code": "direct-error"})
        snapshot = self.db.get_lesson(self.sid)
        self.assertEqual(snapshot["interactions"][0]["question"], "为什么会暂停？")
        self.assertEqual(snapshot["interactions"][0]["status"], "failed")
        self.assertEqual(snapshot["script"], asked["script"])

    def test_complete_without_mastery_gate_and_idempotent_parent_version(self):
        snapshot = self.ready()
        for cursor in range(len(snapshot["script"]["steps"])):
            snapshot = self.progress(snapshot, cursor, f"complete-progress-{cursor}")
        payload = self.command(snapshot, "complete-lesson")
        completed = self.db.complete_lesson(self.sid, payload)
        self.assertTrue(completed["completed"])
        self.assertEqual(completed["progress"]["cursor"], 4)
        course = self.db.get_course(self.course["course_id"])
        self.assertEqual((course["version"], course["progress"]), (2, 100))
        self.assertTrue(course["units"][0]["lectures"][0]["sessions"][0]["completed"])
        self.assertEqual(course["next_item"]["type"], "project")
        self.assertNotIn("url", course["next_item"])
        self.assertEqual(self.db.complete_lesson(self.sid, payload), completed)
        self.db.complete_lesson(self.sid, self.command(completed, "complete-again"))
        self.assertEqual(self.db.get_course(course["course_id"])["version"], 2)
        self.assertEqual(self.db.list_records("courses"), [course])

    def test_failed_prepare_only_retries_explicitly(self):
        run = self.prepare()["generation_run"]
        self.cancel(run)
        snapshot = self.prepare("prepare-after-cancel")
        self.assertEqual(snapshot["generation_run"]["run_id"], run["run_id"])
        self.assertEqual(snapshot["generation_run"]["status"], "cancelled")
        cancelled = self.db.get_run(run["run_id"])
        retry = self.db.retry_run("lesson-explicit-retry", run["run_id"], cancelled["version"])
        self.assertEqual(retry["kind"], "lesson")
        self.assertEqual(retry["input"], run["input"])
        self.assertEqual(self.prepare("prepare-after-retry")["generation_run"]["run_id"], retry["run_id"])

    def test_history_is_bounded_and_required_context_overflow_explicit(self):
        snapshot = self.ready()
        history = [{"interaction_id": str(i), "question": "问题", "answer": "回答", "cursor": -1,
                    "status": "ready"} for i in range(20)]
        session = snapshot["session"]
        context = question_context(self.course, session, snapshot["script"], 0, "当前问题", history)
        self.assertEqual(len(context["recent_interactions"]), 6)
        self.assertEqual(context["recent_interactions"][0]["interaction_id"], "14")
        self.assertEqual(context["question"], "当前问题")
        with self.assertRaises(AppError) as raised:
            question_context(self.course, session, snapshot["script"], 0, "当前问题", [], budget=10)
        self.assertEqual(raised.exception.code, "context_too_large")

    def test_script_ownership_and_command_conflicts(self):
        snapshot = self.ready()
        bad = self.command(snapshot, "wrong-script", cursor=0, play_intent="paused")
        bad["script_id"] = "someone-elses-script"
        with self.assertRaises(AppError):
            self.db.save_progress(self.sid, bad)
        self.progress(snapshot, 0, "same-identity")
        with self.assertRaises(AppError) as raised:
            self.progress(snapshot, 1, "same-identity")
        self.assertEqual(raised.exception.code, "command_conflict")

    def test_script_save_failure_rolls_back_run_and_position_together(self):
        run = self.prepare()["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        before = self.db.get_lesson(self.sid)
        with self.db.transaction() as conn:
            conn.execute("CREATE TRIGGER reject_script BEFORE INSERT ON lesson_scripts "
                         "BEGIN SELECT RAISE(ABORT, 'disk transaction rejection'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(script_input()))
        self.assertEqual(self.db.get_lesson(self.sid), before)
        self.assertEqual(self.db.get_run(run["run_id"])["status"], "generating")

    def test_complete_storage_failure_rolls_back_fact_parent_and_receipt(self):
        snapshot = self.ready()
        for cursor in range(len(snapshot["script"]["steps"])):
            snapshot = self.progress(snapshot, cursor, f"rollback-progress-{cursor}")
        payload = self.command(snapshot, "completion-storage-failure")
        with self.db.transaction() as conn:
            conn.execute("CREATE TRIGGER reject_course BEFORE INSERT ON courses "
                         "BEGIN SELECT RAISE(ABORT, 'disk transaction rejection'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.complete_lesson(self.sid, payload)
        self.assertEqual(self.db.get_lesson(self.sid), snapshot)
        self.assertEqual(self.db.get_course(self.course["course_id"])["version"], 1)
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM command_receipts WHERE id=?",
                                          (payload["client_command_id"],)).fetchone()[0], 0)
            conn.execute("DROP TRIGGER reject_course")
        self.assertTrue(self.db.complete_lesson(self.sid, payload)["completed"])

    def test_next_item_uses_lessons_then_projects_then_exams_without_fake_urls(self):
        course = deepcopy(self.course)
        unit = course["units"][0]
        session = unit["lectures"][0]["sessions"][0]
        stage = unit["project_stages"][0]
        exam = unit["exams"][0]
        done = set()
        for expected, activity in (("lecture", session["session_id"]), ("project", stage["stage_id"]),
                                   ("exam", exam["exam_id"])):
            result = derive_course(deepcopy(course), done)
            self.assertEqual(result["next_item"]["type"], expected)
            self.assertNotIn("url", result["next_item"])
            done.add(activity)
        self.assertIsNone(derive_course(course, done)["next_item"])


class LessonMigrationTests(unittest.TestCase):
    def test_v1_backup_is_real_and_all_old_records_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript("""
                    CREATE TABLE runs(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                    CREATE TABLE courses(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                    CREATE TABLE command_receipts(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,run_id TEXT NOT NULL);
                    CREATE TABLE model_calls(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,data TEXT NOT NULL);
                    PRAGMA user_version=1;
                """)
                conn.execute("INSERT INTO runs VALUES (?,?)", ("old", encode({"run_id": "old", "status": "ready"})))
                conn.execute("INSERT INTO courses VALUES (?,?)", ("preserved", '{"real":"user data"}'))
                conn.execute("INSERT INTO command_receipts VALUES ('command','hash','old')")
                conn.execute("INSERT INTO model_calls VALUES ('call','old','{}')")
                conn.commit()
            db = Database(path)
            self.assertEqual(db.get_run("old")["kind"], "course")
            backups = list(Path(directory).glob("*.bak"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(backup.execute("SELECT data FROM courses").fetchone()[0], '{"real":"user data"}')
                self.assertNotIn("kind", json.loads(backup.execute("SELECT data FROM runs").fetchone()[0]))
            with db.transaction() as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
                for table in ("courses", "command_receipts", "model_calls"):
                    self.assertEqual(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 1)
            Database(path)
            self.assertEqual(len(list(Path(directory).glob("*.bak"))), 1)

    def test_future_database_is_never_downgraded_or_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("PRAGMA user_version=99")
                conn.commit()
            before = path.read_bytes()
            with self.assertRaises(AppError) as raised:
                Database(path)
            self.assertEqual(raised.exception.code, "database_version_unsupported")
            self.assertEqual(path.read_bytes(), before)


class LessonRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_course_answers_phase_is_not_lost_while_clarification_unwinds(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "runtime.sqlite3")
            run = db.create_run("phase-create-input", "理解协程", "stored-model")
            service = CourseService(Settings(data_dir=Path(directory)), db, EventHub())
            service.enqueue(run)
            next_phase = db.transition(run["run_id"], {"queued"}, status="generating", stage="research", answers_submitted=True)
            service.enqueue(next_phase)
            service.enqueue(next_phase)
            self.assertEqual(service.queue.qsize(), 2)
            self.assertEqual(await service.queue.get(), (run["run_id"], "clarifying"))
            self.assertEqual(await service.queue.get(), (run["run_id"], "research"))

    async def test_replayed_queued_run_has_one_worker_entry_and_restart_does_not_charge(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "runtime.sqlite3")
            _, sid = persist_domain_input(db)
            run = db.prepare_lesson(sid, "runtime-prepare", "stored-model", True)["generation_run"]
            service = CourseService(Settings(data_dir=Path(directory)), db, EventHub())
            service.enqueue(run)
            service.enqueue(run)
            self.assertEqual(service.queue.qsize(), 1)
            # start interrupts pending work BEFORE the queue can execute it.
            service.start()
            await asyncio.wait_for(service.queue.join(), timeout=3)
            self.assertEqual(db.get_run(run["run_id"])["status"], "interrupted")
            self.assertEqual(db.calls(run["run_id"]), [])
            await service.close()
