"""Real schema, SQLite and queue checks; no model or search substitution."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from hyperknow.config import Settings
from hyperknow.domain import Clarification, course_research_input
from hyperknow.runtime import CourseService, EventHub
from hyperknow.storage import Database
from tests.test_course import questions


class ClarificationFlowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hyperknow-clarification-")
        self.addCleanup(directory.cleanup)
        self.settings = Settings(data_dir=Path(directory.name))
        self.path = self.settings.data_dir / "hyperknow.sqlite3"
        self.db = Database(self.path)
        run = self.db.create_run("create-clarification", "学习明确范围的Python协程", "saved-model")
        self.run = self.db.transition(run["run_id"], {"queued"}, status="clarifying")

    def test_schema_requires_questions_but_accepts_zero_and_rejects_more_than_five(self):
        self.assertEqual(Clarification(questions=[]).model_dump(), {"questions": []})
        with self.assertRaises(ValidationError):
            Clarification.model_validate({})
        source = questions()[0]
        with self.assertRaises(ValidationError):
            Clarification(questions=[{**source, "id": f"q{i}"} for i in range(6)])

    def test_zero_questions_commit_directly_to_research_without_claiming_user_skip(self):
        saved = self.db.finish_clarification(self.run["run_id"], Clarification(questions=[]))
        self.assertEqual((saved["status"], saved["stage"]), ("generating", "research"))
        self.assertEqual((saved["questions"], saved["answers"]), ([], []))
        self.assertFalse(saved["skipped"])
        self.assertTrue(saved["answers_submitted"])
        self.assertEqual(saved["version"], self.run["version"] + 1)
        self.assertEqual(saved["input"], course_research_input(saved))
        self.assertEqual(json.loads(saved["input"]["context"]),
                         {"questions": [], "answers": [], "clarification_skipped": False})
        self.assertEqual(Database(self.path).get_run(saved["run_id"]), saved)
        self.assertIsNone(self.db.finish_clarification(saved["run_id"], Clarification(questions=[])))
        self.assertEqual(self.db.calls(saved["run_id"]), [])

    def test_nonempty_questions_still_wait_for_user_and_do_not_enqueue_research(self):
        saved = self.db.finish_clarification(self.run["run_id"], Clarification(questions=questions()))
        self.assertEqual(saved["status"], "awaiting_answers")
        self.assertFalse(saved["answers_submitted"])
        self.assertEqual(saved["questions"], questions())
        service = CourseService(self.settings, self.db, EventHub())
        asyncio.run(service.continue_committed_run(saved["run_id"]))
        self.assertTrue(service.queue.empty())

    def test_committed_zero_question_state_schedules_research_without_running_it(self):
        saved = self.db.finish_clarification(self.run["run_id"], Clarification(questions=[]))
        service = CourseService(self.settings, self.db, EventHub())
        asyncio.run(service.continue_committed_run(saved["run_id"]))
        self.assertEqual(service.queue.get_nowait(), (saved["run_id"], "research"))
        self.assertTrue(service.queue.empty())
        self.assertEqual(self.db.calls(saved["run_id"]), [])

    def test_cancelled_clarification_cannot_submit_late_empty_or_nonempty_result(self):
        cancelled = self.db.transition(self.run["run_id"], {"clarifying"}, status="cancelled")
        for result in (Clarification(questions=[]), Clarification(questions=questions())):
            self.assertIsNone(self.db.finish_clarification(self.run["run_id"], result))
        self.assertEqual(self.db.get_run(self.run["run_id"]), cancelled)
