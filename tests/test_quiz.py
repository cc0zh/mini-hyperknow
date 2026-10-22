"""Direct function inputs on real SQLite, never evidence of model generation."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from hyperknow.config import Settings
from hyperknow.domain import AppError
from hyperknow.generation import Generator
from hyperknow.lesson_domain import BoardScriptDraft
from hyperknow.main import AnswerQuiz
from hyperknow.quiz_domain import (
    AttemptSnapshot, MAX_ELAPSED_MS, QuizDraft, QuizSnapshot, quiz_context, score_answers,
    validate_sources,
)
from hyperknow.runtime import CourseService, EventHub
from hyperknow.storage import Database, encode
from test_lesson import persist_domain_input, script_input


def quiz_input(ref):
    # A deterministic input to actual finish_quiz, not injected provider output.
    return {"title": "暂停与恢复练习", "source_refs": [ref], "questions": [
        {"question_id": "q1", "kind": "single", "prompt": "普通调用何时返回控制权？",
         "options": [{"id": "a", "text": "返回时"}, {"id": "b", "text": "始终立即"}],
         "correct_option_ids": ["a"], "explanation": "普通调用在返回前保持控制权。", "source_refs": [ref]},
        {"question_id": "q2", "kind": "multiple", "prompt": "关于暂停和恢复，哪些说法正确？",
         "options": [{"id": "a", "text": "可以暂停"}, {"id": "b", "text": "暂停等于结束"},
                     {"id": "c", "text": "条件满足后继续"}],
         "correct_option_ids": ["a", "c"], "explanation": "暂停并不结束执行，条件满足后继续。",
         "source_refs": [ref]},
        {"question_id": "q3", "kind": "boolean", "prompt": "await可以让调度器安排其他任务。",
         "options": [{"id": "yes", "text": "是"}, {"id": "no", "text": "否"}],
         "correct_option_ids": ["yes"], "explanation": "await在等待时让出控制权。", "source_refs": [ref]},
    ]}


def persisted_quiz(db, target_type, target_id, command="domain-quiz-prepare"):
    snapshot = db.prepare_quiz(target_type, target_id, command, "stored-model", True)
    run = snapshot["generation_run"]
    db.transition(run["run_id"], {"queued"}, status="generating")
    db.finish_quiz(run["run_id"], QuizDraft.model_validate(quiz_input(run["input"]["allowed_source_refs"][0])))
    return db.get_quiz_target(target_type, target_id)


class QuizSchemaTests(unittest.TestCase):
    def test_question_shapes_and_chinese_boolean_labels(self):
        draft = QuizDraft.model_validate(quiz_input("script:real"))
        self.assertEqual(draft.questions[-1].options[0].text, "是")
        changed = quiz_input("script:real")
        changed["questions"][-1]["options"][0]["text"] = "正确"
        self.assertEqual(QuizDraft.model_validate(changed).questions[-1].options[0].text, "正确")
        for count in (3, 8):
            data = quiz_input("script:real")
            for index in range(3, count):
                question = deepcopy(data["questions"][0])
                question["question_id"] = f"q{index + 1}"
                data["questions"].append(question)
            self.assertEqual(len(QuizDraft.model_validate(data).questions), count)

    def test_invalid_counts_types_answers_and_references(self):
        bad = []
        data = quiz_input("script:real"); data["questions"] = data["questions"][:2]; bad.append(data)
        data = quiz_input("script:real"); data["questions"] *= 3; bad.append(data)
        data = quiz_input("script:real"); data["questions"][1]["kind"] = "single"; bad.append(data)
        data = quiz_input("script:real"); data["questions"][1]["correct_option_ids"] = ["a"]; bad.append(data)
        data = quiz_input("script:real"); data["questions"][0]["correct_option_ids"] = ["unknown"]; bad.append(data)
        data = quiz_input("script:real"); data["questions"][0]["options"][1]["id"] = "a"; bad.append(data)
        data = quiz_input("script:real"); data["questions"][2]["options"].append({"id": "x", "text": "不确定"}); bad.append(data)
        data = quiz_input("script:real"); data["questions"][0]["source_refs"] = ["other"]; bad.append(data)
        data = quiz_input("script:real"); data["source_refs"] = []; bad.append(data)
        data = quiz_input("script:real"); data["questions"][0]["question_id"] = "q2"; bad.append(data)
        data = quiz_input("script:real"); data["questions"][1]["correct_option_ids"] = ["a", "a"]; bad.append(data)
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                QuizDraft.model_validate(data)

    def test_source_validation_is_inside_the_structure_validation_boundary(self):
        draft = QuizDraft.model_validate(quiz_input("script:real"))
        self.assertIs(validate_sources(draft, {"allowed_source_refs": ["script:real"]}), draft)
        with self.assertRaises(ValueError):
            validate_sources(draft, {"allowed_source_refs": ["script:other"]})

    def test_numeric_elapsed_bounds_are_not_coerced(self):
        base = {"client_command_id": "numeric-boundary", "expected_version": 1, "question_id": "q1",
                "option_ids": ["a"], "skipped": False}
        for value in (0, 9999, 10000, 10001, MAX_ELAPSED_MS):
            self.assertEqual(AnswerQuiz(**base, elapsed_ms=value).elapsed_ms, value)
        for value in (-1, MAX_ELAPSED_MS + 1, .5, 10000.0, True, "1000", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                AnswerQuiz(**base, elapsed_ms=value)


class QuizScoringTests(unittest.TestCase):
    def answers(self, flags, *, fast=False):
        return [{"correct": correct, "fast": correct and fast, "skipped": False, "elapsed_ms": 11000}
                for correct in flags]

    def test_streak_cap_wrong_and_skip_reset(self):
        result = score_answers(self.answers([True] * 6, fast=True), 6)
        self.assertEqual((result["total_score"], result["max_score"], result["best_streak"]), (6200, 6200, 6))
        self.assertEqual((result["fast_count"], result["stars"]), (6, 3))
        answers = self.answers([True, True, False, True, False, True], fast=True)
        answers[4]["skipped"] = True
        result = score_answers(answers, 6)
        self.assertEqual((result["total_score"], result["best_streak"], result["skipped_count"]), (3300, 2, 1))
        self.assertEqual(result["total_elapsed_ms"], 66000)

    def test_star_paths_use_accuracy_then_score_not_missed_question_count(self):
        # Independent literal expectations from Clone caller parameter semantics.
        for flags, count, total, stars in (([True] * 4 + [False], 5, 3000, 3),
                                          ([True] * 6 + [False] * 4, 10, 5000, 2),
                                          ([True, False, False, False], 4, 600, 1),
                                          ([False] * 3, 3, 0, 0)):
            result = score_answers(self.answers(flags), count)
            self.assertEqual((result["total_score"], result["stars"]), (total, stars))
        self.assertEqual(score_answers([], 0)["stars"], 0)

    def test_accuracy_star_thresholds_include_equality(self):
        for correct, count, stars in ((16, 20, 3), (15, 20, 2), (11, 20, 2),
                                      (10, 20, 1), (5, 20, 1), (4, 20, 0)):
            with self.subTest(correct=correct, count=count):
                result = score_answers(self.answers([True] * correct + [False] * (count - correct)), count)
                self.assertEqual(result["stars"], stars)


class QuizStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hyperknow-quiz-domain-")
        self.path = Path(self.directory.name) / "quiz.sqlite3"
        self.db = Database(self.path)
        self.course, self.sid = persist_domain_input(self.db)
        self.eid = self.course["units"][0]["exams"][0]["exam_id"]

    def tearDown(self):
        self.directory.cleanup()

    def lesson(self):
        run = self.db.prepare_lesson(self.sid, "domain-lesson-input", "stored-model", True)["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(script_input()))
        return self.db.get_lesson(self.sid)

    def ready(self, kind="practice"):
        if kind == "practice":
            self.lesson()
        return persisted_quiz(self.db, kind, self.sid if kind == "practice" else self.eid)

    def attempt(self, target=None):
        target = target or self.ready()
        return self.db.create_attempt(target["quiz"]["quiz_id"], "domain-create-attempt")

    @staticmethod
    def command(snapshot, command, **patch):
        return {"client_command_id": command, "expected_version": snapshot["attempt"]["version"], **patch}

    def answer(self, snapshot, *, elapsed=10000, skipped=False, ids=None, command=None):
        attempt, quiz = snapshot["attempt"], snapshot["quiz"]
        q = quiz["questions"][attempt["cursor"]]
        return self.db.answer_quiz(attempt["attempt_id"], self.command(snapshot,
            command or f"domain-answer-{q['question_id']}", question_id=q["question_id"],
            option_ids=[] if skipped else ids if ids is not None else q["correct_option_ids"],
            skipped=skipped, elapsed_ms=elapsed))

    def finish_answers(self, snapshot):
        for index in range(3):
            snapshot = self.answer(snapshot)
            if index != 2:
                snapshot = self.db.next_question(snapshot["attempt"]["attempt_id"],
                    self.command(snapshot, f"domain-next-{index}"))
        return snapshot

    def cancel(self, run):
        def mutate(current):
            current.update(status="cancelled", error=None)
            return current
        return self.db.mutate_command("domain-cancel-" + run["run_id"], run["run_id"], run["version"],
                                      {"action": "cancel"}, mutate)

    def test_get_is_read_only_and_practice_requires_real_lesson(self):
        snapshot = self.db.get_quiz_target("practice", self.sid)
        QuizSnapshot.model_validate(snapshot)
        self.assertIsNone(snapshot["quiz"])
        self.assertIsNone(snapshot["latest_attempt"])
        with self.assertRaises(AppError) as raised:
            self.db.prepare_quiz("practice", self.sid, "missing-lesson", "model", True)
        self.assertEqual(raised.exception.code, "lesson_required")
        self.assertEqual(self.db.get_quiz_target("practice", self.sid), snapshot)
        with self.db.transaction() as conn:
            for table in ("quizzes", "quiz_states", "quiz_attempts"):
                self.assertEqual(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)

    def test_prepare_cache_concurrent_tabs_and_configuration_replay(self):
        self.lesson()
        before_lesson = self.db.get_lesson(self.sid)
        with ThreadPoolExecutor(max_workers=2) as pool:
            saved = list(pool.map(lambda i: self.db.prepare_quiz("practice", self.sid, f"prepare-tab-{i}",
                                                               "stored-model", True), range(2)))
        self.assertEqual(saved[0], saved[1])
        self.assertEqual(self.db.get_lesson(self.sid), before_lesson)
        run = saved[0]["generation_run"]
        self.assertEqual(run["kind"], "quiz")
        self.assertIsNone(run["session_id"])
        self.assertEqual(self.db.prepare_quiz("practice", self.sid, "prepare-tab-0", "changed", False), saved[0])
        self.assertEqual(self.db.prepare_quiz("practice", self.sid, "prepare-tab-2", "changed", False), saved[0])
        self.assertEqual(self.db.calls(run["run_id"]), [])

    def test_prepare_configuration_failure_does_not_consume_identity(self):
        with self.assertRaises(AppError):
            self.db.prepare_quiz("exam", self.eid, "correctable-prepare", "stored-model", False)
        snapshot = self.db.prepare_quiz("exam", self.eid, "correctable-prepare", "stored-model", True)
        self.assertEqual(snapshot["generation_run"]["kind"], "quiz")

    def test_cancel_retry_interruption_and_late_result_barriers(self):
        run = self.db.prepare_quiz("exam", self.eid, "prepare-exam", "stored-model", True)["generation_run"]
        initial = self.db.get_quiz_target("exam", self.eid)
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        run = self.db.get_run(run["run_id"])
        cancelled = self.cancel(run)
        cached = self.db.prepare_quiz("exam", self.eid, "prepare-cancelled", "changed", False)
        self.assertEqual(cached["generation_run"]["run_id"], run["run_id"])
        self.assertEqual(cached["generation_run"]["status"], "cancelled")
        retry = self.db.retry_run("retry-exam", run["run_id"], cancelled["version"])
        self.assertEqual(retry, self.db.retry_run("retry-exam", run["run_id"], cancelled["version"], configured=False))
        self.assertEqual((retry["kind"], retry["model"], retry["input"]), ("quiz", "stored-model", run["input"]))
        draft = QuizDraft.model_validate(quiz_input(run["input"]["allowed_source_refs"][0]))
        self.assertIsNone(self.db.finish_quiz(run["run_id"], draft))
        with self.assertRaises(AppError):
            self.db.retry_run("retry-obsolete", run["run_id"], cancelled["version"])
        self.db.interrupt_inflight()
        interrupted = self.db.get_quiz_target("exam", self.eid)
        self.assertEqual(interrupted["generation_run"]["status"], "interrupted")
        self.assertGreater(interrupted["version"], initial["version"])
        self.assertEqual(self.db.calls(retry["run_id"]), [])
        with self.assertRaises(AppError):
            Generator(Settings(data_dir=Path(self.directory.name)), self.db).require_active(retry["run_id"], "generating")
        self.assertIsNone(self.db.finish_quiz(retry["run_id"], draft))

    def test_finish_cache_immutable_and_source_validation_atomic(self):
        run = self.db.prepare_quiz("exam", self.eid, "exam-input", "stored-model", True)["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        before = self.db.get_quiz_target("exam", self.eid)
        with self.assertRaises(ValueError):
            self.db.finish_quiz(run["run_id"], QuizDraft.model_validate(quiz_input("script:unknown")))
        self.assertEqual(self.db.get_quiz_target("exam", self.eid), before)
        draft = QuizDraft.model_validate(quiz_input(run["input"]["allowed_source_refs"][0]))
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: self.db.finish_quiz(run["run_id"], draft), range(2)))
        self.assertEqual(sum(r is not None for r in result), 1)
        ready = self.db.get_quiz_target("exam", self.eid)
        QuizSnapshot.model_validate(ready)
        self.assertEqual(Database(self.path).get_quiz_target("exam", self.eid), ready)
        self.assertEqual(self.db.prepare_quiz("exam", self.eid, "cached-exam", "changed", False), ready)

    def test_exam_context_contains_real_unit_outline_and_bounded_cached_scripts(self):
        snapshot = self.lesson()
        unit = self.course["units"][0]
        exam = unit["exams"][0]
        scripts = {self.sid: snapshot["script"]}
        context = quiz_context(self.course, unit, exam, "exam", scripts)
        refs = context["allowed_source_refs"]
        self.assertIn(f"unit:{unit['unit_id']}", refs)
        self.assertIn(f"session:{self.sid}", refs)
        self.assertIn(f"script:{snapshot['script']['script_id']}", refs)
        minimal = quiz_context(self.course, unit, exam, "exam", {})
        size = len(json.dumps(minimal, ensure_ascii=False))
        bounded = quiz_context(self.course, unit, exam, "exam", scripts, budget=size)
        self.assertEqual(bounded, minimal)
        with self.assertRaises(AppError):
            quiz_context(self.course, unit, exam, "exam", {}, budget=1)

    def test_one_unfinished_attempt_across_tabs_and_no_get_creation(self):
        target = self.ready()
        quiz = target["quiz"]
        self.assertEqual(self.db.list_attempts(quiz["quiz_id"]), {"attempts": []})
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(lambda i: self.db.create_attempt(quiz["quiz_id"], f"attempt-tab-{i}"), range(2)))
        self.assertEqual(attempts[0], attempts[1])
        AttemptSnapshot.model_validate(attempts[0])
        self.assertEqual(len(self.db.list_attempts(quiz["quiz_id"])["attempts"]), 1)
        self.assertGreater(self.db.get_quiz_target("practice", self.sid)["version"], target["version"])

    def test_answer_feedback_cursor_timing_and_command_identity(self):
        initial = self.attempt()
        started = initial["attempt"]["question_started_at"]
        answered = self.answer(initial, elapsed=10000, command="boundary-answer")
        answer = answered["attempt"]["answers"][0]
        self.assertEqual((answer["correct"], answer["fast"], answer["points"]), (True, True, 800))
        self.assertEqual(answered["attempt"]["cursor"], 0)
        self.assertEqual(answered["attempt"]["question_started_at"], started)
        self.assertEqual(Database(self.path).get_attempt(answered["attempt"]["attempt_id"]), answered)
        self.assertEqual(self.answer(initial, elapsed=10000, command="boundary-answer"), answered)
        with self.assertRaises(AppError) as raised:
            self.answer(initial, elapsed=9999, command="boundary-answer")
        self.assertEqual(raised.exception.code, "command_conflict")
        with self.assertRaises(AppError) as raised:
            self.answer(initial, command="stale-answer")
        self.assertEqual(raised.exception.latest_version, answered["attempt"]["version"])
        advanced = self.db.next_question(answered["attempt"]["attempt_id"], self.command(answered, "explicit-next"))
        self.assertEqual(advanced["attempt"]["cursor"], 1)
        self.assertNotEqual(advanced["attempt"]["question_started_at"], started)
        self.assertEqual(self.answer(initial, elapsed=10000, command="boundary-answer"), advanced)

    def test_fast_boundary_9999_10000_10001_and_elapsed_limits_directly(self):
        target = self.ready()
        snapshot = self.attempt(target)
        for index, elapsed in enumerate((9999, 10000, 10001)):
            snapshot = self.answer(snapshot, elapsed=elapsed)
            answer = snapshot["attempt"]["answers"][-1]
            self.assertEqual((answer["fast"], answer["points"]), ((True, 800), (True, 900), (False, 800))[index])
            if index != 2:
                snapshot = self.db.next_question(snapshot["attempt"]["attempt_id"], self.command(snapshot, f"boundary-next-{index}"))
        # Invalid direct calls must leave the same attempt and command ID reusable.
        other = self.db.create_attempt(persisted_quiz(self.db, "exam", self.eid, "boundary-exam")["quiz"]["quiz_id"], "boundary-attempt")
        for value in (-1, MAX_ELAPSED_MS + 1, .5, True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(AppError):
                self.answer(other, elapsed=value, command="correctable-elapsed")
        valid = self.answer(other, elapsed=MAX_ELAPSED_MS, command="correctable-elapsed")
        self.assertEqual(valid["attempt"]["answers"][0]["elapsed_ms"], MAX_ELAPSED_MS)
        self.assertFalse(valid["attempt"]["answers"][0]["fast"])

    def test_invalid_selection_and_noncurrent_question_cannot_write(self):
        snapshot = self.attempt()
        aid = snapshot["attempt"]["attempt_id"]
        for ids, skipped in (([], False), (["a", "b"], False), (["missing"], False),
                             (["a", "a"], False), (["a"], True)):
            payload = self.command(snapshot, "correctable-selection", question_id="q1", option_ids=ids,
                                   skipped=skipped, elapsed_ms=0)
            with self.subTest(ids=ids, skipped=skipped), self.assertRaises(AppError):
                self.db.answer_quiz(aid, payload)
        with self.assertRaises(AppError):
            self.db.answer_quiz(aid, self.command(snapshot, "future-question", question_id="q2",
                                                 option_ids=["a"], skipped=False, elapsed_ms=0))
        with self.assertRaises(AppError):
            self.db.next_question(aid, self.command(snapshot, "unanswered-next"))
        with self.assertRaises(AppError):
            self.db.submit_quiz(aid, self.command(snapshot, "early-submit"))
        self.assertEqual(self.db.get_attempt(aid), snapshot)
        answered = self.answer(snapshot, skipped=True, elapsed=0, command="correctable-selection")
        self.assertEqual((answered["attempt"]["answers"][0]["points"], answered["attempt"]["answers"][0]["fast"]), (0, False))
        with self.assertRaises(AppError):
            self.answer(answered, command="rewrite-answer")

    def test_concurrent_answers_have_one_winner(self):
        snapshot = self.attempt()
        def answer(index):
            try:
                return self.answer(snapshot, command=f"answer-tab-{index}")
            except AppError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(answer, range(2)))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertIn("version_conflict", results)

    def test_submit_practice_completes_session_once_and_repractice_preserves_history(self):
        answered = self.finish_answers(self.attempt())
        aid = answered["attempt"]["attempt_id"]
        self.assertEqual(answered["attempt"]["status"], "in_progress")
        with self.assertRaises(AppError):
            self.db.next_question(aid, self.command(answered, "last-next"))
        payload = self.command(answered, "explicit-submit")
        result = self.db.submit_quiz(aid, payload)
        AttemptSnapshot.model_validate(result)
        self.assertEqual((result["attempt"]["result"]["total_score"], result["attempt"]["result"]["stars"]), (2700, 3))
        self.assertEqual(result["course"]["version"], 2)
        self.assertEqual(result["course"]["progress"], 100)
        self.assertEqual(result["course"]["next_item"]["type"], "project")
        self.assertTrue(self.db.get_lesson(self.sid)["completed"])
        self.assertEqual(self.db.submit_quiz(aid, payload), result)
        self.assertEqual(self.db.submit_quiz(aid, self.command(result, "submit-again")), result)
        retry = self.db.create_attempt(result["quiz"]["quiz_id"], "explicit-repractice")
        self.assertNotEqual(retry["attempt"]["attempt_id"], aid)
        self.assertEqual(retry["quiz"], result["quiz"])
        self.assertEqual(self.db.create_attempt(result["quiz"]["quiz_id"], "domain-create-attempt"), result)
        self.assertEqual(self.db.get_attempt(aid), result)
        self.assertEqual(len(self.db.list_attempts(result["quiz"]["quiz_id"])["attempts"]), 2)

    def test_submit_exam_completes_exam_without_changing_session_progress(self):
        target = self.ready("exam")
        answered = self.finish_answers(self.attempt(target))
        result = self.db.submit_quiz(answered["attempt"]["attempt_id"], self.command(answered, "exam-submit"))
        self.assertTrue(self.db.get_quiz_target("exam", self.eid)["completed"])
        self.assertEqual(result["course"]["progress"], 0)
        self.assertEqual(result["course"]["version"], 2)
        self.assertTrue(result["course"]["units"][0]["exams"][0]["completed"])
        self.assertEqual(result["course"]["next_item"]["type"], "lecture")

    def test_practice_submit_after_manual_completion_does_not_increment_course_twice(self):
        target = self.ready()
        lesson = self.db.get_lesson(self.sid)
        self.db.complete_lesson(self.sid, {
            "client_command_id": "manual-first", "expected_version": lesson["progress"]["version"],
            "script_id": lesson["script"]["script_id"]})
        answered = self.finish_answers(self.attempt(target))
        result = self.db.submit_quiz(answered["attempt"]["attempt_id"], self.command(answered, "practice-after-manual"))
        self.assertEqual(result["attempt"]["status"], "submitted")
        self.assertEqual(result["course"]["version"], 2)
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM activity_progress WHERE id=?", (self.sid,)).fetchone()[0], 1)
            fact = json.loads(conn.execute("SELECT data FROM activity_progress WHERE id=?", (self.sid,)).fetchone()[0])
            self.assertNotIn("attempt_id", fact)  # Preserve the original completion fact.

    def test_manual_lesson_completion_bumps_practice_target_without_a_quiz(self):
        lesson = self.lesson()
        before = self.db.get_quiz_target("practice", self.sid)
        payload = {"client_command_id": "manual-complete", "expected_version": lesson["progress"]["version"],
                   "script_id": lesson["script"]["script_id"]}
        self.db.complete_lesson(self.sid, payload)
        after = self.db.get_quiz_target("practice", self.sid)
        self.assertTrue(after["completed"])
        self.assertGreater(after["version"], before["version"])
        self.assertIsNone(after["quiz"])
        self.db.complete_lesson(self.sid, payload)
        self.assertEqual(self.db.get_quiz_target("practice", self.sid), after)

    def test_submit_failure_rolls_back_result_fact_course_and_receipt(self):
        answered = self.finish_answers(self.attempt())
        aid = answered["attempt"]["attempt_id"]
        target = self.db.get_quiz_target("practice", self.sid)
        payload = self.command(answered, "transaction-submit")
        with self.db.transaction() as conn:
            conn.execute("CREATE TRIGGER reject_course BEFORE INSERT ON courses BEGIN SELECT RAISE(ABORT,'disk rejection'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.submit_quiz(aid, payload)
        self.assertEqual(self.db.get_attempt(aid), answered)
        self.assertEqual(self.db.get_quiz_target("practice", self.sid), target)
        self.assertFalse(self.db.get_lesson(self.sid)["completed"])
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM command_receipts WHERE id=?", (payload["client_command_id"],)).fetchone()[0], 0)
            conn.execute("DROP TRIGGER reject_course")
        self.assertEqual(self.db.submit_quiz(aid, payload)["attempt"]["status"], "submitted")

    def test_quiz_save_failure_rolls_back_run_and_target(self):
        run = self.db.prepare_quiz("exam", self.eid, "save-failure", "stored-model", True)["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        before = self.db.get_quiz_target("exam", self.eid)
        with self.db.transaction() as conn:
            conn.execute("CREATE TRIGGER reject_quiz BEFORE INSERT ON quizzes BEGIN SELECT RAISE(ABORT,'disk rejection'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.finish_quiz(run["run_id"], QuizDraft.model_validate(quiz_input(run["input"]["allowed_source_refs"][0])))
        self.assertEqual(self.db.get_quiz_target("exam", self.eid), before)

    def test_unknown_and_duplicate_target_are_not_empty_snapshots(self):
        for kind, key in (("practice", "missing"), ("exam", self.sid), ("unknown", self.sid)):
            with self.subTest(kind=kind, key=key), self.assertRaises(AppError):
                self.db.get_quiz_target(kind, key)
        duplicate = deepcopy(self.course)
        duplicate["course_id"] = "duplicate-course"
        with self.db.transaction() as conn:
            self.db._write(conn, "courses", duplicate["course_id"], duplicate)
        with self.assertRaises(AppError) as raised:
            self.db.get_quiz_target("practice", self.sid)
        self.assertEqual(raised.exception.code, "invalid_target")


class QuizMigrationTests(unittest.TestCase):
    def test_v2_backup_and_eight_existing_tables_are_byte_for_byte_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v2.sqlite3"
            tables = ("runs", "courses", "command_receipts", "model_calls", "lesson_scripts",
                      "lesson_states", "lesson_interactions", "activity_progress")
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript("""
                    CREATE TABLE runs(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                    CREATE TABLE courses(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                    CREATE TABLE command_receipts(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,run_id TEXT NOT NULL,resource_type TEXT NOT NULL DEFAULT 'run');
                    CREATE TABLE model_calls(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,data TEXT NOT NULL);
                    CREATE TABLE lesson_scripts(id TEXT PRIMARY KEY,session_id TEXT NOT NULL UNIQUE,data TEXT NOT NULL);
                    CREATE TABLE lesson_states(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                    CREATE TABLE lesson_interactions(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,data TEXT NOT NULL);
                    CREATE INDEX interactions_session ON lesson_interactions(session_id);
                    CREATE TABLE activity_progress(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                    PRAGMA user_version=2;
                """)
                for table in tables:
                    columns = len(conn.execute(f"PRAGMA table_info({table})").fetchall())
                    values = [f"{table}-id"] + [f"original {table} value {i}" for i in range(1, columns)]
                    if table == "runs":
                        values[-1] = '{ "run_id": "runs-id", "kind": "lesson", "status": "ready" }'
                    conn.execute(f"INSERT INTO {table} VALUES ({','.join('?' * columns)})", values)
                conn.commit()
                before = {table: conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() for table in tables}
                digest = hashlib.sha256(repr(before).encode()).hexdigest()
            db = Database(path)
            backup_path, = list(Path(directory).glob("*.bak"))
            with closing(sqlite3.connect(backup_path)) as backup:
                self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 2)
                copied = {table: backup.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() for table in tables}
                self.assertEqual(copied, before)
                self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            with db.transaction() as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
                after = {table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")] for table in tables}
                self.assertEqual(hashlib.sha256(repr(after).encode()).hexdigest(), digest)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                actual_tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertEqual(actual_tables, {*tables, "quizzes", "quiz_states", "quiz_attempts"})
                index = conn.execute("SELECT sql FROM sqlite_master WHERE name='one_open_attempt'").fetchone()["sql"]
                self.assertIn("UNIQUE INDEX", index)
                self.assertIn("WHERE status='in_progress'", index)
            self.assertNotIn("quiz_id", db.get_run("runs-id"))
            Database(path)
            self.assertEqual(len(list(Path(directory).glob("*.bak"))), 1)

    def test_future_v4_is_refused_without_rewrite_or_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("PRAGMA user_version=4")
                conn.commit()
            before = path.read_bytes()
            with self.assertRaises(AppError) as raised:
                Database(path)
            self.assertEqual(raised.exception.code, "database_version_unsupported")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob("*.bak")), [])


class QuizRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_quiz_single_worker_admission_dedupe_and_restart_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "runtime.sqlite3")
            course, _ = persist_domain_input(db)
            eid = course["units"][0]["exams"][0]["exam_id"]
            run = db.prepare_quiz("exam", eid, "runtime-quiz", "stored-model", True)["generation_run"]
            service = CourseService(Settings(data_dir=Path(directory)), db, EventHub())
            service.enqueue(run)
            service.enqueue(run)
            self.assertEqual(service.queue.qsize(), 1)
            # Real service startup interrupts prior work before it can call a model.
            service.start()
            await asyncio.wait_for(service.queue.join(), timeout=3)
            self.assertEqual(db.get_run(run["run_id"])["status"], "interrupted")
            self.assertEqual(db.calls(run["run_id"]), [])
            await service.close()
