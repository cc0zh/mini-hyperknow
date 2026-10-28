"""Engineering contracts over real ASGI HTTP and SQLite, never model acceptance.

The actual CourseService is assembled but its worker is never started. Explicit
schema inputs exercise product commit functions; they are not provider outputs,
recorded model replies, or evidence that a paid generation succeeded.
"""

from copy import deepcopy
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest

import httpx

from eval_core.contracts import validate_case
from eval_core.runner import execute_trial

from hyperknow.config import Settings
from hyperknow.blueprint_domain import BlueprintDraft, UnitExpansionDraft
from hyperknow.domain import Clarification, CourseDraft
from hyperknow.eval_adapter import (ACTIONS, AdapterBlocked, HyperknowAdapter,
                                    ProtocolError, fixed_answers)
from hyperknow.eval_evidence import (export_fixture_manifest, readonly, records,
                                     snapshot_digest)
from hyperknow.lesson_domain import BoardScriptDraft
from hyperknow.main import create_app
from hyperknow.runtime import CourseService, EventHub
from hyperknow.research_domain import ResearchReport
from hyperknow.quiz_domain import QuizDraft
from hyperknow.storage import Database, encode
from tests.test_assistance_storage import board_draft, response_result
from tests.test_course import course_data, questions
from tests.test_research import page_input, read_step, report_input, search_step


def case(profile="assistance", steps=None, resources=None, **task):
    return {"schema_version": 2, "id": "engineering-adapter", "version": "1",
            "title": "HTTP/storage engineering inputs, not model acceptance", "tags": [],
            "task": {"profile": profile, "input": "解释协程暂停与恢复", **task},
            "prerequisites": {"resources": resources or {}}, "steps": steps or [],
            "capture": [], "limits": {}, "completion": {}}


