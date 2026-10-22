import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agent_core import Agent, AssistantMessage, MockLLMService, OpenAIService, ToolCall, ToolManager, ToolResult
from agent_core.llm.openai import to_openai_messages
from agent_core.types import AgentContext, ToolResultMessage, UserMessage
from agent_core.tools import ToolDefinition
from agent_core.tools.read_file import read_file_tool


class AgentCoreTests(unittest.TestCase):
    def test_agent_executes_tool_then_returns_final_response(self):
        def add(arguments):
            return ToolResult(True, arguments["left"] + arguments["right"])

        manager = ToolManager(
            [
                ToolDefinition(
                    name="add",
                    description="Add two numbers.",
                    parameters={"type": "object"},
                    handler=add,
                )
            ]
        )
        llm = MockLLMService(
            [
                AssistantMessage(
                    tool_calls=[ToolCall("call-1", "add", {"left": 2, "right": 3})],
                    stop_reason="tool_use",
                ),
                AssistantMessage("The result is 5."),
            ]
        )

        result = Agent(llm, tools=manager).run("What is 2 + 3?")

        self.assertEqual(result.response.content, "The result is 5.")
        self.assertEqual(result.turns, 2)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[1].messages[-1].content, "5")

    def test_tool_errors_and_output_are_bounded(self):
        manager = ToolManager(
            [
                ToolDefinition(
                    name="explode",
                    description="Test tool.",
                    parameters={"type": "object"},
                    handler=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
                )
            ]
        )

        error = manager.execute(ToolCall("missing", "not_registered"))
        self.assertTrue(error.is_error)
        self.assertIn("Unknown tool", error.content)

        error = manager.execute(ToolCall("broken", "explode"))
        self.assertTrue(error.is_error)
        self.assertIn("RuntimeError", error.content)

        long_manager = ToolManager(
            [
                ToolDefinition(
                    name="long",
                    description="Test tool.",
                    parameters={"type": "object"},
                    handler=lambda _: ToolResult(True, "a" * 200),
                )
            ],
            max_output_chars=100,
        )
        output = long_manager.execute(ToolCall("long-1", "long"))
        self.assertIn("output truncated", output.content)
        self.assertLessEqual(len(output.content), 100)

        bounded_manager = ToolManager([], max_output_chars=10)
        unknown = bounded_manager.execute(ToolCall("unknown-1", "a" * 100))
        self.assertLessEqual(len(unknown.content), 10)

    def test_incomplete_tool_calls_are_closed_on_provider_error(self):
        llm = MockLLMService(
            [
                AssistantMessage(
                    tool_calls=[ToolCall("call-1", "missing", {})],
                    stop_reason="error",
                    error_message="provider failed",
                ),
                AssistantMessage("recovered"),
            ]
        )
        agent = Agent(llm)

        first = agent.run("first")
        self.assertEqual(first.response.stop_reason, "error")
        self.assertEqual(agent.context.messages[-1].role, "tool_result")

        second = agent.run("second")
        self.assertEqual(second.response.content, "recovered")

    def test_read_file_tool_reads_utf8_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.txt"
            path.write_text("hello 世界", encoding="utf-8")

            result = read_file_tool.handler({"path": str(path), "max_chars": 5})

        self.assertTrue(result.success)
        self.assertEqual(result.data, "hello")

    def test_empty_user_input_is_rejected(self):
        with self.assertRaises(ValueError):
            Agent(MockLLMService()).run("  ")

    def test_openai_provider_converts_tool_call_response(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="add",
                                    arguments='{"left": 2, "right": 3}',
                                ),
                            )
                        ],
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        )

        class FakeCompletions:
            def __init__(self):
                self.kwargs = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                return response

        completions = FakeCompletions()
        service = OpenAIService(model="gpt-test", client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
        result = service.complete(
            AgentContext(
                "Be precise.",
                [UserMessage("Calculate"), AssistantMessage(tool_calls=[ToolCall("old", "old_tool", {})]), ToolResultMessage("old", "done")],
                tools=[{"type": "function", "function": {"name": "add"}}],
            )
        )

        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual(result.tool_calls[0].arguments, {"left": 2, "right": 3})
        self.assertEqual(result.usage["total_tokens"], 14)
        self.assertEqual(completions.kwargs["model"], "gpt-test")
        self.assertEqual(completions.kwargs["tools"][0]["function"]["name"], "add")
        self.assertEqual(completions.kwargs["messages"][0], {"role": "system", "content": "Be precise."})

    def test_openai_message_conversion_preserves_tool_call_pairing(self):
        messages = to_openai_messages(
            AgentContext(
                "",
                [
                    AssistantMessage(content="", tool_calls=[ToolCall("call-1", "read_file", {"path": "a.txt"})], stop_reason="tool_use"),
                    ToolResultMessage("call-1", "contents"),
                ],
            )
        )

        self.assertEqual(messages[0]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(messages[1], {"role": "tool", "tool_call_id": "call-1", "content": "contents"})

    def test_openai_provider_turns_provider_failure_into_agent_error(self):
        class FailingCompletions:
            def create(self, **kwargs):
                raise RuntimeError("offline")

        service = OpenAIService(
            client=SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
        )
        result = service.complete(AgentContext("", []))

        self.assertEqual(result.stop_reason, "error")
        self.assertIn("offline", result.error_message)

    def test_openai_service_loads_project_env_without_overriding_process_env(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "OPENAI_API_KEY=dotenv-key\nOPENAI_MODEL=dotenv-model\n"
                "OPENAI_BASE_URL=https://dotenv.example/v1\n",
                encoding="utf-8",
            )
            captured = []
            with patch.dict("os.environ", {"OPENAI_MODEL": "process-model"}, clear=True):
                with patch("agent_core.llm.openai.Path.cwd", return_value=Path(directory)):
                    with patch.object(
                        OpenAIService,
                        "_create_client",
                        side_effect=lambda *args: captured.append(args) or object(),
                    ):
                        service = OpenAIService()

            self.assertEqual(service.model, "process-model")
            self.assertEqual(
                captured,
                [("dotenv-key", "https://dotenv.example/v1", None)],
            )

    def test_explicit_openai_options_override_env_values(self):
        captured = []
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "env-key", "OPENAI_MODEL": "env-model", "OPENAI_BASE_URL": "https://env.example/v1"},
            clear=True,
        ):
            with patch("agent_core.llm.openai.load_dotenv"):
                with patch.object(
                    OpenAIService,
                    "_create_client",
                    side_effect=lambda *args: captured.append(args) or object(),
                ):
                    service = OpenAIService(
                        model="explicit-model",
                        api_key="explicit-key",
                        base_url="https://explicit.example/v1",
                    )

        self.assertEqual(service.model, "explicit-model")
        self.assertEqual(captured, [("explicit-key", "https://explicit.example/v1", None)])


if __name__ == "__main__":
    unittest.main()
