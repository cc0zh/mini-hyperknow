"""Teacher-led classroom protocol checks; real-model quality is validated separately."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from hyperknow.config import Settings
from hyperknow.domain import AppError, CourseDraft
from hyperknow.lesson_domain import BoardOperation
from hyperknow.storage import Database
from hyperknow.teacher import (BoardLedger, TeachingBasisDraft, TeacherGenerationResult,
                               TeacherTurnDraft, validate_basis, whiteboard_tool)
from test_course import course_data


def operation(object_id: str, content: str, target_ids: list[str] | None = None) -> dict:
    return BoardOperation(object_id=object_id, kind="text", target_ids=target_ids or [], content=content,
                           items=[], language="", columns=[], rows=[], nodes=[], edges=[]).model_dump()


class TeacherProtocolTests(unittest.TestCase):
    def test_whiteboard_ledger_rejects_duplicate_and_future_references(self):
        ledger = BoardLedger()
        self.assertTrue(ledger.present({"operations": [operation("first", "先定义")]}).success)
        self.assertFalse(ledger.present({"operations": [operation("first", "重复")]}).success)
        self.assertFalse(ledger.present({"operations": [operation("later", "不能前向引用", ["missing"])]}).success)
        self.assertEqual([item["object_id"] for item in ledger.operations], ["first"])

    def test_whiteboard_tool_schema_is_provider_compatible(self):
        schema = whiteboard_tool(BoardLedger()).parameters
        self.assertNotIn("$defs", str(schema))
        self.assertNotIn("pattern", str(schema))
        self.assertEqual(schema["properties"]["operations"]["items"]["required"], ["kind", "object_id"])

    def test_basis_requires_allowed_source_references(self):
        draft = TeachingBasisDraft.model_validate({
            "schema_version": 1, "objectives": ["理解暂停点"], "objective_refs": ["keypoint:0"],
            "knowledge": [{"item_id": "k1", "content": "暂停点让出执行机会", "source_refs": ["keypoint:0"]}],
            "examples": [{"item_id": "e1", "content": "两个任务交替", "source_refs": ["keypoint:0"]}],
            "derivations": [], "misconceptions": [{"item_id": "m1", "content": "暂停等于阻塞", "source_refs": ["keypoint:0"]}],
            "teaching_options": [{"option_id": "o1", "approach": "先画状态变化", "useful_when": "学生混淆等待和阻塞", "source_refs": ["keypoint:0"]}],
        })
        validate_basis(draft, {"basis_allowed_refs": ["keypoint:0"]})
        with self.assertRaises(ValueError):
            validate_basis(draft, {"basis_allowed_refs": ["keypoint:1"]})

    def test_teacher_prepare_and_turn_do_not_replace_legacy_script(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            db = Database(settings.data_dir / "hyperknow.sqlite3")
            course_run = db.create_run("course", "理解 Python 协程", settings.model)
            course_run = db.transition(course_run["run_id"], {"queued"}, status="generating")
            ready_run = db.finish_course(course_run["run_id"], CourseDraft.model_validate(course_data()))
            course = db.get_course(ready_run["course_id"])
            session_id = course["units"][0]["lectures"][0]["sessions"][0]["session_id"]
            prepared = db.prepare_teacher_lesson(session_id, "teacher-prepare", settings.model, True)
            basis_run = prepared["generation_run"]
            self.assertEqual(basis_run["kind"], "lesson_basis")
            self.assertIsNone(prepared["script"])
            basis_run = db.transition(basis_run["run_id"], {"queued"}, status="generating")
            draft = TeachingBasisDraft.model_validate({
                "schema_version": 1, "objectives": ["理解暂停点"], "objective_refs": ["keypoint:0"],
                "knowledge": [{"item_id": "k1", "content": "await让出机会", "source_refs": ["keypoint:0"]}],
                "examples": [{"item_id": "e1", "content": "两个任务交替", "source_refs": ["keypoint:0"]}],
                "derivations": [], "misconceptions": [{"item_id": "m1", "content": "await等于阻塞", "source_refs": ["keypoint:0"]}],
                "teaching_options": [{"option_id": "o1", "approach": "画状态", "useful_when": "混淆概念", "source_refs": ["keypoint:0"]}],
            })
            self.assertIsNotNone(db.finish_lesson_basis(basis_run["run_id"], draft))
            ready = db.get_lesson(session_id)
            teacher_version = ready["teacher"]["version"]
            turn = db.start_teacher_turn(session_id, {"client_command_id": "teacher-turn", "expected_version": teacher_version}, settings.model, True)
            turn_run = db.transition(turn["generation_run"]["run_id"], {"queued"}, status="generating")
            result = TeacherGenerationResult(
                TeacherTurnDraft(action="explain", response="先把暂停和阻塞分开。", awaits_student=False,
                                 basis_refs=["keypoint:0"]),
                [operation("pause", "暂停")], [], "stop")
            self.assertIsNotNone(db.finish_teacher_turn(turn_run["run_id"], result))
            saved = db.get_lesson(session_id)
            self.assertEqual(saved["teacher"]["turns"][0]["response"], "先把暂停和阻塞分开。")
            self.assertEqual(saved["teacher"]["board"]["operations"][0]["object_id"], "pause")
            self.assertEqual(saved["script"], None)
            second = db.start_teacher_turn(session_id, {"client_command_id": "teacher-turn-2",
                                                        "expected_version": saved["teacher"]["version"],
                                                        "student_answer": "暂停会让出执行机会"}, settings.model, True)
            second_run = db.transition(second["generation_run"]["run_id"], {"queued"}, status="generating")
            second_result = TeacherGenerationResult(
                TeacherTurnDraft(action="adapt", response="对，接下来比较它和阻塞。", awaits_student=False,
                                 basis_refs=["keypoint:0"]),
                [operation("contrast", "对比", ["pause"])], [], "stop")
            db.finish_teacher_turn(second_run["run_id"], second_result)
            self.assertEqual([item["object_id"] for item in db.get_lesson(session_id)["teacher"]["board"]["operations"]],
                             ["pause", "contrast"])
            failed = db.start_teacher_turn(session_id, {"client_command_id": "teacher-turn-failed",
                                                         "expected_version": db.get_lesson(session_id)["teacher"]["version"]}, settings.model, True)
            failed_run = db.transition(failed["generation_run"]["run_id"], {"queued"}, status="generating")
            failed_run = db.transition(failed_run["run_id"], {"generating"}, status="failed",
                                       error={"code": "provider_error", "message": "provider stopped", "retryable": True})
            retry = db.retry_run("teacher-retry", failed_run["run_id"], failed_run["version"])
            self.assertEqual(retry["kind"], "teacher_turn")
            self.assertEqual(db.get_lesson(session_id)["teacher"]["pending_run_id"], retry["run_id"])
            self.assertEqual(retry["teacher_version"], db.get_lesson(session_id)["teacher"]["version"])
            retry = db.transition(retry["run_id"], {"queued"}, status="generating")
            retry_result = TeacherGenerationResult(
                TeacherTurnDraft(action="continue", response="重试后继续当前比较。", awaits_student=False,
                                 basis_refs=["keypoint:0"]), [], [], "stop")
            db.finish_teacher_turn(retry["run_id"], retry_result)
            self.assertEqual(len(db.get_lesson(session_id)["teacher"]["turns"]), 3)
            before_replay = len([run for run in db.list_records("runs") if run.get("kind") == "teacher_turn"])
            replay = db.start_teacher_turn(session_id, {"client_command_id": "teacher-turn", "expected_version": teacher_version}, settings.model, True)
            self.assertEqual(len([run for run in db.list_records("runs") if run.get("kind") == "teacher_turn"]), before_replay)
            self.assertEqual(replay["session"]["session_id"], session_id)


if __name__ == "__main__":
    unittest.main()
