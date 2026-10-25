"""Direct teaching rules and real SQLite tool calls; not model substitutes."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest

from pydantic import ValidationError

from agent_core.skills import SkillRegistry
from agent_core.tools.validation import validate
from agent_core.types import ToolCall
from hyperknow.assistance_domain import ArtifactDraft, TeachingResponse, forbidden_artifacts, requested_artifacts
from hyperknow.assistance_generation import (AssistantGenerator, build_skill_snapshots, inline_schema,
                                           continuation_state, validate_teaching)
from hyperknow.config import Settings
from hyperknow.domain import AppError
from hyperknow.storage import Database


class SkillTests(unittest.TestCase):
    def test_only_an_explicit_unnegated_request_keeps_the_artifact_guarantee(self):
        self.assertEqual(requested_artifacts("给我三道关于二分的自测题"), ["quiz"])
        self.assertEqual(requested_artifacts("做一组导数闪卡"), ["flashcards"])
        self.assertEqual(requested_artifacts("用白板分步讲二分查找"), ["whiteboard"])
        self.assertEqual(requested_artifacts("用流程图说明解析流程"), ["diagram"])
        self.assertEqual(requested_artifacts("不要闪卡，只要一道选择题"), ["quiz"])
        self.assertEqual(requested_artifacts("不要闪卡"), [])
        self.assertEqual(requested_artifacts("用通俗的方式讲解什么是导数"), [])
        # Talking about the artifact that already exists is not a request for
        # a new one; the real model produced this exact failure.
        self.assertEqual(requested_artifacts("请只解释当前白板第一步的含义，不生成新白板，不提前讲后面的步骤。"), [])
        self.assertEqual(requested_artifacts("这块白板上的第二步为什么要把 u 留住？"), [])
        self.assertEqual(requested_artifacts("上面的流程图里 F 节点是什么意思？"), [])
        self.assertEqual(forbidden_artifacts("请只解释当前白板第一步的含义，不生成新白板，不提前讲后面的步骤。"), ["whiteboard"])
        self.assertEqual(forbidden_artifacts("不要闪卡"), ["flashcards"])
        self.assertEqual(forbidden_artifacts("用通俗的方式讲解什么是导数"), [])
        # Kind is the model's decision; the reader never names two at once.
        self.assertEqual(requested_artifacts("先来闪卡再做一道自测题"), ["flashcards"])

    def test_product_catalog_discloses_metadata_not_body(self):
        registry = SkillRegistry(build_skill_snapshots())
        self.assertEqual({s["name"] for s in registry.catalog()}, {"concept-explanation", "problem-solving"})
        for item in registry.catalog():
            self.assertNotIn("body", item)
            loaded = registry.load(item["name"])
            self.assertEqual(item["sha256"], sha256(loaded["body"].encode()).hexdigest())

    def test_snapshots_are_independent_and_digest_checked(self):
        snapshots = build_skill_snapshots()
        registry = SkillRegistry(snapshots)
        snapshots["concept-explanation"]["body"] = "changed"
        restored = SkillRegistry(registry.snapshot())
        self.assertNotEqual(restored.load("concept-explanation")["body"], "changed")
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
    def test_continuation_keeps_saved_plan_and_requires_complete_envelope(self):
        previous = TeachingResponse(text="定义", plan=["定义", "计算"], waiting_for="continue").model_dump()
        expected = continuation_state({"action": "continue", "history": [{"response": previous}]})
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
                "operations": [{"kind": "text", "content": "复合函数"}]}
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
            "text": "解释复合函数", "action": "message", "skill_hint": "concept-explanation"},
            "rule-input-model", True, build_skill_snapshots())
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
                                                     {"name": "concept-explanation"})).is_error)

    def test_a_named_artifact_kind_is_the_only_kind_this_turn_may_create(self):
        conversation = self.db.create_assistance_conversation("requested-kind-conversation")
        turn = self.db.assistance_turn(conversation["conversation_id"], {
            "client_command_id": "requested-kind-turn", "expected_version": conversation["version"],
            "text": "给我三道关于二分的自测题", "action": "message", "skill_hint": "auto"},
            "rule-input-model", True, build_skill_snapshots())
        run = self.db.transition(turn["active_run"]["run_id"], {"queued"}, status="generating")
        generator = AssistantGenerator(self.settings, self.db, Event())
        generator.run = run
        generator.registry = SkillRegistry(run["input"]["skill_snapshots"])
        from time import monotonic
        generator.deadline = monotonic() + 30
        tools = generator.tools()
        self.assertFalse(tools.execute(ToolCall("load", "get_skills", {"name": "concept-explanation"})).is_error)
        wrong = tools.execute(ToolCall("wrong", "create_flashcards",
                                       {"title": "卡片", "data": {"cards": [{"question": "问", "answer": "答"}]}}))
        self.assertTrue(wrong.is_error)
        self.assertEqual(generator.artifacts, [])

    def test_one_artifact_per_turn_even_without_an_explicit_request(self):
        self._load()
        self.assertFalse(self.tools.execute(ToolCall("card", "create_flashcards",
                                                    {"title": "卡片", "data": {"cards": [{"question": "问", "answer": "答"}]}})).is_error)
        second = self.tools.execute(ToolCall("diagram", "create_diagram",
                                             {"title": "流程", "data": {"source": "flowchart LR\n A-->B", "caption": "两步"}}))
        self.assertTrue(second.is_error)
        self.assertEqual(len(self.generator.artifacts), 1)

    def test_an_explicit_refusal_blocks_that_kind_even_when_nothing_was_requested(self):
        conversation = self.db.create_assistance_conversation("refusal-conversation")
        turn = self.db.assistance_turn(conversation["conversation_id"], {
            "client_command_id": "refusal-turn", "expected_version": conversation["version"],
            "text": "只解释当前白板，不生成新白板", "action": "message", "skill_hint": "auto"},
            "rule-input-model", True, build_skill_snapshots())
        self.assertEqual(turn["active_run"]["input"]["requested_artifacts"], [])
        self.assertEqual(turn["active_run"]["input"]["forbidden_artifacts"], ["whiteboard"])
        run = self.db.transition(turn["active_run"]["run_id"], {"queued"}, status="generating")
        generator = AssistantGenerator(self.settings, self.db, Event())
        generator.run = run
        generator.registry = SkillRegistry(run["input"]["skill_snapshots"])
        from time import monotonic
        generator.deadline = monotonic() + 30
        tools = generator.tools()
        self.assertFalse(tools.execute(ToolCall("load", "get_skills", {"name": "concept-explanation"})).is_error)
        blocked = tools.execute(ToolCall("board", "create_whiteboard", {"title": "板书", "data": {"steps": [
            {"title": "起点", "narration": "先看已知条件", "page": 1, "column": 1,
             "operations": [{"kind": "text", "content": "已知 x=2", "items": [], "language": ""}]}]}}))
        self.assertTrue(blocked.is_error)
        self.assertEqual(generator.artifacts, [])

    def test_only_trusted_teaching_tools_are_registered(self):
        names = {t["function"]["name"] for t in self.tools.definitions()}
        self.assertEqual(names, {"get_skills", "create_flashcards", "create_quiz", "create_whiteboard",
                                 "create_animation", "create_diagram"})
        for definition in self.tools.definitions():
            # Core validation rejects unsupported schema keywords before execution.
            schema = definition["function"]["parameters"]
            self.assertNotIn("$defs", json.dumps(schema))
            self.assertNotIn("$ref", json.dumps(schema))

    def test_activation_and_staged_artifact_use_real_tools_and_disk(self):
        args = {"title": "复合函数", "data": {"cards": [{"question": "复合是什么？", "answer": "输出成为输入。"}]}}
        denied = self.tools.execute(ToolCall("before-skill", "create_flashcards", args))
        self.assertTrue(denied.is_error)
        loaded = self.tools.execute(ToolCall("load-skill", "get_skills", {"name": "concept-explanation"}))
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
        result = self.tools.execute(ToolCall("after-cancel", "get_skills", {"name": "concept-explanation"}))
        self.assertTrue(result.is_error)
        self.assertEqual(self.db.calls(self.generator.run["run_id"]), [])


if __name__ == "__main__":
    unittest.main()
