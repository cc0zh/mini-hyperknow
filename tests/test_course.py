"""Direct rules/schema/SQLite checks; not evidence of real model acceptance."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from hyperknow.config import Settings
from hyperknow.domain import (
    AppError, Clarification, CourseDraft, materialize_course, resolve_answers,
)
from hyperknow.generation import Generator, parse_json
from hyperknow.storage import Database


def questions():
    return Clarification.model_validate({"questions": [{
        "id": "experience", "question": "已有的 Python 经验？", "type": "single",
        "allow_custom": True, "options": [
            {"id": "new", "label": "刚开始", "description": "从基础开始"},
            {"id": "basic", "label": "会基础", "description": "能写简单程序"},
        ],
    }]}).model_dump()["questions"]


def course_data():
    # Explicit schema input, never presented as a model response.
    return {
        "title": "Python 协程", "description": "理解协程的暂停和恢复",
        "target_learner": "会基础 Python 的学习者", "difficulty": "beginner",
        "tags": ["Python"],
        "projects": [{"project_key": "scheduler", "name": "协作调度器",
                      "description": "轮流推进两个协程", "final_deliverable": "可运行的调度器"}],
        "units": [{
            "title": "协作执行", "description": "认识暂停点",
            "lectures": [{"title": "协程", "description": "暂停与恢复",
                          "sessions": [{"title": "暂停点", "description": "执行到 await",
                                        "outline": "比较同步调用和协程暂停",
                                        "key_points": ["await 允许协作式切换"],
                                        "estimated_minutes": 15}]}],
            "exams": [{"title": "暂停点考核", "goal": "辨认暂停与阻塞"}],
            "project_stages": [{"project_key": "scheduler", "title": "推进两个协程",
                                "description": "观察交替执行", "deliverable": "执行顺序记录"}],
        }],
    }


class AnswerTests(unittest.TestCase):
    def test_answers_include_question_and_selected_option_text(self):
        source = questions()
        before = deepcopy(source)
        result = resolve_answers(source, [{"question_id": "experience",
                                          "option_ids": ["basic"], "custom_text": "  会循环  "}], False)
        self.assertEqual(result, [{"question_id": "experience", "question": source[0]["question"],
                                   "option_ids": ["basic"], "selected_options": [source[0]["options"][1]],
                                   "custom_text": "会循环"}])
        self.assertEqual(source, before)

    def test_multi_answer_preserves_all_selected_options(self):
        source = questions()
        source[0]["type"] = "multi"
        result = resolve_answers(source, [{"question_id": "experience", "option_ids": ["basic", "new"]}], False)
        self.assertEqual([option["id"] for option in result[0]["selected_options"]], ["basic", "new"])

    def test_explicit_skip_accepts_no_answers(self):
        self.assertEqual(resolve_answers(questions(), [], True), [])

    def test_invalid_answers_are_rejected(self):
        valid = {"question_id": "experience", "option_ids": ["basic"]}
        cases = [
            (questions(), [valid], True),
            (questions(), [], False),
            (questions(), [{"question_id": "unknown", "option_ids": ["basic"]}], False),
            (questions(), [valid, valid], False),
            (questions(), [{"question_id": "experience", "option_ids": ["unknown"]}], False),
            (questions(), [{"question_id": "experience", "option_ids": ["basic", "basic"]}], False),
            (questions(), [{"question_id": "experience", "option_ids": ["new", "basic"]}], False),
            (questions(), [{"question_id": "experience", "custom_text": "   "}], False),
        ]
        no_custom = questions()
        no_custom[0]["allow_custom"] = False
        cases.append((no_custom, [{"question_id": "experience", "custom_text": "其他"}], False))
        for index, (source, answers, skip) in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(AppError) as raised:
                    resolve_answers(source, answers, skip)
                self.assertEqual((raised.exception.code, raised.exception.status), ("invalid_answers", 400))


class CourseSchemaTests(unittest.TestCase):
    def test_valid_course_draft_round_trips(self):
        draft = CourseDraft.model_validate(course_data())
        self.assertEqual(CourseDraft.model_validate_json(draft.model_dump_json()), draft)

    def test_nonempty_hierarchy_and_bounded_session_are_required(self):
        for case in ("units", "lectures", "sessions", "duration", "key_points", "tags", "extra"):
            with self.subTest(case=case):
                data = course_data()
                session = data["units"][0]["lectures"][0]["sessions"][0]
                if case == "units":
                    data["units"] = []
                elif case == "lectures":
                    data["units"][0]["lectures"] = []
                elif case == "sessions":
                    data["units"][0]["lectures"][0]["sessions"] = []
                elif case == "duration":
                    session["estimated_minutes"] = 0
                elif case == "key_points":
                    session["key_points"] = ["  "]
                elif case == "tags":
                    data["tags"] = ["  "]
                else:
                    data["unknown"] = True
                with self.assertRaises(ValidationError):
                    CourseDraft.model_validate(data)

    def test_project_keys_and_references_are_validated(self):
        for case in ("duplicate", "unknown", "unstaged"):
            with self.subTest(case=case):
                data = course_data()
                if case == "duplicate":
                    data["projects"].append(deepcopy(data["projects"][0]))
                elif case == "unknown":
                    data["units"][0]["project_stages"][0]["project_key"] = "missing"
                else:
                    data["units"][0]["project_stages"] = []
                with self.assertRaises(ValidationError):
                    CourseDraft.model_validate(data)

    def test_clarification_requires_unique_question_and_option_ids(self):
        for case in ("question", "option"):
            with self.subTest(case=case):
                data = {"questions": questions()}
                if case == "question":
                    data["questions"].append(deepcopy(data["questions"][0]))
                else:
                    data["questions"][0]["options"][1]["id"] = "new"
                with self.assertRaises(ValidationError):
                    Clarification.model_validate(data)

    def test_materialization_assigns_unique_ids_and_preserves_snapshot(self):
        draft = CourseDraft.model_validate(course_data())
        original = draft.model_dump()
        run = {"goal": "理解 Python 协程", "questions": questions(),
               "answers": resolve_answers(questions(), [{"question_id": "experience", "option_ids": ["basic"]}], False),
               "skipped": False}
        timestamp = "2026-10-22T00:00:00+00:00"
        course = materialize_course(draft, run, timestamp)
        unit = course["units"][0]
        lecture = unit["lectures"][0]
        session = lecture["sessions"][0]
        project = course["projects"][0]
        stage = unit["project_stages"][0]
        ids = [course["course_id"], unit["unit_id"], lecture["lecture_id"], session["session_id"],
               project["project_id"], stage["stage_id"], unit["exams"][0]["exam_id"]]
        self.assertTrue(all(isinstance(value, str) and value for value in ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(stage["project_id"], project["project_id"])
        self.assertNotIn("project_key", project)
        self.assertNotIn("project_key", stage)
        self.assertEqual(course["goal"], run["goal"])
        self.assertEqual(course["clarification"], {key: run[key] for key in ("questions", "answers", "skipped")})
        self.assertEqual(course["created_at"], timestamp)
        self.assertEqual((course["unit_count"], course["session_count"], course["exam_count"]), (1, 1, 1))
        self.assertEqual((course["version"], course["progress"]), (1, 0))
        self.assertEqual(course["next_item"], {"type": "lecture", "title": session["title"],
                                               "session_id": session["session_id"], "unit_id": unit["unit_id"]})
        self.assertEqual(draft.model_dump(), original)


class JsonParsingTests(unittest.TestCase):
    def test_parse_json_preserves_unicode_and_nested_data(self):
        self.assertEqual(parse_json(' \n{"title":"协程","units":[{"title":"暂停"}]} \n'),
                         {"title": "协程", "units": [{"title": "暂停"}]})

    def test_malformed_json_is_rejected_not_replaced_with_a_course(self):
        for source in ("", '{"title":', '{"title":"协程",}', 'not JSON'):
            with self.subTest(source=source), self.assertRaises((ValueError, AppError)):
                parse_json(source)


class CourseStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = Settings(data_dir=Path(directory.name))
        self.path = self.settings.data_dir / "hyperknow.sqlite3"
        self.db = Database(self.path)
        self.draft = CourseDraft.model_validate(course_data())

    def create(self, command="create-course-1"):
        return self.db.create_run(command, "理解 Python 协程", self.settings.model)

    def generating(self):
        run = self.create()
        return self.db.transition(run["run_id"], {"queued"}, status="generating")

    def test_course_and_run_survive_reopening_sqlite(self):
        run = self.generating()
        ready = self.db.finish_course(run["run_id"], self.draft)
        saved_course = self.db.get_course(ready["course_id"])
        self.assertTrue(self.path.is_file())
        reopened = Database(self.path)
        self.assertEqual(reopened.get_run(run["run_id"]), ready)
        self.assertEqual(reopened.get_course(ready["course_id"]), saved_course)
        self.assertEqual(reopened.list_records("courses"), [saved_course])
        self.assertEqual((ready["status"], ready["version"]), ("ready", run["version"] + 1))

    def test_create_command_is_idempotent_after_reopen(self):
        run = self.create()
        reopened = Database(self.path)
        self.assertEqual(reopened.create_run("create-course-1", run["goal"], self.settings.model), run)
        self.assertEqual(reopened.list_records("runs"), [run])

    def test_same_command_with_different_goal_returns_409(self):
        original = self.create()
        with self.assertRaises(AppError) as raised:
            self.db.create_run("create-course-1", "学习其他主题", self.settings.model)
        self.assertEqual((raised.exception.code, raised.exception.status), ("command_conflict", 409))
        self.assertEqual(self.db.list_records("runs"), [original])

    def test_command_replay_keeps_original_run_when_default_model_changes(self):
        original = self.create()
        reopened = Database(self.path)
        replay = reopened.create_run("create-course-1", original["goal"], "different-configured-model")
        self.assertEqual(replay, original)
        self.assertEqual(replay["model"], self.settings.model)
        self.assertEqual(reopened.list_records("runs"), [original])

    def test_mutation_replay_does_not_increment_version_twice(self):
        run = self.create()
        def cancel(current):
            return {**current, "status": "cancelled"}
        args = ("cancel-course-1", run["run_id"], run["version"], {"action": "cancel"}, cancel)
        saved = self.db.mutate_command(*args)
        self.assertEqual(saved["version"], run["version"] + 1)
        self.assertEqual(Database(self.path).mutate_command(*args), saved)

    def test_stale_version_rejects_mutation_without_changing_run(self):
        run = self.generating()
        with self.assertRaises(AppError) as raised:
            self.db.mutate_command("stale-cancel-1", run["run_id"], run["version"] - 1,
                                   {"action": "cancel"}, lambda current: {**current, "status": "cancelled"})
        self.assertEqual((raised.exception.code, raised.exception.status), ("version_conflict", 409))
        self.assertEqual(Database(self.path).get_run(run["run_id"]), run)

    def test_cancelled_run_rejects_late_course_without_persisting_it(self):
        run = self.generating()
        cancelled = self.db.mutate_command(
            "cancel-course-1", run["run_id"], run["version"], {"action": "cancel"},
            lambda current: {**current, "status": "cancelled"})
        self.assertIsNone(self.db.finish_course(run["run_id"], self.draft))
        reopened = Database(self.path)
        self.assertEqual(reopened.list_records("courses"), [])
        self.assertEqual(reopened.get_run(run["run_id"]), cancelled)
        self.assertIsNone(cancelled["course_id"])

    def test_ready_run_rejects_retry_without_creating_another_run(self):
        ready = self.db.finish_course(self.generating()["run_id"], self.draft)
        with self.assertRaises(AppError) as raised:
            self.db.retry_run("retry-ready-1", ready["run_id"], ready["version"])
        self.assertEqual((raised.exception.code, raised.exception.status), ("state_conflict", 409))
        self.assertEqual(self.db.list_records("runs"), [ready])
        self.assertEqual(len(self.db.list_records("courses")), 1)

    def test_concurrent_finish_creates_at_most_one_course_per_run(self):
        run = self.generating()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.db.finish_course(run["run_id"], self.draft), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        reopened = Database(self.path)
        courses = reopened.list_records("courses")
        self.assertEqual(len(courses), 1)
        saved = reopened.get_run(run["run_id"])
        self.assertEqual(saved["course_id"], courses[0]["course_id"])
        self.assertEqual(saved["status"], "ready")

    def test_restart_interrupts_inflight_but_preserves_awaiting_answers_and_ready(self):
        runs = {}
        for status in ("queued", "clarifying", "generating", "awaiting_answers", "cancelled", "failed", "ready"):
            run = self.create("create-" + status)
            if status == "ready":
                self.db.transition(run["run_id"], {"queued"}, status="generating")
                run = self.db.finish_course(run["run_id"], self.draft)
            elif status != "queued":
                run = self.db.transition(run["run_id"], {"queued"}, status=status, questions=questions())
            runs[status] = run
        restarted = Database(self.path)
        restarted.interrupt_inflight()
        for status, old in runs.items():
            with self.subTest(status=status):
                saved = restarted.get_run(old["run_id"])
                if status in {"queued", "clarifying", "generating"}:
                    self.assertEqual(saved["status"], "interrupted")
                    self.assertEqual(saved["version"], old["version"] + 1)
                    self.assertEqual(saved["error"]["code"], "interrupted")
                    self.assertTrue(saved["error"]["retryable"])
                else:
                    self.assertEqual(saved, old)
        before = restarted.list_records("runs")
        restarted.interrupt_inflight()
        self.assertEqual(restarted.list_records("runs"), before)
        self.assertEqual(len(restarted.list_records("courses")), 1)


class GenerationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hyperknow-admission-")
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.db = Database(root / "hyperknow.sqlite3")
        self.generator = Generator(Settings(data_dir=root), self.db)
        run = self.db.create_run("admission-command", "研究协程暂停", "configured-model")
        self.run_id = run["run_id"]
        self.db.transition(self.run_id, {"queued"}, status="generating")

    def test_cancel_blocks_later_model_admission(self):
        self.generator.require_active(self.run_id, "generating")
        self.db.transition(self.run_id, {"generating"}, status="cancelled")
        with self.assertRaises(AppError) as raised:
            self.generator.require_active(self.run_id, "generating")
        self.assertEqual(raised.exception.code, "run_inactive")

    def test_process_shutdown_blocks_later_model_admission(self):
        self.generator.stopping.set()
        with self.assertRaises(AppError):
            self.generator.require_active(self.run_id, "generating")
        self.assertEqual(self.db.get_run(self.run_id)["status"], "generating")

    def test_restart_interruption_blocks_old_generation_admission(self):
        self.db.interrupt_inflight()
        with self.assertRaises(AppError):
            self.generator.require_active(self.run_id, "generating")


if __name__ == "__main__":
    unittest.main()
