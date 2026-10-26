"""Direct protocol/config checks; no provider response replacement or replay."""

import unittest

from agent_core.llm import LLMConfig, LLMServiceRegistry
from agent_core.llm.openai import completion_parameters, from_openai_response, to_openai_messages
from agent_core.llm.sanitize import sanitize_messages
from agent_core.types import AgentContext, AssistantMessage, ToolCall, ToolResultMessage, UserMessage


class RegistryTests(unittest.TestCase):
    def test_explicit_tiers_and_no_silent_fallback(self):
        registry = LLMServiceRegistry({"high": LLMConfig("configured-model")})
        self.assertTrue(registry.has("high"))
        self.assertFalse(registry.has("low"))
        with self.assertRaisesRegex(ValueError, "not configured"):
            registry.get("low")
        with self.assertRaisesRegex(ValueError, "tier"):
            LLMServiceRegistry({"unknown": LLMConfig("model")})

    def test_invalid_config_and_secret_repr(self):
        config = LLMConfig("model", api_key="not-a-network-credential")
        self.assertNotIn("not-a-network-credential", repr(config))
        for values in ({"model": ""}, {"model": "m", "timeout": 0},
                       {"model": "m", "timeout": float("nan")},
                       {"model": "m", "provider": "unsupported"},
                       {"model": "m", "max_output_tokens": True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                LLMConfig(**values)


class MessageBoundaryTests(unittest.TestCase):
    def test_provider_token_limit_uses_documented_key_without_sdk_or_network(self):
        for endpoint in ("https://api.deepseek.com", "https://api.deepseek.com/v1/"):
            self.assertEqual(completion_parameters(2048, endpoint), {"max_tokens": 2048})
        for endpoint in (None, "https://api.openai.com/v1", "https://api.deepseek.com.example/v1"):
            self.assertEqual(completion_parameters(2048, endpoint), {"max_completion_tokens": 2048})
        self.assertEqual(completion_parameters(None, "https://api.deepseek.com"), {})
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError):
                completion_parameters(value, "https://api.deepseek.com")

    def test_interrupted_group_is_closed_before_next_user(self):
        assistant = AssistantMessage(tool_calls=[ToolCall("a", "read"), ToolCall("b", "read")])
        source = [UserMessage("first"), assistant, ToolResultMessage("a", "saved"), UserMessage("next")]
        result = sanitize_messages(source)
        self.assertEqual([m.role for m in result], ["user", "assistant", "tool_result", "tool_result", "user"])
        self.assertEqual(result[3].tool_call_id, "b")
        self.assertTrue(result[3].is_error)
        self.assertIn("unknown", result[3].content)
        self.assertEqual(len(source), 4)

    def test_orphan_results_and_failed_empty_assistants_not_replayed(self):
        source = [ToolResultMessage("orphan", "unexpected"), AssistantMessage(stop_reason="error"),
                  AssistantMessage(stop_reason="aborted"), UserMessage("continue")]
        self.assertEqual(sanitize_messages(source), [UserMessage("continue")])

    def test_tool_argument_snapshot_is_independent(self):
        assistant = AssistantMessage(tool_calls=[ToolCall("a", "read", {"path": "original"})])
        result = sanitize_messages([assistant])
        result[0].tool_calls[0].arguments["path"] = "changed"
        self.assertEqual(assistant.tool_calls[0].arguments["path"], "original")

    def test_duplicate_identity_rejected_at_boundary(self):
        for calls in ([ToolCall("same", "read"), ToolCall("same", "read")], [ToolCall("", "read")]):
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                sanitize_messages([AssistantMessage(tool_calls=calls)])

    def test_wire_conversion_closes_trailing_group(self):
        context = AgentContext("rules", [AssistantMessage(tool_calls=[ToolCall("a", "read")])])
        messages = to_openai_messages(context)
        self.assertEqual(messages[-1]["role"], "tool")
        self.assertEqual(messages[-1]["tool_call_id"], "a")

    def test_incomplete_tool_json_cannot_be_treated_as_executable(self):
        # These dictionaries are direct converter inputs, never SDK/HTTP substitutes.
        for reason in ("length", "content_filter", "unknown", None):
            result = from_openai_response({"choices": [{"finish_reason": reason, "message": {
                "tool_calls": [{"id": "a", "function": {"name": "write", "arguments": "{}"}}],
            }}]}, model="requested")
            self.assertEqual(result.stop_reason, "error")
            self.assertIn(str(reason), result.error_message)

    def test_tool_finish_without_tool_calls_is_not_success(self):
        result = from_openai_response({"choices": [{"finish_reason": "tool_calls", "message": {"content": ""}}]},
                                      model="requested")
        self.assertEqual(result.stop_reason, "error")

    def test_invalid_tool_arguments_and_negative_usage(self):
        result = from_openai_response({"usage": {"total_tokens": -1, "prompt_tokens": True},
                                      "choices": [{"message": {"tool_calls": [{
                                          "id": "", "function": {"name": "read", "arguments": "[]"},
                                      }]}}]}, model="requested")
        self.assertEqual(result.stop_reason, "error")
        self.assertIsNone(result.usage)

    def test_non_finite_or_non_json_arguments_are_provider_errors(self):
        for arguments in ('{"bad":NaN}', '{"bad":Infinity}', '{"bad":-Infinity}',
                          '{"bad":1e999}', {"bad": float("nan")}, {"bad": object()},
                          {"nested": {2: "not-a-string-key"}}):
            with self.subTest(arguments=arguments):
                result = from_openai_response({"usage": {"total_tokens": 7}, "choices": [{
                    "finish_reason": "tool_calls", "message": {"tool_calls": [{
                        "id": "a", "function": {"name": "read_file", "arguments": arguments},
                    }]},
                }]}, model="requested")
                self.assertEqual(result.stop_reason, "error")
                self.assertEqual(result.tool_calls, [])
                self.assertEqual(result.usage, {"total_tokens": 7})

    def test_non_text_content_is_explicit_error_not_context_crash(self):
        result = from_openai_response({"choices": [{"message": {"content": ["unexpected"]}}]}, model="requested")
        self.assertEqual(result.stop_reason, "error")
        self.assertIn("non-text", result.error_message)


if __name__ == "__main__":
    unittest.main()
