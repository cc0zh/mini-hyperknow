"""Direct teaching rules and real SQLite tool calls; not model substitutes."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest

from pydantic import ValidationError

from agent_core.context import ContextManager
from agent_core.compression import ContextBudgetExceeded
from agent_core.skills import SkillRegistry
from agent_core.tools.validation import validate
from agent_core.types import AgentContext, AssistantMessage, ToolCall, UserMessage
from hyperknow.assistance_domain import ArtifactDraft, TeachingResponse
from hyperknow.assistance_generation import (AssistantGenerator, build_skill_snapshots, inline_schema,
                                           continuation_state, validate_teaching, RecordedTeachingModel,
                                           CONTEXT_BUDGET, OUTPUT_RESERVE, TeachingContext, teaching_inputs)
from hyperknow.config import Settings
from hyperknow.domain import AppError
from hyperknow.storage import Database
from hyperknow.prompts.assistance import teaching_prompt
from hyperknow.assistance_generation import teaching_schema


def test_skill_snapshots():
    body = "A test-only specialized method; does not grant permissions."
    return {"test-skill": {"name": "test-skill", "description": "Method fixture", "version": "1",
                           "body": body, "sha256": sha256(body.encode()).hexdigest()}}


class SkillTests(unittest.TestCase):
    def test_empty_product_registry_is_valid_and_unknown_load_fails(self):
        self.assertEqual(build_skill_snapshots(), {})
        registry = SkillRegistry({})
        self.assertEqual(registry.catalog(), [])
        self.assertEqual(registry.snapshot(), {})
        self.assertEqual(SkillRegistry.from_directory(Path("unused-directory"), ()).snapshot(), {})
        with self.assertRaises(ValueError):
            registry.load("missing")
        for invalid in ([], None, {str(i): {} for i in range(13)}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                SkillRegistry(invalid)

    def test_product_catalog_discloses_metadata_not_body(self):
        registry = SkillRegistry(test_skill_snapshots())
        self.assertEqual({s["name"] for s in registry.catalog()}, {"test-skill"})
        for item in registry.catalog():
            self.assertNotIn("body", item)
            loaded = registry.load(item["name"])
            self.assertEqual(item["sha256"], sha256(loaded["body"].encode()).hexdigest())

    def test_snapshots_are_independent_and_digest_checked(self):
        snapshots = test_skill_snapshots()
        registry = SkillRegistry(snapshots)
        snapshots["test-skill"]["body"] = "changed"
        restored = SkillRegistry(registry.snapshot())
        self.assertNotEqual(restored.load("test-skill")["body"], "changed")
        with self.assertRaises(ValueError):
            SkillRegistry(snapshots)
        with self.assertRaises(ValueError):
            registry.load("../../private")

    def test_trusted_directory_allowlist_and_metadata_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "test-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("---\nname: test-skill\ndescription: test\nversion: 1\n---\nGuide", encoding="utf-8")
            registry = SkillRegistry.from_directory(root, ("test-skill",))
            self.assertEqual(registry.load("test-skill")["body"], "Guide")
            with self.assertRaises(ValueError):
                SkillRegistry.from_directory(root, ("../test-skill",))
            (skill / "SKILL.md").write_text("---\nname: other\ndescription: test\nversion: 1\n---\nGuide", encoding="utf-8")
            with self.assertRaises(ValueError):
                SkillRegistry.from_directory(root, ("test-skill",))


class TeachingSchemaTests(unittest.TestCase):
    def test_suggestions_require_explicit_valid_intent_and_pending_continue(self):
        pending = {"text": "定义", "plan": ["定义", "计算"], "waiting_for": "continue",
                   "suggestions": [{"label": "看计算", "text": "看计算示例", "action": "continue"}]}
        self.assertEqual(TeachingResponse.model_validate(pending).suggestions[0].action, "continue")
        for suggestion in ({"label": "继续", "text": "继续"},
                           {"label": "继续", "text": "继续", "action": "execute"}):
            with self.assertRaises(ValidationError):
                TeachingResponse.model_validate({**pending, "suggestions": [suggestion]})
        with self.assertRaises(ValidationError):
            TeachingResponse.model_validate({**pending, "waiting_for": "none"})
        ordinary = TeachingResponse(text="解释", suggestions=[{
            "label": "换个角度", "text": "继续解释同一步", "action": "message"}])
        self.assertEqual(ordinary.suggestions[0].action, "message")

    def test_prompt_keeps_policy_separate_and_skill_loading_optional(self):
        plain = teaching_prompt([], teaching_schema())
        specialized = teaching_prompt(SkillRegistry(test_skill_snapshots()).catalog(), teaching_schema())
        self.assertIn("当前没有可用Skill", plain)
        self.assertIn("不是回答或创建产物的前置条件", specialized)
        self.assertNotIn("skill_hint", plain)
        self.assertNotIn("requested_artifacts", plain)
        self.assertNotIn("forbidden_artifacts", plain)
        self.assertNotIn("首先调用get_skills", specialized)
        self.assertNotIn(test_skill_snapshots()["test-skill"]["body"], specialized)

    def test_continuation_keeps_saved_plan_and_requires_complete_envelope(self):
        previous = TeachingResponse(text="定义", plan=["定义", "计算"], waiting_for="continue").model_dump()
        expected = {"plan": previous["plan"], "current_step": 1, "is_last_step": True}
        self.assertEqual(expected, {"plan": ["定义", "计算"], "current_step": 1, "is_last_step": True})
        self.assertEqual(continuation_state({"action": "continue", "history": [], "continuation_state": expected}), expected)
        candidate = TeachingResponse(text="计算", plan=previous["plan"], current_step=1).model_dump()
        validate_teaching(json.dumps(candidate), expected)
        for patch in ({"plan": ["直觉", "计算"]}, {"current_step": 0}):
            with self.assertRaises(ValueError):
                validate_teaching(json.dumps({**candidate, **patch}), expected)
        with self.assertRaises(ValueError):
            validate_teaching('{"text":"only text"}', None)
        with self.assertRaises(AppError):
            continuation_state({"action": "continue", "history": []})
        with self.assertRaises(AppError):
            continuation_state({"action": "continue", "history": [{"response": previous}]})

    def test_response_wait_and_plan_are_consistent(self):
        good = {"text": "先认识复合函数", "plan": ["复合函数", "变化率"],
                "current_step": 0, "waiting_for": "continue"}
        self.assertEqual(TeachingResponse.model_validate(good).waiting_for, "continue")
        for change in ({"current_step": 2}, {"current_step": True}, {"plan": []},
                       {"waiting_for": "answer"}, {"questions": [{"question_id": "q", "question": "基础如何？"}]}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                TeachingResponse.model_validate({**good, **change})

    def test_quiz_answers_must_belong_to_unique_options(self):
        draft = {"kind": "quiz", "title": "复合函数", "data": {"questions": [{
            "question_id": "q1", "question": "哪个是内层函数？", "options": [
                {"id": "a", "text": "平方"}, {"id": "b", "text": "正弦"}],
            "correct_ids": ["a"], "explanation": "先平方再取正弦。"}]}}
        ArtifactDraft.model_validate(draft)
        for ids in ([], ["missing"], ["a", "a"]):
            data = deepcopy(draft)
            data["data"]["questions"][0]["correct_ids"] = ids
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                ArtifactDraft.model_validate(data)

    def test_board_is_ordered_and_does_not_accept_course_or_execution(self):
        step = {"title": "定义", "narration": "先理解定义", "page": 1, "column": 1,
                "operations": [{"object_id": "definition", "kind": "text", "content": "复合函数"}]}
        draft = {"kind": "whiteboard", "title": "复合函数", "data": {"steps": [step]}}
        self.assertEqual(ArtifactDraft.model_validate(draft).data["steps"][0]["page"], 1)
        for patch in ({"page": 2}, {"operations": [{"kind": "bash", "content": "noop"}]}):
            with self.assertRaises(ValidationError):
                ArtifactDraft.model_validate({**draft, "data": {"steps": [{**step, **patch}]}})
        with self.assertRaises(ValidationError):
            ArtifactDraft.model_validate({**draft, "course_id": "not-a-course"})

    def test_animation_and_flashcards_reject_blank_content(self):
        for draft in ({"kind": "animation", "title": "演示", "data": {"html": " "}},
                      {"kind": "flashcards", "title": "复习", "data": {"cards": []}},
                      {"kind": "flashcards", "title": "复习", "data": {"cards": [{"question": " ", "answer": "a"}]}}):
            with self.subTest(kind=draft["kind"]), self.assertRaises(ValidationError):
                ArtifactDraft.model_validate(draft)

    def test_local_schema_expansion_is_fail_closed(self):
        schema = inline_schema({"$defs": {"A": {"type": "string", "const": "a"}},
                                "type": "object", "properties": {"kind": {"$ref": "#/$defs/A"}}})
        validate({"kind": "a"}, schema)
        with self.assertRaises(ValueError):
            validate({"kind": "b"}, schema)
        with self.assertRaises(ValueError):
            inline_schema({"$ref": "https://invalid.example/schema"})


class TeachingToolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.directory.name) / "teaching.sqlite3")
        self.settings = Settings(Path(self.directory.name))
        self.conversation = self.db.create_assistance_conversation("create-rule-conversation")
        snapshot = self.db.assistance_turn(self.conversation["conversation_id"], {
            "client_command_id": "create-rule-turn", "expected_version": self.conversation["version"],
            "text": "解释复合函数", "action": "message"},
            "rule-input-model", True, test_skill_snapshots())
        run = self.db.transition(snapshot["active_run"]["run_id"], {"queued"}, status="generating")
        self.generator = AssistantGenerator(self.settings, self.db, Event())
        self.generator.run = run
        self.generator.registry = SkillRegistry(run["input"]["skill_snapshots"])
        from time import monotonic
        self.generator.deadline = monotonic() + 30
        self.tools = self.generator.tools()

    def tearDown(self):
        self.directory.cleanup()

    def _load(self):
        self.assertFalse(self.tools.execute(ToolCall("load-skill", "get_skills",
                                                     {"name": "test-skill"})).is_error)

    def test_output_budget_override_is_local_and_default_is_unchanged(self):
        experiment = AssistantGenerator(self.settings, self.db, Event(), output_reserve=16384)
        self.assertEqual(experiment.output_reserve, 16384)
        self.assertEqual(self.generator.output_reserve, 8192)
        self.assertEqual(OUTPUT_RESERVE, 8192)
        for invalid in (True, 0, -1, 1.5, "16384", CONTEXT_BUDGET):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                AssistantGenerator(self.settings, self.db, Event(), output_reserve=invalid)

    def test_all_teaching_providers_omit_output_caps_independently_of_context_reserve(self):
        from agent_core.llm.openai import completion_parameters
        for reserve in (8192, 16384):
            for endpoint in (None, "https://api.deepseek.com"):
                settings = Settings(Path(self.directory.name), api_key="local-construction-only",
                                    base_url=endpoint)
                generator = AssistantGenerator(settings, self.db, Event(), output_reserve=reserve)
                generator.run = self.generator.run
                with generator._provider() as provider:
                    self.assertIsNone(provider.max_output_tokens)
                    self.assertEqual(completion_parameters(provider.max_output_tokens, endpoint), {})
                    self.assertEqual(provider.client.max_retries, 0)
                self.assertEqual(generator.output_reserve, reserve)

    def test_model_input_ignores_legacy_intent_flags_without_rewriting_the_audit(self):
        frozen = {**self.generator.run["input"], "text": "我看不懂这个白板，请重新生成白板讲解。",
                  "requested_artifacts": ["quiz"], "forbidden_artifacts": ["whiteboard"]}
        original = deepcopy(frozen)
        inputs = teaching_inputs(frozen)
        self.assertEqual(inputs["text"], frozen["text"])
        for key in ("skill_snapshots", "requested_artifacts", "forbidden_artifacts"):
            self.assertNotIn(key, inputs)
        self.assertEqual(inputs["action"], frozen["action"])
        self.assertEqual(inputs["history"], frozen["history"])
        self.assertEqual(frozen, original)
        self.assertEqual(json.loads(json.dumps(inputs, ensure_ascii=False)), inputs)

    def test_context_guard_accounts_for_the_selected_output_reserve_before_calling(self):
        from agent_core.tokens import TokenEstimator
        context = AgentContext("budget boundary", [])
        estimated_input = TokenEstimator().estimate(context).input_tokens
        self.generator.output_reserve = CONTEXT_BUDGET - estimated_input + 1
        # No provider substitute is needed: the guard must reject before use.
        model = RecordedTeachingModel(None, self.generator)
        with self.assertRaises(AppError) as failure:
            model.complete(context)
        self.assertEqual(failure.exception.code, "context_too_large")
        self.assertEqual(model.calls, 0)
        self.assertEqual(self.db.calls(self.generator.run["run_id"]), [])

    def test_empty_registry_hides_loader_but_can_stage_and_commit_an_artifact(self):
        self.generator.registry = SkillRegistry({})
        tools = self.generator.tools()
        self.assertNotIn("get_skills", {t["function"]["name"] for t in tools.definitions()})
        created = tools.execute(ToolCall("card", "create_flashcards",
            {"title": "复习", "data": {"cards": [{"question": "问", "answer": "答"}]}}))
        self.assertFalse(created.is_error)
        self.assertEqual(self.generator.used, [])
        result = {"response": TeachingResponse(text="请翻卡复习。").model_dump(),
                  "artifacts": self.generator.artifacts, "skill_uses": self.generator.used}
        self.assertEqual(self.db.finish_assistance(self.generator.run["run_id"], result)["status"], "ready")
        turn = self.db.get_assistance_conversation(self.conversation["conversation_id"])["turns"][0]
        self.assertEqual(turn["skill_uses"], [])
        self.assertEqual(len(turn["artifacts"]), 1)

    def test_staged_animation_projection_fits_without_changing_audit_or_committed_html(self):
        html = "<!doctype html><html><body><p>" + "内层的输出成为外层的输入。" * 1800 + "</p></body></html>"
        call = ToolCall("large-animation", "create_animation", {"title": "复合函数", "data": {"html": html}})
        result = self.tools.execute(call)
        self.assertFalse(result.is_error)
        definitions = self.tools.definitions()
        baseline = ContextManager("教学", max_context_tokens=CONTEXT_BUDGET,
                                  reserve_output_tokens=OUTPUT_RESERVE, compression_threshold=1)
        projected = TeachingContext("教学", max_context_tokens=CONTEXT_BUDGET,
                                    reserve_output_tokens=OUTPUT_RESERVE, compression_threshold=1)
        messages = [UserMessage("只解释当前复合函数，不修改原计划。"),
                    AssistantMessage("", tool_calls=[call], stop_reason="tool_use"), result]
        for message in messages:
            baseline.append_message(message)
            projected.append_message(message)
        with self.assertRaises(ContextBudgetExceeded):
            baseline.prepare(definitions)
        context = projected.prepare(definitions)
        selected = context.messages[1].tool_calls[0]
        marker = selected.arguments["data"]["html"]
        self.assertIn("HTML omitted", marker)
        self.assertIn(sha256(html.encode("utf-8")).hexdigest(), marker)
        self.assertIn(f"utf8_bytes={len(html.encode('utf-8'))}", marker)
        self.assertEqual((selected.id, selected.name, selected.arguments["title"]),
                         (call.id, call.name, call.arguments["title"]))
        self.assertEqual(context.messages[0], messages[0])
        self.assertEqual(context.messages[-1], result)
        self.assertEqual(context, projected.prepare(definitions))
        self.assertEqual(projected.messages, messages)
        self.assertEqual(projected.audit_messages, messages)
        self.assertEqual(call.arguments["data"]["html"], html)
        self.db.finish_assistance(self.generator.run["run_id"], {
            "response": TeachingResponse(text="看内层输出如何作为外层输入。").model_dump(),
            "artifacts": self.generator.artifacts, "skill_uses": []})
        reopened = Database(self.db.path)
        saved = reopened.get_assistance_conversation(self.conversation["conversation_id"])
        self.assertEqual(saved["turns"][0]["artifacts"][0]["data"]["html"], html)

    def test_projection_preserves_failed_and_other_tools_and_requires_a_completed_pair(self):
        html = "<!doctype html><p>" + "复合函数" * 200 + "</p>"
        first = ToolCall("first-animation", "create_animation", {"title": "演示", "data": {"html": html}})
        duplicate = ToolCall("rejected-animation", "create_animation", deepcopy(first.arguments))
        diagram = ToolCall("rejected-diagram", "create_diagram", {
            "title": "关系", "data": {"source": "flowchart LR\n A-->B", "caption": "内层到外层"}})
        context = TeachingContext("教学")
        context.append_message(UserMessage("解释复合函数"))
        initial = context.get_context(self.tools.definitions())
        self.assertEqual(initial, AgentContext("教学", [UserMessage("解释复合函数")],
                                               self.tools.definitions()))
        context.append_message(AssistantMessage("", tool_calls=[first], stop_reason="tool_use"))
        with self.assertRaises(ValueError):
            context.get_context()
        self.assertEqual(context.messages[1].tool_calls[0].arguments["data"]["html"], html)
        context.append_message(self.tools.execute(first))
        for call in (duplicate, diagram):
            context.append_message(AssistantMessage("", tool_calls=[call], stop_reason="tool_use"))
            result = self.tools.execute(call)
            self.assertTrue(result.is_error)
            context.append_message(result)
        projected = context.get_context()
        self.assertIn("HTML omitted", projected.messages[1].tool_calls[0].arguments["data"]["html"])
        self.assertEqual(projected.messages[3].tool_calls[0], duplicate)
        self.assertEqual(projected.messages[5].tool_calls[0], diagram)

    def test_short_successful_animation_stays_verbatim(self):
        call = ToolCall("short-animation", "create_animation", {
            "title": "短演示", "data": {"html": "<p>内层 → 外层</p>"}})
        context = TeachingContext("教学")
        context.append_message(UserMessage("简单展示"))
        context.append_message(AssistantMessage("", tool_calls=[call], stop_reason="tool_use"))
        result = self.tools.execute(call)
        self.assertFalse(result.is_error)
        context.append_message(result)
        self.assertEqual(context.get_context().messages, context.messages)

    def test_trusted_skill_activation_is_recorded_once_and_does_not_grant_tools(self):
        self._load()
        self._load()
        self.assertEqual(len(self.generator.used), 1)
        self.assertEqual(self.generator.used[0]["sha256"], test_skill_snapshots()["test-skill"]["sha256"])
        steps = self.db.get_run(self.generator.run["run_id"])["steps"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["tool"], "get_skills")
        self.assertNotIn("read_file", {t["function"]["name"] for t in self.tools.definitions()})

    def test_legacy_intent_flags_are_not_artifact_tool_permissions(self):
        self.generator.run["input"].update(requested_artifacts=["quiz"], forbidden_artifacts=["flashcards"])
        result = self.tools.execute(ToolCall("card", "create_flashcards", {
            "title": "复习", "data": {"cards": [{"question": "问", "answer": "答"}]}}))
        self.assertFalse(result.is_error)
        self.assertEqual([a["kind"] for a in self.generator.artifacts], ["flashcards"])

    def test_one_artifact_per_turn_even_without_an_explicit_request(self):
        self.assertFalse(self.tools.execute(ToolCall("card", "create_flashcards",
                                                    {"title": "卡片", "data": {"cards": [{"question": "问", "answer": "答"}]}})).is_error)
        second = self.tools.execute(ToolCall("diagram", "create_diagram",
                                             {"title": "流程", "data": {"source": "flowchart LR\n A-->B", "caption": "两步"}}))
        self.assertTrue(second.is_error)
        self.assertEqual(len(self.generator.artifacts), 1)

    def test_only_trusted_teaching_tools_are_registered(self):
        names = {t["function"]["name"] for t in self.tools.definitions()}
        self.assertEqual(names, {"get_skills", "create_flashcards", "create_quiz", "create_whiteboard",
                                 "create_animation", "create_diagram"})
        for definition in self.tools.definitions():
            # Core validation rejects unsupported schema keywords before execution.
            schema = definition["function"]["parameters"]
            self.assertNotIn("$defs", json.dumps(schema))
            self.assertNotIn("$ref", json.dumps(schema))

    def test_optional_activation_and_staged_artifact_use_real_tools_and_disk(self):
        args = {"title": "复合函数", "data": {"cards": [{"question": "复合是什么？", "answer": "输出成为输入。"}]}}
        loaded = self.tools.execute(ToolCall("load-skill", "get_skills", {"name": "test-skill"}))
        self.assertFalse(loaded.is_error)
        created = self.tools.execute(ToolCall("create-card", "create_flashcards", args))
        self.assertFalse(created.is_error)
        self.assertEqual(len(self.generator.artifacts), 1)
        self.assertEqual(len(self.db.get_run(self.generator.run["run_id"])["steps"]), 2)
        self.assertFalse(self.db.get_assistance_conversation(self.conversation["conversation_id"])["turns"][0]["artifacts"])
        self.assertTrue(self.tools.execute(ToolCall("repeat", "create_flashcards", args)).is_error)

    def test_cancelled_tool_cannot_stage_new_content_or_make_calls(self):
        self.db.transition(self.generator.run["run_id"], {"generating"}, status="cancelled")
        with self.assertRaises(AppError):
            self.generator.require_active()
        result = self.tools.execute(ToolCall("after-cancel", "get_skills", {"name": "test-skill"}))
        self.assertTrue(result.is_error)
        self.assertEqual(self.db.calls(self.generator.run["run_id"]), [])


if __name__ == "__main__":
    unittest.main()
