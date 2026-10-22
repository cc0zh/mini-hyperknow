"""Free pre-admission checks using the actual provider, never a replacement."""

from threading import Event
import unittest

from agent_core import Agent, ContextManager, OpenAIService, ToolManager
from agent_core.compression import ContextBudgetExceeded, ContextCompressor, plan_compression
from agent_core.engine import _emit, run_agent_loop
from agent_core.tokens import TokenCounter
from agent_core.types import AssistantMessage, ToolCall, UserMessage


class EventTests(unittest.TestCase):
    def test_observer_cannot_mutate_call_or_tool_result_context(self):
        source = AssistantMessage(tool_calls=[ToolCall("a", "read", {"path": "original"})])

        def observer(event):
            event.data["message"].tool_calls[0].arguments["path"] = "modified"
            event.data["message"].tool_calls.clear()

        _emit(observer, "assistant_message", message=source)
        self.assertEqual(source.tool_calls[0].arguments["path"], "original")

    def test_failed_observer_is_not_a_result_commit_failure(self):
        def observer(event):
            raise ValueError("event sink disconnected")

        with self.assertWarnsRegex(RuntimeWarning, "observer failed: ValueError"):
            _emit(observer, "agent_end", response=AssistantMessage("complete"))


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        # Real SDK configured for a closed local endpoint; no model or HTTP stub.
        # A bug may attempt an actual failing connection, but can never charge.
        self.service = OpenAIService(api_key="local-admission-check", base_url="http://127.0.0.1:1/v1",
                                     model="admission-check", timeout=.1, max_retries=0)
        self.addCleanup(self.service.close)

    def test_turn_start_observer_can_cancel_before_first_paid_request(self):
        events = []

        def observer(event):
            events.append(event.type)
            if event.type == "turn_start":
                agent.abort()

        agent = Agent(self.service, emit=observer)
        result = agent.run("cancel before network admission")
        self.assertTrue(result.aborted)
        self.assertEqual(result.turns, 0)
        self.assertEqual(result.usage["calls"], 0)
        self.assertEqual(events, ["agent_start", "turn_start", "turn_end", "agent_end"])
        self.assertEqual(len(agent.context.messages), 1)

    def test_budget_rejection_does_not_request_provider_or_drop_history(self):
        context = ContextManager(max_context_tokens=200)
        context.append_message(UserMessage("large current turn " * 100))
        original = context.messages
        counter = TokenCounter()
        result = run_agent_loop(context, self.service, ToolManager(), token_counter=counter)
        self.assertEqual(result.turns, 0)
        self.assertEqual(result.response.stop_reason, "error")
        self.assertEqual(context.messages, original)
        self.assertEqual(counter.snapshot()["calls"], 0)

    def test_summary_cancelled_after_request_preparation_before_admission(self):
        history = [UserMessage("older long data " * 100), UserMessage("recent"), UserMessage("current")]
        plan = plan_compression(history)
        checks = []

        def cancelled():
            checks.append(True)
            return len(checks) >= 2

        compressor = ContextCompressor(self.service)
        with self.assertRaisesRegex(ContextBudgetExceeded, "cancelled before"):
            compressor.complete_plan(plan, is_aborted=cancelled)
        self.assertEqual(len(checks), 2)

    def test_already_cancelled_run_has_agent_lifecycle_and_no_model_turn(self):
        stopped = Event()
        stopped.set()
        events = []
        result = run_agent_loop(ContextManager(), self.service, ToolManager(),
                                is_aborted=stopped.is_set, emit=lambda event: events.append(event.type))
        self.assertTrue(result.aborted)
        self.assertEqual(result.turns, 0)
        self.assertEqual(events, ["agent_start", "agent_end"])


if __name__ == "__main__":
    unittest.main()
