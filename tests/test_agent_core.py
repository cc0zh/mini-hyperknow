"""Direct core-function and real file checks; no provider replacement."""

from pathlib import Path
import tempfile
import unittest

from agent_core import ContextManager, ToolCall, ToolManager
from agent_core.llm.openai import to_openai_messages
from agent_core.tools.read_file import read_file_tool
from agent_core.types import AgentContext, AssistantMessage, ToolResultMessage, UserMessage


class CoreFunctionTests(unittest.TestCase):
    def test_context_snapshot_does_not_mutate_history(self):
        manager = ContextManager("local rules")
        manager.append_message(UserMessage("actual input"))
        context = manager.get_context()
        context.messages.clear()
        self.assertEqual(len(manager.messages), 1)

    def test_actual_file_tool_and_output_bound(self):
        with tempfile.TemporaryDirectory(prefix="hyperknow-core-") as directory:
            path = Path(directory) / "lesson.txt"
            path.write_text("课程正文" * 100, encoding="utf-8")
            manager = ToolManager([read_file_tool], max_output_chars=120)
            result = manager.execute(ToolCall("file-call", "read_file", {"path": str(path)}))
            self.assertFalse(result.is_error)
            self.assertLessEqual(len(result.content), 120)
            self.assertIn("truncated", result.content)
            missing = manager.execute(ToolCall("missing", "read_file", {"path": str(path / "missing")}))
            self.assertTrue(missing.is_error)

    def test_unknown_tool_is_error(self):
        self.assertTrue(ToolManager().execute(ToolCall("unknown", "not_registered")).is_error)

    def test_direct_message_conversion_preserves_tool_order(self):
        context = AgentContext("rules", [
            UserMessage("question"),
            AssistantMessage(tool_calls=[ToolCall("c1", "read_file", {"path": "README.md"})]),
            ToolResultMessage("c1", "file content"),
        ])
        messages = to_openai_messages(context)
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "tool"])
        self.assertEqual(messages[-1]["tool_call_id"], "c1")
        self.assertEqual(messages[2]["tool_calls"][0]["function"]["name"], "read_file")


if __name__ == "__main__":
    unittest.main()