class SyncASGITransport(httpx.BaseTransport):
    """Bridge actual httpx.ASGITransport, not a response/provider substitute."""

    def __init__(self, app):
        self.app = app

    def handle_request(self, request):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app)) as client:
                response = await client.send(request)
                await response.aread()
                return httpx.Response(response.status_code, headers=response.headers,
                                      content=response.content, request=request)
        return asyncio.run(send())


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hyperknow-eval-adapter-")
        self.directory = Path(self.temp.name)
        self.db = Database(self.directory / "hyperknow.sqlite3")
        settings = Settings(self.directory, api_key="engineering-unused-no-worker", model="engineering-model",
                            tavily_api_key="engineering-unused-no-worker")
        self.app = create_app(settings)
        hub = EventHub()
        self.service = CourseService(settings, self.db, hub)
        self.app.state.db, self.app.state.config = self.db, settings
        self.app.state.hub, self.app.state.service = hub, self.service
        # No context manager/lifespan: a real provider exists, but no model
        # worker/thread ever starts. Every request uses actual ASGITransport.
        self.client = httpx.Client(transport=SyncASGITransport(self.app), base_url="http://127.0.0.1")
        self.adapter = self.new_adapter()
        self.sequence = 0

    def tearDown(self):
        self.assertIsNone(self.service.worker)
        self.adapter.close()
        self.client.close()
        self.temp.cleanup()

    def new_adapter(self, manifest=None):
        return HyperknowAdapter("http://127.0.0.1", self.directory, client=self.client,
                                 fixture_manifest=manifest)

    def command(self):
        self.sequence += 1
        return f"engineering-command-{self.sequence}"

    def action(self, bindings, name, data=None):
        observation = self.adapter.observe(bindings)
        step = {"id": f"step_{self.sequence}", "action": name, "input": data or {}}
        return self.adapter.build_action(step, observation, bindings, self.command())

    def execute(self, bindings, name, data=None):
        action = self.action(bindings, name, data)
        return self.adapter.act(action), action

    def conversation(self, public=None):
        bindings = self.adapter.prepare(public or case())
        bindings, _ = self.execute(bindings, "conversation.create")
        return bindings

    def finish_turn(self, bindings, *, result=None):
        run_id = bindings["run_ids"][-1]
        self.db.transition(run_id, {"queued"}, status="generating")
        self.db.finish_assistance(run_id, result or response_result())

    def fixture_course(self, lesson=False):
        run = self.db.create_run(self.command(), "测试真实事务契约，不是模型输出", "engineering-model")
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        ready = self.db.finish_course(run["run_id"], CourseDraft.model_validate(course_data()))
        course = self.db.get_course(ready["course_id"])
        session = course["units"][0]["lectures"][0]["sessions"][0]["session_id"]
        exam = course["units"][0]["exams"][0]["exam_id"]
        producers = {run["run_id"]: run["run_id"]}
        if lesson:
            snapshot = self.db.prepare_lesson(session, self.command(), "engineering-model", True)
            lesson_run = snapshot["generation_run"]
            self.db.transition(lesson_run["run_id"], {"queued"}, status="generating")
            draft = BoardScriptDraft.model_validate({"title": "schema input", "steps": board_draft()["data"]["steps"]})
            self.db.finish_lesson(lesson_run["run_id"], draft)
            producers[lesson_run["run_id"]] = lesson_run["run_id"]
        bindings = {"course": {"kind": "course", "id": course["course_id"]},
                    "session": {"kind": "session", "id": session},
                    "exam": {"kind": "exam", "id": exam}}
        sources = {}
        with readonly(self.db.path) as conn:
            for table, rows in records(conn).items():
                if table == "command_receipts":
                    continue
                for row in rows:
                    if table == "runs":
                        source = row["id"]
                    elif table in {"lesson_states", "lesson_scripts"} and lesson:
                        source = lesson_run["run_id"]
                    else:
                        source = run["run_id"]
                    sources[f"{table}/{row['id']}"] = source
        manifest = export_fixture_manifest(self.directory, origin="engineering-transaction-snapshot",
                                            bindings=bindings, resource_sources=sources)
        path = self.directory / "fixture.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.adapter = self.new_adapter(path)
        return bindings, path

    def test_prepare_does_not_write_and_rejects_private_case(self):
        with readonly(self.db.path) as conn:
            before = snapshot_digest(conn)
        bindings = self.adapter.prepare(case(input={"text": "JSON task input"}))
        self.assertEqual(bindings["run_ids"], [])
        with readonly(self.db.path) as conn:
            self.assertEqual(snapshot_digest(conn), before)
        for private in ("checks", "reference_facts"):
            with self.assertRaises(ProtocolError):
                self.adapter.prepare({**case(), private: []})

    def test_single_turn_real_http_receipts_and_frozen_collect(self):
        bindings = self.conversation()
        bindings, action = self.execute(bindings, "assistance.message", {"text": "显式工程输入"})
        self.assertEqual(self.adapter.observe(bindings)["state"], "running")
        self.assertEqual(self.adapter.recover(action)["run_ids"], bindings["run_ids"])
        self.finish_turn(bindings)
        observation = self.adapter.observe(bindings)
        self.assertEqual((observation["state"], observation["outcome"]), ("terminal", "success"))
        self.assertIn("turn.saved", observation["checkpoints"])
        facts = self.adapter.collect(observation, bindings)
        self.assertEqual(set(facts), {"schema_version", "source", "runs", "calls", "resources", "artifacts",
                                     "turns", "checkpoints", "gaps", "observation", "actions"})
        self.assertEqual(facts["turns"][0]["run_id"], bindings["run_ids"][0])
        facts["turns"][0]["user_text"] = "local mutation"
        self.assertEqual(self.adapter.collect(observation, bindings)["turns"][0]["user_text"], "显式工程输入")
        self.assertEqual(observation["model_calls"], 0)
        self.assertEqual(observation["model_calls_coverage"], "saved_calls_only")

    def test_failed_turn_recovery_preserves_original_run_and_missing_output(self):
        bindings = self.conversation()
        bindings, action = self.execute(bindings, "assistance.message", {"text": "失败恢复工程输入"})
        run_id = bindings["run_ids"][0]
        self.db.transition(run_id, {"queued"}, status="failed")
        observation = self.adapter.observe(bindings)
        self.assertEqual((observation["state"], observation["outcome"]), ("terminal", "failed"))
        facts = self.adapter.collect(observation, bindings)
        self.assertEqual(facts["runs"][run_id]["run_id"], run_id)
        self.assertEqual(facts["runs"][run_id]["status"], "failed")
        self.assertIsNone(facts["turns"][0]["response"])
        with readonly(self.db.path) as conn:
            original = snapshot_digest(conn)
        self.assertEqual(self.adapter.recover(action)["run_ids"], [run_id])
        self.assertEqual(self.adapter.act(action)["run_ids"], [run_id])
        self.assertEqual(len(self.db.list_records("runs")), 1)
        with readonly(self.db.path) as conn:
            self.assertEqual(snapshot_digest(conn), original)

    def test_unknown_in_flight_is_never_resent(self):
        bindings = self.conversation()
        action = self.action(bindings, "assistance.message", {"text": "尚未发送"})
        self.assertIsNone(self.adapter.recover(action))
        action["status"] = "in_flight"
        with self.assertRaisesRegex(AdapterBlocked, "never resend"):
            self.adapter.act(action)
        self.assertEqual(self.db.get_assistance_conversation(bindings["refs"]["conversation"]["id"])["turns"], [])

    def test_duplicate_act_recovers_without_post_and_fingerprint_is_exact(self):
        bindings = self.conversation()
        bindings, action = self.execute(bindings, "assistance.message", {"text": "只保存一次"})
        self.assertEqual(self.adapter.act(action)["run_ids"], bindings["run_ids"])
        self.assertEqual(len(self.db.list_records("runs")), 1)
        with self.db.transaction() as conn:
            conn.execute("UPDATE command_receipts SET fingerprint=? WHERE id=?", ("wrong", action["command_id"]))
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.adapter.recover(action)

    def test_recovery_rejects_retry_replacement_and_receipt_rollback(self):
        bindings = self.conversation()
        bindings, action = self.execute(bindings, "assistance.message", {"text": "原轮次"})
        bindings, _ = self.execute(bindings, "run.cancel")
        original = self.db.get_run(bindings["run_ids"][0])
        self.db.retry_run(self.command(), original["run_id"], original["version"], configured=True)
        with self.assertRaisesRegex(ProtocolError, "retried|replacement|retry"):
            self.adapter.recover(action)
        with self.assertRaisesRegex(ProtocolError, "retry|replacement"):
            self.adapter.observe(bindings)

    def test_generating_cancel_does_not_claim_worker_settlement(self):
        bindings = self.conversation()
        bindings, _ = self.execute(bindings, "assistance.message")
        run_id = bindings["run_ids"][-1]
        self.db.transition(run_id, {"queued"}, status="generating")
        bindings, _ = self.execute(bindings, "run.cancel")
        observation = self.adapter.observe(bindings)
        self.assertEqual(self.db.get_run(run_id)["status"], "cancelled")
        self.assertEqual(observation["state"], "blocked")
        self.assertIn("execution_settlement_unverified", observation["error"])
        self.assertIn("run.terminal", observation["checkpoints"])

    def test_known_receipt_disappearance_and_run_version_rollback(self):
        bindings = self.conversation()
        bindings, action = self.execute(bindings, "assistance.message")
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM command_receipts WHERE id=?", (action["command_id"],))
        with self.assertRaisesRegex(ProtocolError, "rollback"):
            self.adapter.preflight(case(), bindings)

    def test_receipt_does_not_allow_immutable_run_input_change(self):
        bindings = self.conversation()
        bindings, _ = self.execute(bindings, "assistance.message", {"text": "原始固定输入"})
        run = self.db.get_run(bindings["run_ids"][-1])
        run["input"]["text"] = "被替换的输入"
        with self.db.transaction() as conn:
            conn.execute("UPDATE runs SET data=? WHERE id=?", (encode(run), run["run_id"]))
        with self.assertRaisesRegex(ProtocolError, "identity/input"):
            self.adapter.observe(bindings)

    def test_arbitrary_path_or_body_edit_is_rejected_before_http(self):
        bindings = self.conversation()
        action = self.action(bindings, "assistance.message")
        for key, value in (("url", "http://example.com"), ("path", "/api/runs/unknown/retry"),
                           ("body", {"client_command_id": "different-command"})):
            changed = deepcopy(action)
            changed[key] = value
            with self.assertRaises(ProtocolError):
                self.adapter.act(changed)
        self.assertEqual(len(self.db.list_records("runs")), 0)

    def test_foreign_existing_data_is_not_accepted_as_fixture(self):
        self.db.create_assistance_conversation(self.command())
        with self.assertRaisesRegex(AdapterBlocked, "fixture manifest"):
            self.adapter.prepare(case())

    def test_foreign_writes_after_preflight_are_blocked(self):
        bindings = self.conversation()
        self.db.create_assistance_conversation("foreign-conversation-command")
        with self.assertRaisesRegex(ProtocolError, "unowned"):
            self.adapter.observe(bindings)

    def test_context_manager_does_not_close_injected_client(self):
        with self.new_adapter() as adapter:
            adapter.prepare(case())
        self.assertFalse(self.client.is_closed)

    def test_fixture_alias_binding_and_lesson_prepare_freshness(self):
        _, path = self.fixture_course()
        public = case("lesson", steps=[{"id": "prepare", "action": "lesson.prepare", "input": {"session": "session"}}],
                      resources={"session": {"kind": "session"}})
        bindings = self.adapter.prepare(public)
        bindings, action = self.execute(bindings, "lesson.prepare", {"session": "session"})
        self.assertEqual(action["receipt_payload"]["action"], "prepare")
        self.assertEqual(self.adapter.preflight(public, bindings), bindings["environment"])
        with self.new_adapter(path) as resumed:
            self.assertEqual(resumed.preflight(public, bindings), bindings["environment"])
            self.assertEqual(resumed.recover(action)["run_ids"], bindings["run_ids"])
        with self.assertRaises(ProtocolError):
            self.action(bindings, "lesson.prepare", {"session": "session"})

    def test_fixture_target_hash_and_inventory_must_match(self):
        _, path = self.fixture_course()
        manifest = json.loads(path.read_text())
        manifest["resources"][0]["sha256"] = "wrong"
        path.write_text(json.dumps(manifest))
        with self.new_adapter(path) as adapter:
            with self.assertRaisesRegex(AdapterBlocked, "hash"):
                adapter.prepare(case("lesson", resources={"session": {"kind": "session"}}))

    def test_old_lesson_is_input_but_not_new_prepare_output(self):
        self.fixture_course(lesson=True)
        public = case("lesson", steps=[{"id": "old", "action": "lesson.prepare", "input": {}}],
                      resources={"session": {"kind": "session"}})
        with self.assertRaisesRegex(AdapterBlocked, "generation history"):
            self.adapter.prepare(public)

    def test_lesson_cursor_and_question_use_progress_version(self):
        self.fixture_course(lesson=True)
        bindings = self.adapter.prepare(case("question", resources={"session": {"kind": "session"}}))
        observation = self.adapter.observe(bindings)
        snapshot = observation["resources"]["session"]["snapshot"]
        self.assertNotEqual(snapshot["version"], snapshot["progress"]["version"])
        action = self.action(bindings, "lesson.progress", {"cursor": "next"})
        self.assertEqual(action["body"]["expected_version"], snapshot["progress"]["version"])
        bindings = self.adapter.act(action)
        with self.assertRaisesRegex(ProtocolError, "one saved step"):
            self.action(bindings, "lesson.progress", {"cursor": 4})
        bindings, action = self.execute(bindings, "lesson.question", {"question": "为何会暂停？"})
        self.assertEqual(action["body"]["cursor"], 0)
        self.assertEqual(self.db.get_run(bindings["run_ids"][-1])["kind"], "question")
        self.assertEqual(self.adapter.observe(bindings)["state"], "running")

    def test_practice_requires_real_lesson_and_exam_uses_actual_target(self):
        fixture, _ = self.fixture_course()
        steps = [{"id": "quiz", "action": "quiz.prepare", "input": {"target_type": "practice", "target": "session"}}]
        with self.assertRaisesRegex(AdapterBlocked, "requires a real prerequisite lesson"):
            self.adapter.prepare(case("quiz", steps=steps, resources={"session": {"kind": "session"}}))
        public = case("quiz", steps=[{"id": "quiz", "action": "quiz.prepare", "input": {"target_type": "exam", "target": "exam"}}],
                      resources={"exam": {"kind": "exam"}})
        bindings = self.adapter.prepare(public)
        bindings, action = self.execute(bindings, "quiz.prepare", {"target_type": "exam", "target": "exam"})
        self.assertEqual(action["receipt_payload"]["target_id"], fixture["exam"]["id"])
        self.assertEqual(self.db.get_run(bindings["run_ids"][-1])["kind"], "quiz")

    def test_practice_uses_bound_session_and_real_saved_script(self):
        fixture, _ = self.fixture_course(lesson=True)
        steps = [{"id": "practice", "action": "quiz.prepare", "input": {"target_type": "practice", "target": "session"}}]
        public = case("quiz", steps=steps, resources={"session": {"kind": "session"}})
        bindings = self.adapter.prepare(public)
        bindings, action = self.execute(bindings, "quiz.prepare", {"target_type": "practice", "target": "session"})
        self.assertEqual(action["path"], f"/api/sessions/{fixture['session']['id']}/practice/prepare")
        run = self.db.get_run(bindings["run_ids"][-1])
        self.assertEqual(run["target_id"], fixture["session"]["id"])
        self.assertTrue(any(ref.startswith("script:") for ref in run["input"]["allowed_source_refs"]))

    def test_committed_artifact_not_tool_step_is_checkpoint(self):
        bindings = self.conversation()
        bindings, _ = self.execute(bindings, "assistance.message")
        run_id = bindings["run_ids"][-1]
        self.db.transition(run_id, {"queued"}, status="generating")
        self.db.assistance_step(run_id, {"tool": "create_whiteboard", "status": "ready"})
        observation = self.adapter.observe(bindings)
        self.assertNotIn("artifact.saved", observation["checkpoints"])
        self.db.finish_assistance(run_id, response_result(board_draft()))
        observation = self.adapter.observe(bindings)
        self.assertIn("artifact.saved", observation["checkpoints"])
        facts = self.adapter.collect(observation, bindings)
        self.assertEqual(len(facts["artifacts"]), 1)
        bindings, action = self.execute(bindings, "artifact.progress", {"cursor": "next"})
        self.assertEqual(action["body"]["cursor"], 0)
        with self.assertRaises(AdapterBlocked):
            self.adapter.collect(observation, bindings)

    def test_explicit_continuation_preserves_original_plan(self):
        bindings = self.conversation()
        bindings, _ = self.execute(bindings, "assistance.message")
        result = response_result()
        result["response"].update(plan=["先观察", "再推导"], current_step=0, waiting_for="continue")
        self.finish_turn(bindings, result=result)
        self.assertEqual(self.adapter.observe(bindings)["state"], "waiting")
        bindings, action = self.execute(bindings, "assistance.continue")
        run = self.db.get_run(bindings["run_ids"][-1])
        self.assertEqual(run["input"]["continuation_state"]["current_step"], 1)
        self.assertEqual(run["input"]["continuation_state"]["plan"], ["先观察", "再推导"])
        self.assertEqual(self.adapter.recover(action)["run_ids"], bindings["run_ids"])

    def test_zero_clarification_is_running_through_automatic_research(self):
        public = case("course", steps=[{"id": "create", "action": "course.create", "input": {"goal": "真实API工程检查"}}])
        bindings = self.adapter.prepare(public)
        bindings, _ = self.execute(bindings, "course.create", {"goal": "真实API工程检查"})
        run_id = bindings["run_ids"][-1]
        self.db.transition(run_id, {"queued"}, status="clarifying")
        self.db.finish_clarification(run_id, Clarification(questions=[]))
        observation = self.adapter.observe(bindings)
        self.assertEqual(observation["state"], "running")
        self.assertNotIn("course.answers", observation["actions"])
        self.assertNotIn("clarification.ready", observation["checkpoints"])
        self.assertEqual(observation["resources"]["run_" + run_id]["snapshot"]["stage"], "research")

    def test_fixed_clarification_and_skip_bind_real_question_ids(self):
        public = case("course", answer_policy={"mode": "fixed", "facts": "已有基础，每天30分钟"})
        bindings = self.adapter.prepare(public)
        bindings, _ = self.execute(bindings, "course.create", {"goal": "真实API工程检查"})
        run_id = bindings["run_ids"][-1]
        self.db.transition(run_id, {"queued"}, status="clarifying")
        self.db.finish_clarification(run_id, Clarification.model_validate({"questions": questions()}))
        action = self.action(bindings, "course.answers")
        self.assertEqual(action["body"]["answers"][0]["question_id"], questions()[0]["id"])
        self.assertEqual(action["body"]["answers"][0]["custom_text"], "已有基础，每天30分钟")
        self.adapter.act(action)

    def test_model_answerer_is_explicitly_blocked(self):
        with self.assertRaisesRegex(AdapterBlocked, "model answerer"):
            self.adapter.prepare(case(answer_policy={"mode": "model"}))

    def test_explicit_skip_policy_is_not_inferred_from_missing_facts(self):
        public = case("course", answer_policy={"mode": "skip"})
        bindings = self.adapter.prepare(public)
        bindings, _ = self.execute(bindings, "course.create", {"goal": "显式跳过工程检查"})
        run_id = bindings["run_ids"][-1]
        self.db.transition(run_id, {"queued"}, status="clarifying")
        self.db.finish_clarification(run_id, Clarification.model_validate({"questions": questions()}))
        bindings, action = self.execute(bindings, "course.answers")
        self.assertTrue(action["body"]["skip"])
        self.assertEqual(action["body"]["answers"], [])
        self.assertTrue(self.db.get_run(run_id)["skipped"])

    def test_research_json_input_preserves_original_context(self):
        public = case("research", input={"goal": "公开调研目标", "context": "公开背景资料"})
        bindings = self.adapter.prepare(public)
        bindings, action = self.execute(bindings, "research.create")
        self.assertEqual(action["body"]["context"], "公开背景资料")
        self.assertEqual(self.db.get_run(bindings["run_ids"][-1])["input"], public["task"]["input"])

    def test_blueprint_approval_binds_observed_version_and_committed_units(self):
        bindings = self.adapter.prepare(case("course"))
        bindings, _ = self.execute(bindings, "course.create", {"goal": "蓝图版本工程检查"})
        run_id = bindings["run_ids"][-1]
        self.db.transition(run_id, {"queued"}, status="clarifying")
        self.db.finish_clarification(run_id, Clarification(questions=[]))
        self.db.research_step(run_id, search_step())
        source = self.db.research_step(run_id, read_step(), page_input())
        self.db.finish_research(run_id, ResearchReport.model_validate(report_input(source["source_id"])))
        blueprint = {"title": "schema蓝图", "description": "纯事务输入，不是模型输出", "target_learner": "基础学习者",
                     "difficulty": "beginner", "tags": ["engineering"], "units": [{
                         "title": "一个单元", "description": "一步展开", "learning_objectives": ["认识暂停"],
                         "estimated_sessions": 1}]}
        self.db.finish_blueprint(run_id, BlueprintDraft.model_validate(blueprint))
        observation = self.adapter.observe(bindings)
        self.assertEqual(observation["state"], "waiting")
        self.assertIn("blueprint.awaiting", observation["checkpoints"])
        wrong = deepcopy(observation)
        for resource in wrong["resources"].values():
            if resource["kind"] == "course":
                resource["snapshot"]["blueprint_version"] += 1
        with self.assertRaisesRegex(ProtocolError, "blueprint version"):
            self.adapter.build_action({"id": "wrong", "action": "course.blueprint", "input": {"approve": True}},
                                      wrong, bindings, self.command())
        action = self.adapter.build_action({"id": "approve", "action": "course.blueprint", "input": {"approve": True}},
                                           observation, bindings, self.command())
        self.assertEqual(action["body"]["expected_version"], self.db.get_run(run_id)["version"])
        bindings = self.adapter.act(action)
        run = self.db.begin_unit(run_id)
        session = deepcopy(course_data()["units"][0]["lectures"][0]["sessions"][0])
        session["depths"] = ["intuition"]
        expansion = UnitExpansionDraft.model_validate({"lectures": [{"title": "schema讲座", "description": "纯结构输入",
                                                                    "sessions": [session]}]})
        self.db.finish_unit(run_id, run["current_unit_id"], expansion)
        final = self.adapter.observe(bindings)
        self.assertEqual(final["state"], "terminal")
        self.assertIn("course.ready", final["checkpoints"])
        self.assertIn("unit.saved:" + run["current_unit_id"], final["checkpoints"])
        self.assertEqual(self.adapter.collect(final, bindings)["runs"][run_id]["approved_blueprint_version"], 1)

    def test_preexisting_quiz_is_never_new_execution(self):
        fixture, path = self.fixture_course()
        exam = fixture["exam"]["id"]
        snapshot = self.db.prepare_quiz("exam", exam, self.command(), "engineering-model", True)
        run = snapshot["generation_run"]
        ref = run["input"]["allowed_source_refs"][0]
        quiz = {"title": "纯schema题组", "source_refs": [ref], "questions": []}
        for index, kind in enumerate(("single", "multiple", "boolean")):
            quiz["questions"].append({"question_id": f"q{index}", "kind": kind, "prompt": "纯结构校验输入？",
                                      "options": [{"id": "a", "text": "是"}, {"id": "b", "text": "否"}],
                                      "correct_option_ids": ["a", "b"] if kind == "multiple" else ["a"],
                                      "explanation": "此输入仅验证落库结构。", "source_refs": [ref]})
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_quiz(run["run_id"], QuizDraft.model_validate(quiz))
        prior = json.loads(path.read_text())
        sources = {f"{r['table']}/{r['id']}": r["source"]["run_id"] for r in prior["resources"]}
        with readonly(self.db.path) as conn:
            for table, rows in records(conn).items():
                if table != "command_receipts":
                    for row in rows:
                        sources.setdefault(f"{table}/{row['id']}", run["run_id"])
        manifest = export_fixture_manifest(self.directory, origin="engineering-old-quiz", bindings=fixture,
                                            resource_sources=sources)
        path.write_text(json.dumps(manifest))
        self.adapter = self.new_adapter(path)
        public = case("quiz", steps=[{"id": "quiz", "action": "quiz.prepare", "input": {"target": "exam"}}],
                      resources={"exam": {"kind": "exam"}})
        with self.assertRaisesRegex(AdapterBlocked, "generation history"):
            self.adapter.prepare(public)

    def test_search_configuration_is_checked_before_course_writes(self):
        self.app.state.config = Settings(self.directory, api_key="engineering-unused", model="engineering-model")
        public = case("course", steps=[{"id": "create", "action": "course.create", "input": {}}])
        with self.assertRaisesRegex(AdapterBlocked, "search configuration"):
            self.adapter.prepare(public)
        self.assertEqual(self.db.list_records("runs"), [])

    def test_resume_recovers_receipt_committed_before_bindings_were_saved(self):
        bindings = self.conversation()
        action = self.action(bindings, "assistance.message", {"text": "提交后客户端未存新bindings"})
        self.adapter.act(action)  # Simulate loss of the returned replacement bindings.
        with self.new_adapter() as resumed:
            self.assertEqual(resumed.preflight(bindings["case"], bindings), bindings["environment"])
            recovered = resumed.recover(action)
            self.assertEqual(len(recovered["run_ids"]), 1)
            self.assertEqual(resumed.observe(recovered)["state"], "running")

    def test_http_snapshot_cannot_redirect_away_from_isolated_origin(self):
        # An injected client's default origin is irrelevant: every request has
        # the validated explicit adapter URL, including read-only crosschecks.
        self.client.base_url = httpx.URL("https://example.invalid/ignored/")
        bindings = self.conversation()
        self.assertEqual(self.adapter.observe(bindings)["state"], "waiting")

    def test_execute_trial_conversation_completed_resume_has_no_new_business(self):
        value = case(steps=[{"id": "create", "action": "conversation.create", "input": {},
                            "when": {"state": ["preparing"]}, "optional": False,
                            "checkpoint": "conversation.created"}])
        value.update(checks=[], reference_facts=["private grading material"], capture=["conversation.created"])
        value["limits"] = {"wait_seconds": 3.0, "poll_seconds": 0.01}
        value = validate_case(value)
        output = self.directory / "trial-conversation"
        result = execute_trial(value, self.adapter, output, execute=True)
        self.assertEqual(result["stage"], "completed", result.get("error"))
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(len(result["evidence"]), 1)
        self.assertNotIn("reference_facts", result["actions"][0]["request"]["bindings"]["case"])
        with readonly(self.db.path) as conn:
            before = snapshot_digest(conn)
        original_bytes = (output / "result.json").read_bytes()
        with self.new_adapter() as resumed:
            self.assertEqual(execute_trial(value, resumed, output, resume=True), result)
        self.assertEqual((output / "result.json").read_bytes(), original_bytes)
        with readonly(self.db.path) as conn:
            self.assertEqual(snapshot_digest(conn), before)
        self.assertEqual(self.db.list_records("runs"), [])

    def test_execute_trial_two_turns_with_real_background_product_transactions(self):
        # This thread supplies explicit schema inputs to genuine commit methods.
        # It is not a model/provider implementation and does not make quality claims.
        stop = threading.Event()
        completed, errors = [], []

        def commit_schema_inputs():
            try:
                while not stop.is_set() and len(completed) < 2:
                    for run in self.db.list_records("runs"):
                        if run["kind"] == "assistance" and run["status"] == "queued":
                            self.db.transition(run["run_id"], {"queued"}, status="generating")
                            result = response_result()
                            result["response"]["text"] = "工程schema提交输入，不是模型输出"
                            self.db.finish_assistance(run["run_id"], result)
                            completed.append(run["run_id"])
                    stop.wait(0.01)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=commit_schema_inputs)
        worker.start()
        try:
            steps = [
                {"id": "create", "action": "conversation.create", "input": {},
                 "when": {"state": ["preparing"]}, "checkpoint": "conversation.created"},
                {"id": "first", "action": "assistance.message", "input": {"text": "第一轮工程输入"},
                 "when": {"state": ["waiting"], "action": "assistance.message"}, "checkpoint": "first.saved"},
                {"id": "second", "action": "assistance.message", "input": {"text": "第二轮工程输入"},
                 "when": {"state": ["terminal"], "action": "assistance.message"}, "checkpoint": "second.saved"},
            ]
            value = case(steps=steps)
            value.update(checks=[], reference_facts=[], capture=["turn.saved"])
            value["limits"] = {"wait_seconds": 5.0, "poll_seconds": 0.01}
            value = validate_case(value)
            result = execute_trial(value, self.adapter, self.directory / "trial-multiturn", execute=True)
            self.assertEqual(result["stage"], "completed", result.get("error"))
            self.assertEqual(len(result["actions"]), 3)
            self.assertEqual(len(result["bindings"]["run_ids"]), 2)
            self.assertEqual({step["status"] for step in result["steps"]}, {"settled"})
            self.assertEqual({t["user_text"] for t in result["evidence"][-1]["data"]["turns"]},
                             {"第一轮工程输入", "第二轮工程输入"})
            self.assertEqual(result["budget"]["model_calls_coverage"], "saved_calls_only")
        finally:
            stop.set()
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])


class AnswerPolicyTests(unittest.TestCase):
    def test_no_semantic_option_or_position_guessing(self):
        current = questions()
        current[0]["allow_custom"] = False
        with self.assertRaises(ProtocolError):
            fixed_answers(current, {"mode": "fixed", "facts": "会基础"})
        answer = fixed_answers(current, {"mode": "fixed", "rules": [{"question": current[0]["question"],
                                                                 "option_labels": ["会基础"]}]})
        self.assertEqual(answer[0]["option_ids"], ["basic"])
        current[0]["options"][1]["label"] = "changed"
        with self.assertRaises(ProtocolError):
            fixed_answers(current, {"rules": [{"question_id": current[0]["id"], "option_labels": ["会基础"]}]})

    def test_action_list_covers_declared_b01_b08_surface(self):
        self.assertEqual(len(ACTIONS), 13)
        self.assertNotIn("run.retry", ACTIONS)


if __name__ == "__main__":
    unittest.main()
