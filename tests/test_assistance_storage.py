"""Real temporary SQLite transactions; no provider or persistence substitutes."""

import copy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest

from hyperknow.domain import AppError, CourseDraft
from hyperknow.storage import Database
from tests.test_course import course_data


def response_result(*artifacts):
    return {"response": {"text": "先确定已知量，再逐步推导。", "questions": [], "plan": [],
                         "current_step": 0, "waiting_for": "none"},
            "artifacts": list(artifacts), "skill_uses": []}


def board_draft():
    return {"kind": "whiteboard", "title": "分步推导", "data": {"steps": [
        {"title": "起点", "narration": "先看已知条件", "page": 1, "column": 1,
         "operations": [{"kind": "text", "content": "已知 x=2", "items": [], "language": ""}]},
        {"title": "下一步", "narration": "再代入表达式", "page": 1, "column": 1,
         "operations": [{"kind": "formula", "content": "x+1=3", "items": [], "language": ""}]},
    ]}}


class AssistanceStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hyperknow-assistance-storage-")
        self.path = Path(self.directory.name) / "hyperknow.sqlite3"
        self.db = Database(self.path)
        self.sequence = 0

    def tearDown(self):
        self.directory.cleanup()

    def command(self):
        self.sequence += 1
        return f"assistance-command-{self.sequence}"

    def conversation(self):
        return self.db.create_assistance_conversation(self.command())

    def turn(self, conversation, **changes):
        body = {"client_command_id": self.command(), "expected_version": conversation["version"],
                "text": "解释这个概念", "action": "message", **changes}
        return self.db.assistance_turn(conversation["conversation_id"], body, "original-model", True,
                                       {"catalog": [{"name": "original-skill", "body": "original-body"}]})

    def cancel(self, run):
        def change(current):
            current.update(status="cancelled", error=None)
            return current
        return self.db.mutate_command(self.command(), run["run_id"], run["version"],
                                      {"action": "cancel"}, change)

    def ready_board(self):
        conversation = self.turn(self.conversation(), text="用白板分步推导")
        run_id = conversation["active_run"]["run_id"]
        self.db.transition(run_id, {"queued"}, status="generating")
        self.db.finish_assistance(run_id, response_result(board_draft()))
        conversation = self.db.get_assistance_conversation(conversation["conversation_id"])
        return conversation, conversation["turns"][-1]["artifacts"][0]

    def test_v3_migration_is_additive_reopen_preserves_conversation_and_receipt(self):
        conversation = self.conversation()
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT count(*) FROM assistance_artifacts").fetchone()[0], 0)
        reopened = Database(self.path)
        self.assertEqual(reopened.get_assistance_conversation(conversation["conversation_id"]), conversation)
        self.assertEqual(reopened.create_assistance_conversation("assistance-command-1"), conversation)
        self.assertEqual(len(reopened.list_assistance_conversations()), 1)

    def test_user_text_is_frozen_without_keyword_derived_artifact_constraints(self):
        texts = ["我看不懂这个白板，请重新生成白板讲解。", "我不懂动画原理，请生成一个动画讲解。",
                 "不要闪卡、测验、白板、动画或图解。", "用白板讲解", "不要动画，请生成动画。"]
        for text in texts:
            with self.subTest(text=text):
                conversation = self.turn(self.conversation(), text=text)
                run = conversation["active_run"]
                self.assertEqual(run["input"]["text"], text)
                self.assertNotIn("requested_artifacts", run["input"])
                self.assertNotIn("forbidden_artifacts", run["input"])
                self.assertEqual(Database(self.path).get_run(run["run_id"])["input"], run["input"])

    def test_text_reply_can_commit_without_a_keyword_derived_artifact_requirement(self):
        conversation = self.turn(self.conversation(), text="我看不懂这个白板，请重新生成白板讲解。")
        run = conversation["active_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_assistance(run["run_id"], response_result())
        turn = Database(self.path).get_assistance_conversation(conversation["conversation_id"])["turns"][0]
        self.assertEqual(turn["status"], "ready")
        self.assertEqual(turn["artifacts"], [])

    def test_historical_flags_do_not_override_artifact_commit_or_change_frozen_input(self):
        conversation = self.turn(self.conversation(), text="我看不懂这个白板，请重新生成白板讲解。")
        run = conversation["active_run"]
        frozen = {**run["input"], "requested_artifacts": ["quiz"], "forbidden_artifacts": ["whiteboard"]}
        self.db.transition(run["run_id"], {"queued"}, status="generating", input=frozen)
        self.db.finish_assistance(run["run_id"], response_result(board_draft()))
        reopened = Database(self.path)
        turn = reopened.get_assistance_conversation(conversation["conversation_id"])["turns"][0]
        self.assertEqual(turn["status"], "ready")
        self.assertEqual([a["kind"] for a in turn["artifacts"]], ["whiteboard"])
        self.assertEqual(reopened.get_run(run["run_id"])["input"], frozen)

    def test_existing_v3_database_gains_tables_without_replacing_old_data(self):
        run = self.db.create_run(self.command(), "学习迭代器", "original-model")
        with self.db.transaction() as conn:
            conn.execute("DROP TABLE assistance_artifacts")
            conn.execute("DROP TABLE assistance_conversations")
        reopened = Database(self.path)
        self.assertEqual(reopened.get_run(run["run_id"]), run)
        self.assertEqual(reopened.list_assistance_conversations(), [])
        with reopened.transaction() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_concurrent_turns_are_serialized_by_real_database_transaction(self):
        conversation = self.conversation()
        commands = [self.command(), self.command()]
        def create(command_id):
            try:
                return self.db.assistance_turn(conversation["conversation_id"], {
                    "client_command_id": command_id, "expected_version": conversation["version"],
                    "text": "并发请求", "action": "message"}, "model", True, {})
            except AppError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, commands))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn("version_conflict", results)
        self.assertEqual(len(self.db.list_records("runs")), 1)

    def test_missing_model_does_not_prevent_creation_or_leave_partial_turn(self):
        conversation = self.conversation()
        body = {"client_command_id": self.command(), "expected_version": 1, "text": "解释极限",
                "action": "message"}
        with self.assertRaises(AppError) as failure:
            self.db.assistance_turn(conversation["conversation_id"], body, "model", False, {})
        self.assertEqual(failure.exception.code, "model_not_configured")
        self.assertEqual(self.db.get_assistance_conversation(conversation["conversation_id"]), conversation)
        self.assertEqual(self.db.list_records("runs"), [])

    def test_turn_idempotency_version_and_one_inflight(self):
        conversation = self.conversation()
        body = {"client_command_id": self.command(), "expected_version": 1, "text": "解释极限",
                "action": "message"}
        created = self.db.assistance_turn(conversation["conversation_id"], body, "model", True, {})
        replay = self.db.assistance_turn(conversation["conversation_id"], body, "different-model", False, {})
        self.assertEqual(replay, created)
        self.assertEqual(created["turns"][0]["status"], "queued")
        self.assertEqual(created["active_run"]["kind"], "assistance")
        self.assertIsNone(created["active_run"]["course_id"])
        for patch, code in (({"text": "other"}, "command_conflict"),
                            ({"client_command_id": self.command()}, "version_conflict"),
                            ({"client_command_id": self.command(), "expected_version": created["version"]},
                             "conversation_active")):
            with self.assertRaises(AppError) as failure:
                self.db.assistance_turn(conversation["conversation_id"], {**body, **patch}, "model", True, {})
            self.assertEqual(failure.exception.code, code)
        self.assertEqual(len(self.db.list_records("runs")), 1)

    def test_cancel_retry_keeps_turn_input_model_and_rejects_late_predecessor(self):
        conversation = self.turn(self.conversation())
        parent = conversation["active_run"]
        self.db.transition(parent["run_id"], {"queued"}, status="generating")
        parent = self.cancel(self.db.get_run(parent["run_id"]))
        stopped = self.db.get_assistance_conversation(conversation["conversation_id"])
        self.assertIsNone(stopped["active_run"])
        self.assertEqual(stopped["turns"][0]["status"], "cancelled")
        retried = self.db.retry_run(self.command(), parent["run_id"], parent["version"], configured=True)
        self.assertEqual(retried["input"], parent["input"])
        self.assertEqual(retried["model"], parent["model"])
        self.assertEqual(retried["turn_id"], parent["turn_id"])
        self.assertEqual(retried["parent_run_id"], parent["run_id"])
        self.assertIsNone(self.db.finish_assistance(parent["run_id"], response_result()))
        # Even a generic late metadata update cannot replace the successor.
        self.db.transition(parent["run_id"], {"cancelled"}, usage={"total_tokens": 12})
        current = self.db.get_assistance_conversation(conversation["conversation_id"])
        self.assertEqual(current["active_run"]["run_id"], retried["run_id"])
        self.assertEqual(len(current["turns"]), 1)
        with self.assertRaises(AppError):
            self.db.retry_run(self.command(), parent["run_id"], parent["version"] + 1, configured=True)

    def test_retry_is_only_available_for_latest_turn_and_never_ready(self):
        first = self.turn(self.conversation())
        cancelled = self.cancel(first["active_run"])
        current = self.db.get_assistance_conversation(first["conversation_id"])
        next_turn = self.turn(current, text="改问另一个问题")
        next_cancelled = self.cancel(next_turn["active_run"])
        with self.assertRaises(AppError) as failure:
            self.db.retry_run(self.command(), cancelled["run_id"], cancelled["version"], configured=True)
        self.assertEqual(failure.exception.code, "state_conflict")
        retry = self.db.retry_run(self.command(), next_cancelled["run_id"], next_cancelled["version"], configured=True)
        self.db.transition(retry["run_id"], {"queued"}, status="generating")
        ready = self.db.finish_assistance(retry["run_id"], response_result())
        with self.assertRaises(AppError):
            self.db.retry_run(self.command(), ready["run_id"], ready["version"], configured=True)

    def test_older_turn_metadata_cannot_clear_the_newer_turn_active_run(self):
        conversation = self.turn(self.conversation())
        first_id = conversation["active_run"]["run_id"]
        self.db.transition(first_id, {"queued"}, status="generating")
        self.db.finish_assistance(first_id, response_result())
        conversation = self.turn(self.db.get_assistance_conversation(conversation["conversation_id"]))
        self.db.transition(first_id, {"ready"}, usage={"total_tokens": 9})
        self.assertEqual(self.db.get_assistance_conversation(conversation["conversation_id"]), conversation)

    def test_continue_requires_a_saved_pending_plan_and_is_idempotent(self):
        conversation = self.conversation()
        with self.assertRaises(AppError) as failure:
            self.turn(conversation, action="continue", text="")
        self.assertEqual(failure.exception.code, "invalid_continuation")
        self.assertEqual(self.db.list_records("runs"), [])
        conversation = self.turn(conversation)
        run_id = conversation["active_run"]["run_id"]
        self.db.transition(run_id, {"queued"}, status="generating")
        result = response_result()
        result["response"].update(plan=["定义", "计算"], waiting_for="continue")
        self.db.finish_assistance(run_id, result)
        conversation = self.db.get_assistance_conversation(conversation["conversation_id"])
        body = {"client_command_id": self.command(), "expected_version": conversation["version"],
                "text": "", "action": "continue"}
        created = self.db.assistance_turn(conversation["conversation_id"], body, "model", True, {})
        self.assertEqual(created["turns"][-1]["action"], "continue")
        self.assertEqual(self.db.assistance_turn(conversation["conversation_id"], body, "model", True, {}), created)

    def test_explicit_suggestion_action_uses_authoritative_next_step_without_a_skill(self):
        from hyperknow.assistance_generation import validate_teaching
        import json
        conversation = self.turn(self.conversation())
        run_id = conversation["active_run"]["run_id"]
        self.db.transition(run_id, {"queued"}, status="generating")
        result = response_result()
        result["response"].update(plan=["定义", "例子"], waiting_for="continue", suggestions=[
            {"label": "看个例子", "text": "用数值说明", "action": "continue"}])
        self.db.finish_assistance(run_id, result)
        conversation = self.db.get_assistance_conversation(conversation["conversation_id"])
        suggestion = conversation["turns"][-1]["response"]["suggestions"][0]
        continued = self.turn(conversation, text=suggestion["text"], action=suggestion["action"])
        run = continued["active_run"]
        expected = run["input"]["continuation_state"]
        self.assertEqual(expected, {"plan": ["定义", "例子"], "current_step": 1, "is_last_step": True})
        with self.assertRaises(ValueError):
            validate_teaching(json.dumps(result["response"]), expected)
        final = response_result()
        final["response"].update(plan=expected["plan"], current_step=1, suggestions=[])
        validated = validate_teaching(json.dumps(final["response"]), expected)
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_assistance(run["run_id"], {**final, "response": validated.model_dump()})
        saved = self.db.get_assistance_conversation(conversation["conversation_id"])
        self.assertEqual(saved["turns"][-1]["status"], "ready")
        self.assertEqual(saved["turns"][-1]["skill_uses"], [])

    def test_large_saved_turn_cannot_remove_authoritative_continuation_state(self):
        conversation = self.turn(self.conversation(), text="问" * 12000)
        run_id = conversation["active_run"]["run_id"]
        self.db.transition(run_id, {"queued"}, status="generating")
        result = response_result()
        result["response"].update(text="答" * 12000, plan=["定义", "计算"], waiting_for="continue")
        self.db.finish_assistance(run_id, result)
        conversation = self.db.get_assistance_conversation(conversation["conversation_id"])
        continued = self.turn(conversation, action="continue", text="")
        inputs = continued["active_run"]["input"]
        self.assertEqual(inputs["history"], [])
        self.assertTrue(inputs["history_truncated"])
        self.assertEqual(inputs["continuation_state"], {"plan": ["定义", "计算"], "current_step": 1, "is_last_step": True})
        from hyperknow.assistance_generation import continuation_state
        self.assertEqual(continuation_state(inputs), inputs["continuation_state"])

    def test_restart_interrupts_turn_and_releases_active_run_without_new_call(self):
        conversation = self.turn(self.conversation())
        run_id = conversation["active_run"]["run_id"]
        self.db.transition(run_id, {"queued"}, status="generating")
        self.db.record_call(run_id, {"status": "started", "usage": None})
        self.db.interrupt_inflight()
        reopened = Database(self.path)
        snapshot = reopened.get_assistance_conversation(conversation["conversation_id"])
        self.assertIsNone(snapshot["active_run"])
        self.assertEqual(snapshot["turns"][0]["status"], "interrupted")
        self.assertEqual(snapshot["turns"][0]["error"]["code"], "interrupted")
        self.assertIsNone(reopened.finish_assistance(run_id, response_result()))
        self.assertEqual(len(reopened.calls(run_id)), 1)

    def test_finish_is_atomic_materializes_ids_and_steps_and_recovers(self):
        conversation, artifact = self.ready_board()
        self.assertIsNone(conversation["active_run"])
        turn = conversation["turns"][-1]
        self.assertEqual(turn["status"], "ready")
        self.assertEqual(artifact["turn_id"], turn["turn_id"])
        self.assertEqual(artifact["data"]["cursor"], -1)
        self.assertEqual(len({s["step_id"] for s in artifact["data"]["steps"]}), 2)
        self.assertEqual(Database(self.path).get_assistance_artifact(artifact["artifact_id"]), artifact)
        self.assertIsNone(self.db.finish_assistance(turn["run_id"], response_result(board_draft())))
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM assistance_artifacts").fetchone()[0], 1)

    def test_each_artifact_kind_persists_but_one_turn_holds_only_one(self):
        html = "<main>unique-animation-source</main>"
        drafts = [board_draft(),
            {"kind": "animation", "title": "动画", "data": {"html": html}},
            {"kind": "flashcards", "title": "卡片", "data": {
                "cards": [{"question": "什么是迭代器？", "answer": "实现逐项访问约定的对象。"}]}},
            {"kind": "quiz", "title": "测验", "data": {"questions": [{
                "question_id": "q1", "question": "哪个调用获取下一项？",
                "options": [{"id": "a", "text": "next"}, {"id": "b", "text": "len"}],
                "correct_ids": ["a"], "explanation": "next向迭代器请求下一项。"}]}},
            {"kind": "diagram", "title": "流程", "data": {"source": "flowchart LR\n  A-->B", "caption": "两步流程"}}]
        conversation = self.turn(self.conversation())
        for draft in drafts:
            run_id = conversation["active_run"]["run_id"]
            self.db.transition(run_id, {"queued"}, status="generating")
            self.db.finish_assistance(run_id, response_result(draft))
            conversation = self.db.get_assistance_conversation(conversation["conversation_id"])
            persisted = conversation["turns"][-1]["artifacts"]
            self.assertEqual([a["kind"] for a in persisted], [draft["kind"]])
            self.assertEqual(self.db.get_assistance_artifact(persisted[0]["artifact_id"]), persisted[0])
            if draft["kind"] != "diagram":
                conversation = self.turn(conversation, text="下一件事")
        next_turn = self.turn(conversation, text="这些产物有什么区别？")
        context = next_turn["active_run"]["input"]
        # Only summaries enter history; a full animation body never does.
        self.assertNotIn("unique-animation-source", str(context))
        self.assertTrue(context["history"])
        quiz = next(a for a in conversation["turns"][-2]["artifacts"] if a["kind"] == "quiz")
        with self.assertRaises(AppError) as failure:
            self.db.assistance_progress(quiz["artifact_id"], {"client_command_id": self.command(),
                                                             "expected_version": 1, "cursor": 0})
        self.assertEqual(failure.exception.code, "artifact_conflict")

    def test_a_second_artifact_in_one_turn_is_rejected_without_saving_either(self):
        conversation = self.turn(self.conversation())
        run_id = conversation["active_run"]["run_id"]
        self.db.transition(run_id, {"queued"}, status="generating")
        with self.assertRaises(AppError) as failure:
            self.db.finish_assistance(run_id, response_result(board_draft(), board_draft()))
        self.assertEqual(failure.exception.code, "artifact_limit")
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM assistance_artifacts").fetchone()[0], 0)

    def test_course_deletion_preserves_independent_conversation_artifacts_and_model_calls(self):
        conversation, artifact = self.ready_board()
        assistance_run_id = conversation["turns"][0]["run_id"]
        self.db.record_call(assistance_run_id, {"kind": "assistance", "usage": {"total_tokens": 5}})
        conversation = self.turn(conversation, text="继续解释这个概念")
        course_run = self.db.create_run(self.command(), "学习协程", "course-model")
        self.db.transition(course_run["run_id"], {"queued"}, status="generating")
        completed = self.db.finish_course(course_run["run_id"], CourseDraft.model_validate(course_data()))
        course = self.db.get_course(completed["course_id"])
        self.db.delete_course(course["course_id"], {"client_command_id": self.command(),
                                                    "expected_version": course["version"]})
        self.assertEqual(self.db.get_assistance_conversation(conversation["conversation_id"]), conversation)
        self.assertEqual(self.db.get_assistance_artifact(artifact["artifact_id"]), artifact)
        self.assertEqual(len(self.db.calls(assistance_run_id)), 1)
        self.assertEqual(self.db.get_run(assistance_run_id)["status"], "ready")

    def test_invalid_completion_rolls_back_all_artifacts(self):
        conversation = self.turn(self.conversation(), text="用白板分步推导")
        run_id = conversation["active_run"]["run_id"]
        self.db.transition(run_id, {"queued"}, status="generating")
        bad = copy.deepcopy(board_draft())
        bad["data"]["steps"][0]["operations"][0]["content"] = ""
        with self.assertRaises(ValueError):
            self.db.finish_assistance(run_id, response_result(board_draft(), bad))
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM assistance_artifacts").fetchone()[0], 0)
        current = self.db.get_assistance_conversation(conversation["conversation_id"])
        self.assertIsNone(current["turns"][0]["response"])
        self.assertEqual(current["turns"][0]["artifacts"], [])

    def test_whiteboard_progress_versions_idempotency_and_pending_question_context(self):
        conversation, artifact = self.ready_board()
        aid = artifact["artifact_id"]
        body = {"client_command_id": self.command(), "expected_version": 1, "cursor": 0}
        progressed = self.db.assistance_progress(aid, body)
        self.assertEqual(progressed["version"], 2)
        self.assertEqual(self.db.assistance_progress(aid, body), progressed)
        question = self.turn(self.db.get_assistance_conversation(conversation["conversation_id"]),
                             artifact_id=aid, text="为什么这一步成立？")
        context = question["active_run"]["input"]
        self.assertEqual(context["whiteboard"]["steps"], progressed["data"]["steps"][:1])
        self.assertNotIn("下一步", str(context))
        self.assertEqual(context["history"][0]["artifacts"], [
            {key: artifact[key] for key in ("artifact_id", "kind", "title")}])
        self.assertFalse(context["history_truncated"])
        stay = self.db.assistance_progress(aid, {"client_command_id": self.command(),
                                                "expected_version": 2, "cursor": 0})
        self.assertEqual(stay["version"], 2)
        with self.assertRaises(AppError) as failure:
            self.db.assistance_progress(aid, {"client_command_id": self.command(),
                                             "expected_version": 2, "cursor": 1})
        self.assertEqual(failure.exception.code, "question_active")
        cancelled = self.cancel(question["active_run"])
        next_step = self.db.assistance_progress(aid, {"client_command_id": self.command(),
                                                     "expected_version": 2, "cursor": 1})
        self.assertEqual(next_step["data"]["cursor"], 1)
        for cursor, code in ((-1, "invalid_cursor"), (2, "invalid_cursor")):
            with self.assertRaises(AppError) as failure:
                self.db.assistance_progress(aid, {"client_command_id": self.command(),
                                                 "expected_version": 3, "cursor": cursor})
            self.assertEqual(failure.exception.code, code)
        with self.assertRaises(AppError) as failure:
            self.db.assistance_progress(aid, {"client_command_id": self.command(),
                                             "expected_version": 2, "cursor": 1})
        self.assertEqual(failure.exception.code, "version_conflict")
        retried = self.db.retry_run(self.command(), cancelled["run_id"], cancelled["version"], configured=True)
        self.assertEqual(retried["input"], question["active_run"]["input"])
        self.assertEqual(retried["input"]["whiteboard"]["cursor"], 0)
        self.assertEqual(len(retried["input"]["whiteboard"]["steps"]), 1)

    def test_feedback_reopen_and_replay_keep_embedded_artifact_current(self):
        conversation, artifact = self.ready_board()
        for vote in ("up", "down"):
            body = {"client_command_id": self.command(), "expected_version": artifact["version"], "vote": vote}
            saved = self.db.assistance_feedback(artifact["artifact_id"], body)
            reopened = Database(self.path)
            snapshot = reopened.get_assistance_conversation(conversation["conversation_id"])
            self.assertEqual(snapshot["turns"][0]["artifacts"], [saved])
            self.assertEqual(snapshot["version"], conversation["version"])
            self.assertEqual(reopened.assistance_feedback(saved["artifact_id"], body), saved)
            self.assertEqual(reopened.get_assistance_artifact(saved["artifact_id"]), saved)
            same = reopened.assistance_feedback(saved["artifact_id"], {
                "client_command_id": self.command(), "expected_version": saved["version"], "vote": vote})
            self.assertEqual(same, saved)
            artifact = saved

    def test_foreign_whiteboard_is_rejected_and_steps_only_record_while_current(self):
        _, artifact = self.ready_board()
        other = self.conversation()
        with self.assertRaises(AppError) as failure:
            self.turn(other, artifact_id=artifact["artifact_id"])
        self.assertEqual(failure.exception.code, "artifact_conflict")
        conversation = self.turn(other)
        run = conversation["active_run"]
        self.assertIsNone(self.db.assistance_step(run["run_id"], {"kind": "tool"}))
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        stepped = self.db.assistance_step(run["run_id"], {"kind": "tool", "name": "get_skills"})
        self.assertEqual(stepped["steps"], [{"kind": "tool", "name": "get_skills"}])
        self.cancel(stepped)
        self.assertIsNone(self.db.assistance_step(run["run_id"], {"kind": "late"}))

    def test_saved_history_is_bounded_and_current_question_is_never_truncated(self):
        conversation = self.conversation()
        for index in range(14):
            conversation = self.turn(conversation, text=f"第 {index} 个问题")
            run_id = conversation["active_run"]["run_id"]
            self.db.transition(run_id, {"queued"}, status="generating")
            self.db.finish_assistance(run_id, response_result())
            conversation = self.db.get_assistance_conversation(conversation["conversation_id"])
        text = "当前问题" * 2000
        conversation = self.turn(conversation, text=text)
        context = conversation["active_run"]["input"]
        self.assertEqual(context["text"], text)
        self.assertEqual(len(context["history"]), 12)
        self.assertTrue(context["history_truncated"])
        self.assertEqual(context["history_selection"]["selected_turn_ids"],
                         [t["turn_id"] for t in conversation["turns"][-13:-1]])
