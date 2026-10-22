"""Real temporary disk and pure context rules; no provider replacements."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_core.compression import (
    ContextBudgetExceeded, SUMMARY_HEADER, build_compression_request, plan_compression,
)
from agent_core.context import ContextManager
from agent_core.llm.openai import to_openai_messages
from agent_core.memory import LongTermMemory
from agent_core.storage import SessionBusyError, SessionConflictError, SessionCorruptionError, SessionStore
from agent_core.tokens import TokenCounter, TokenEstimator
from agent_core.types import AgentContext, AssistantMessage, ToolCall, ToolResultMessage, UserMessage


def append_turn(manager: ContextManager, text: str, *, tool: bool = False) -> None:
    manager.append_message(UserMessage(text))
    if tool:
        call_id = f"lookup-{len(manager.messages)}"
        manager.append_message(AssistantMessage(tool_calls=[ToolCall(call_id, "read", {"paths": ["a"]})]))
        manager.append_message(ToolResultMessage(call_id, "actual historical tool output"))
    manager.append_message(AssistantMessage("Completed response"))


class ContextSnapshotTests(unittest.TestCase):
    def test_legacy_api_and_nested_snapshot_ownership(self):
        manager = ContextManager("original system")
        manager.append_message(UserMessage("question"))
        call = ToolCall("one", "read", {"nested": {"paths": ["original"]}})
        assistant = AssistantMessage(tool_calls=[call], usage={"prompt_tokens": 4})
        manager.append_message(assistant)
        call.arguments["nested"]["paths"].append("external")
        assistant.tool_calls.clear()
        assistant.usage["prompt_tokens"] = 200
        manager.append_message(ToolResultMessage("one", "result"))
        tools = [{"type": "function", "function": {"parameters": {"items": ["original"]}}}]
        context = manager.prepare(iter(tools))
        tools[0]["function"]["parameters"]["items"].clear()
        context.tools[0]["function"]["parameters"]["items"].append("snapshot only")
        context.messages[1].tool_calls[0].arguments["nested"]["paths"].clear()
        manager.messages[1].tool_calls.clear()
        manager.audit_messages[1].tool_calls.clear()
        self.assertEqual(manager.messages[1].tool_calls[0].arguments, {"nested": {"paths": ["original"]}})
        self.assertEqual(manager.messages[1].usage, {"prompt_tokens": 4})
        self.assertEqual(len(manager.audit_messages[1].tool_calls), 1)
        self.assertEqual(context.system_prompt, "original system")
        self.assertFalse(manager.needs_compression())

    def test_invalid_tool_pairing_cannot_change_history(self):
        manager = ContextManager()
        with self.assertRaises(ValueError):
            manager.append_message(ToolResultMessage("absent", "orphan"))
        manager.append_message(UserMessage("request"))
        with self.assertRaises(ValueError):
            manager.append_message(AssistantMessage(tool_calls=[ToolCall("same", "read"), ToolCall("same", "read")]))
        manager.append_message(AssistantMessage(tool_calls=[ToolCall("one", "read"), ToolCall("two", "read")]))
        before = manager.messages
        with self.assertRaises(ValueError):
            manager.append_message(UserMessage("cannot interleave"))
        with self.assertRaises(ContextBudgetExceeded):
            manager.prepare()
        self.assertEqual(manager.messages, before)
        manager.append_message(ToolResultMessage("two", "out of order is allowed"))
        with self.assertRaises(ValueError):
            manager.append_message(ToolResultMessage("two", "duplicate"))
        manager.append_message(ToolResultMessage("one", "resolved"))
        self.assertEqual(len(manager.get_context().messages), 4)
        with self.assertRaisesRegex(ValueError, "unique within active history"):
            manager.append_message(AssistantMessage(tool_calls=[ToolCall("one", "read")]))

    def test_preparation_cancelled_without_mutating_history(self):
        manager = ContextManager()
        append_turn(manager, "input")
        before = manager.messages
        with self.assertRaisesRegex(ContextBudgetExceeded, "cancelled"):
            manager.prepare(is_aborted=lambda: True)
        self.assertEqual(manager.messages, before)


class SessionDiskTests(unittest.TestCase):
    def test_turn_markers_and_restore_close_all_dangling_calls_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            with SessionStore(path) as store:
                manager = ContextManager("rules", session_store=store)
                self.assertEqual(manager.begin_turn(), 1)
                self.assertEqual(manager.begin_turn(), 1)
                manager.append_message(UserMessage("write once"))
                manager.append_message(AssistantMessage(
                    tool_calls=[ToolCall("done", "write"), ToolCall("unknown", "write"), ToolCall("never", "write")],
                    stop_reason="tool_use", usage={"prompt_tokens": 29},
                ))
                manager.append_message(ToolResultMessage("done", "side effect already happened"))
            with SessionStore(path) as store:
                manager = ContextManager("rules", session_store=store)
                self.assertEqual(len(manager.messages), 5)
                for result in manager.messages[-2:]:
                    self.assertTrue(result.is_error)
                    self.assertIn("Interrupted", result.content)
                    self.assertIn("not automatically re-executed", result.content)
                self.assertEqual([message.tool_call_id for message in manager.messages[-3:]], ["done", "unknown", "never"])
                provider = to_openai_messages(manager.prepare())
                self.assertEqual([message["role"] for message in provider], ["system", "user", "assistant", "tool", "tool", "tool"])
                self.assertEqual(store.load().turn, 1)
                audit = manager.audit_messages
                counter = TokenCounter()
                self.assertIsNone(counter.totals["total_tokens"])
                self.assertEqual(counter.snapshot()["calls"], 0)
            with SessionStore(path) as store:
                manager = ContextManager(session_store=store)
                self.assertEqual(manager.audit_messages, audit)
                self.assertEqual(manager.begin_turn(), 2)
                manager.append_message(UserMessage("explicit continuation"))
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([record["turn"] for record in records if record["type"] == "turn"], [1, 2])

    def test_single_writer_is_os_owned_and_one_context_per_store(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            with SessionStore(path) as store:
                manager = ContextManager(session_store=store)
                with self.assertRaises(SessionBusyError):
                    SessionStore(path)
                with self.assertRaises(SessionBusyError):
                    ContextManager(session_store=store)
                script = (
                    "import sys; from agent_core.storage import SessionStore, SessionBusyError; "
                    "\ntry: s = SessionStore(sys.argv[1])"
                    "\nexcept SessionBusyError: sys.exit(0)"
                    "\nelse: s.close(); sys.exit(3)"
                )
                process = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, timeout=20)
                self.assertEqual(process.returncode, 0, process.stderr)
                manager.append_message(UserMessage("still owned"))
            with SessionStore(path) as store:
                self.assertEqual(store.load().messages, [UserMessage("still owned")])

    def test_real_process_exit_releases_lock_and_repairs_pending_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash.jsonl"
            script = (
                "import os,sys; from agent_core.context import ContextManager; "
                "from agent_core.storage import SessionStore; "
                "from agent_core.types import UserMessage, AssistantMessage, ToolCall; "
                "s=SessionStore(sys.argv[1]); c=ContextManager(session_store=s); "
                "c.append_message(UserMessage('change disk')); "
                "c.append_message(AssistantMessage(tool_calls=[ToolCall('write','write')])); os._exit(0)"
            )
            process = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr)
            with SessionStore(path) as store:
                manager = ContextManager(session_store=store)
                self.assertTrue(manager.messages[-1].is_error)
                manager.prepare()

    def test_only_uncommitted_tail_can_be_recovered_and_append_remains_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            with SessionStore(path) as store:
                ContextManager(session_store=store).append_message(UserMessage("durable"))
            original = path.read_bytes()
            tail = b'{"version":1,"seq":3,"message":"\xe4\xb8'
            with path.open("ab") as stream:
                stream.write(tail)
            with SessionStore(path) as store:
                self.assertEqual(store.recovered_tail_bytes, len(tail))
                self.assertEqual(path.read_bytes(), original)
                manager = ContextManager(session_store=store)
                manager.append_message(AssistantMessage("continued"))
            with SessionStore(path) as store:
                self.assertEqual(len(store.load().audit_messages), 2)
                self.assertEqual(store.recovered_tail_bytes, 0)

    def test_committed_corruption_even_at_end_is_not_swallowed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            with SessionStore(path) as store:
                ContextManager(session_store=store).append_message(UserMessage("durable"))
            original = path.read_bytes()
            for tail in (b'not json\n', b'not json\n{"unfinished":', b'broken\rrecord\n{"unfinished":',
                         b'{"version":1,"seq":999,"type":"turn","turn":2}\n'):
                with self.subTest(tail=tail):
                    path.write_bytes(original + tail)
                    before = path.read_bytes()
                    with self.assertRaises(SessionCorruptionError):
                        SessionStore(path)
                    self.assertEqual(path.read_bytes(), before)

    def test_non_newline_record_is_not_a_committed_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            with SessionStore(path) as store:
                ContextManager(session_store=store).append_message(UserMessage("keep me"))
                revision = store.load().revision
            tail = json.dumps({"version": 1, "seq": revision + 1, "type": "checkpoint", "messages": []}).encode()
            with path.open("ab") as stream:
                stream.write(tail)
            with SessionStore(path) as store:
                self.assertEqual(store.recovered_tail_bytes, len(tail))
                self.assertEqual(store.load().messages, [UserMessage("keep me")])

    def test_stale_revision_and_invalid_checkpoint_leave_both_states_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            with SessionStore(path) as store:
                store.append_message(UserMessage("original"))
                before, disk = store.load(), path.read_bytes()
                with self.assertRaises(SessionConflictError):
                    store.checkpoint([], expected_revision=0)
                with self.assertRaises(ValueError):
                    store.checkpoint([ToolResultMessage("missing", "orphan")])
                with self.assertRaises(ValueError):
                    store.append_message(AssistantMessage(tool_calls=[ToolCall("bad", "read", {"not-json": object()})]))
                self.assertEqual(store.load(), before)
                self.assertEqual(path.read_bytes(), disk)


class MemoryDiskTests(unittest.TestCase):
    def test_existing_oversized_memory_is_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            path.write_text('{"too-large":"' + "x" * 100 + '"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "byte limit"):
                LongTermMemory(path, max_total_bytes=40)

    def test_explicit_crud_atomic_reload_and_no_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            memory = LongTermMemory(path)
            manager = ContextManager("system unchanged", memory=memory)
            append_turn(manager, "My name is private and must not be inferred")
            self.assertEqual(memory.as_dict(), {})
            self.assertFalse(path.exists())
            memory.set("language", "Chinese")
            memory.update({"format": "concise"})
            memory.as_dict()["language"] = "external"
            self.assertEqual(LongTermMemory(path).get("language"), "Chinese")
            context = manager.prepare()
            self.assertEqual(context.system_prompt, "system unchanged")
            self.assertIn("Untrusted explicit long-term memory", context.messages[0].content)
            self.assertTrue(memory.delete("format"))
            self.assertFalse(memory.delete("not present"))
            memory.replace({"only": "replacement"})
            self.assertEqual(LongTermMemory(path).as_dict(), {"only": "replacement"})
            memory.replace({})
            self.assertEqual(memory.as_dict(), {})

    def test_bounds_validate_before_disk_or_state_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            memory = LongTermMemory(path, max_entries=2, max_value_chars=10, max_total_bytes=40)
            memory.set("keep", "old")
            original = path.read_bytes()
            for values in ({"a": "a", "b": "b", "c": "c"}, {"key": "x" * 11},
                           {"": "no"}, {"a" * 129: "a"}, {"a": "中" * 10, "b": "中" * 10}, {"a": 1}):
                with self.subTest(values=values):
                    with self.assertRaises(ValueError):
                        memory.replace(values)
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(memory.as_dict(), {"keep": "old"})

    def test_real_atomic_replace_failure_does_not_commit_in_memory_or_leave_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            memory = LongTermMemory(path)
            memory.set("keep", "old")
            backup = path.with_suffix(".previous")
            path.rename(backup)
            path.mkdir()
            marker = path / "marker"
            marker.write_text("must remain", encoding="utf-8")
            with self.assertRaises(OSError):
                memory.set("keep", "uncommitted")
            self.assertEqual(memory.get("keep"), "old")
            self.assertEqual(LongTermMemory(backup).get("keep"), "old")
            self.assertEqual(marker.read_text(encoding="utf-8"), "must remain")
            self.assertEqual(sorted(item.name for item in Path(directory).iterdir()), ["memory.json", "memory.previous"])


class TokenRuleTests(unittest.TestCase):
    def test_estimate_includes_system_nested_arguments_schemas_and_output_reserve(self):
        estimator = TokenEstimator()
        context = AgentContext("rules", [UserMessage("question")])
        original = estimator.estimate(context)
        reserved = estimator.estimate(context, reserve_output_tokens=123)
        self.assertTrue(original.is_estimate)
        self.assertEqual(reserved.total_tokens - original.total_tokens, 123)
        enlarged = deepcopy(context)
        enlarged.system_prompt += "中" * 100
        self.assertGreaterEqual(estimator.estimate(enlarged).total_tokens - original.total_tokens, 300)
        enlarged.tools = [{"function": {"name": "read", "parameters": {"description": "x" * 2000}}}]
        self.assertGreater(estimator.estimate(enlarged).input_tokens, original.input_tokens + 2000)
        enlarged.messages.append(AssistantMessage(tool_calls=[ToolCall("one", "read", {"nested": ["x" * 2000]})]))
        self.assertGreater(estimator.estimate(enlarged).input_tokens, original.input_tokens + 4000)

    def test_budget_threshold_is_tokens_not_turn_count_and_counts_tools_and_memory(self):
        manager = ContextManager(max_context_tokens=3000, reserve_output_tokens=100)
        append_turn(manager, "short")
        self.assertFalse(manager.needs_compression())
        definitions = [{"description": "x" * 3000}]
        self.assertTrue(manager.needs_compression(iter(definitions)))
        before = manager.messages
        with self.assertRaises(ContextBudgetExceeded):
            manager.prepare(definitions)
        self.assertEqual(manager.messages, before)
        manager.append_message(UserMessage("one huge input" * 400))
        self.assertTrue(manager.needs_compression())
        with self.assertRaises(ContextBudgetExceeded):
            manager.prepare()
        with tempfile.TemporaryDirectory() as directory:
            memory = LongTermMemory(Path(directory) / "memory.json")
            memory.set("fact", "x" * 2500)
            self.assertTrue(ContextManager(memory=memory, max_context_tokens=2000).needs_compression())

    def test_provider_counter_preserves_unknown_partial_actual_zero_and_summary_buckets(self):
        counter = TokenCounter()
        self.assertIsNone(counter.totals["total_tokens"])
        usage = {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12}
        counter.record(usage)
        usage["total_tokens"] = 200
        counter.record({"prompt_tokens": 2, "completion_tokens": 0, "total_tokens": 2}, kind="summary")
        self.assertEqual(counter.totals["total_tokens"], 14)
        self.assertEqual(counter.snapshot()["by_kind"]["summary"]["usage"]["completion_tokens"], 0)
        counter.record(None)
        counter.record({"prompt_tokens": 4})
        snapshot = counter.snapshot()
        self.assertIsNone(snapshot["usage"]["total_tokens"])
        self.assertIsNone(snapshot["usage"]["prompt_tokens"])
        self.assertEqual(snapshot["known_usage"]["total_tokens"], 14)
        self.assertEqual(snapshot["known_usage"]["prompt_tokens"], 15)
        self.assertEqual(snapshot["calls"], 4)
        self.assertEqual(snapshot["unknown_calls"], 1)
        for invalid in ({"total_tokens": -1}, {"total_tokens": True}, {"total_tokens": "5"}):
            with self.assertRaises(ValueError):
                counter.record(invalid)
        self.assertEqual(counter.snapshot(), snapshot)


class CompressionRuleTests(unittest.TestCase):
    def make_history(self, **kwargs) -> ContextManager:
        manager = ContextManager("original trusted system", **kwargs)
        append_turn(manager, "Old factual input " * 300, tool=True)
        append_turn(manager, "another old turn " * 200)
        append_turn(manager, "recent turn", tool=True)
        manager.append_message(UserMessage("current user turn"))
        manager.append_message(AssistantMessage(tool_calls=[ToolCall("now", "read")]))
        manager.append_message(ToolResultMessage("now", "current result"))
        return manager

    def test_plan_retains_whole_user_turns_and_never_promotes_summary_to_system(self):
        manager = self.make_history()
        before = manager.messages
        plan = plan_compression(before, keep_recent_turns=2)
        self.assertEqual(plan.recent_messages[0], UserMessage("recent turn"))
        self.assertEqual(plan.recent_messages[-1], ToolResultMessage("now", "current result"))
        candidate = plan.candidate("Historical goals and observed tool outcomes.")
        manager.commit_compression(candidate)
        context = manager.get_context()
        self.assertEqual(context.system_prompt, "original trusted system")
        self.assertEqual(context.messages[0].role, "user")
        self.assertTrue(context.messages[0].content.startswith(SUMMARY_HEADER))
        self.assertEqual(context.messages[1:], list(plan.recent_messages))
        self.assertEqual(manager.audit_messages, before)
        self.assertEqual(to_openai_messages(context)[0]["content"], "original trusted system")

    def test_summary_request_has_its_own_full_input_and_output_preflight(self):
        plan = plan_compression(self.make_history().messages)
        request = build_compression_request(plan)
        self.assertEqual(request.tools, [])
        self.assertIn("untrusted historical conversation", request.system_prompt)
        self.assertEqual(len(json.loads(request.messages[0].content)), len(plan.older_messages))
        estimate = TokenEstimator().estimate(request, reserve_output_tokens=1024)
        with self.assertRaisesRegex(ContextBudgetExceeded, "low-tier context budget"):
            build_compression_request(plan, max_context_tokens=estimate.total_tokens - 1)
        self.assertEqual(build_compression_request(plan, max_context_tokens=estimate.total_tokens), request)
        with self.assertRaisesRegex(ContextBudgetExceeded, "low-tier context budget"):
            build_compression_request(plan, max_context_tokens=estimate.total_tokens, reserve_output_tokens=1025)
        # JSON-wrapping historical tool arguments and content itself consumes budget.
        history_input = TokenEstimator().estimate(AgentContext("", list(plan.older_messages))).input_tokens
        self.assertGreater(estimate.input_tokens, history_input)
        for kwargs in ({"max_context_tokens": 0}, {"reserve_output_tokens": 0},
                       {"max_context_tokens": 100, "reserve_output_tokens": 100}):
            with self.assertRaises(ValueError):
                build_compression_request(plan, **kwargs)

    def test_compression_checkpoint_restores_active_history_and_preserves_all_audit_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            with SessionStore(path) as store:
                manager = self.make_history(session_store=store)
                audit, original_log = manager.audit_messages, path.read_bytes()
                manager.commit_compression(plan_compression(manager.messages).candidate("Useful historical facts."))
                active = manager.messages
                self.assertTrue(path.read_bytes().startswith(original_log))
                self.assertEqual(store.load().audit_messages, audit)
                self.assertEqual(store.load().messages, active)
            with SessionStore(path) as store:
                manager = ContextManager(session_store=store)
                self.assertEqual(manager.messages, active)
                self.assertEqual(manager.audit_messages, audit)
                self.assertGreater(len(manager.audit_messages), len(manager.messages))

    def test_empty_larger_stale_or_underbudget_candidates_cannot_replace_history(self):
        manager = self.make_history()
        plan = plan_compression(manager.messages)
        original, audit = manager.messages, manager.audit_messages
        for invalid in ("", "   "):
            with self.assertRaises(ContextBudgetExceeded):
                plan.candidate(invalid)
        with self.assertRaisesRegex(ContextBudgetExceeded, "did not reduce"):
            manager.commit_compression(plan.candidate("x" * 30000))
        self.assertEqual(manager.messages, original)
        self.assertEqual(manager.audit_messages, audit)
        candidate = plan.candidate("short summary")
        manager.append_message(AssistantMessage("newer state"))
        with self.assertRaisesRegex(ContextBudgetExceeded, "stale"):
            manager.commit_compression(candidate)
        bounded = self.make_history(max_context_tokens=300)
        before = bounded.messages
        with self.assertRaisesRegex(ContextBudgetExceeded, "threshold"):
            bounded.commit_compression(plan_compression(before).candidate("short summary"))
        self.assertEqual(bounded.messages, before)

    def test_failed_checkpoint_keeps_live_history_and_disk_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            store = SessionStore(path)
            manager = self.make_history(session_store=store)
            candidate = plan_compression(manager.messages).candidate("short summary")
            original, audit, disk = manager.messages, manager.audit_messages, path.read_bytes()
            store.close()
            with self.assertRaisesRegex(RuntimeError, "closed"):
                manager.commit_compression(candidate)
            self.assertEqual(manager.messages, original)
            self.assertEqual(manager.audit_messages, audit)
            self.assertEqual(path.read_bytes(), disk)
            with SessionStore(path) as restored:
                self.assertEqual(restored.load().messages, original)

    def test_configured_threshold_commit_is_complete_and_below_trigger(self):
        manager = self.make_history()
        original = manager.estimate_tokens().total_tokens
        manager.max_context_tokens = original
        self.assertTrue(manager.needs_compression())
        manager.commit_compression(plan_compression(manager.messages).candidate("small factual summary"))
        self.assertFalse(manager.needs_compression())
        self.assertEqual(manager.prepare().messages, manager.messages)

    def test_cannot_split_a_recent_turn_or_repeatedly_summarize_only_a_summary(self):
        manager = ContextManager()
        append_turn(manager, "huge only turn " * 200)
        with self.assertRaisesRegex(ContextBudgetExceeded, "No older whole"):
            plan_compression(manager.messages)
        manager = self.make_history()
        manager.commit_compression(plan_compression(manager.messages).candidate("facts"))
        with self.assertRaisesRegex(ContextBudgetExceeded, "existing summary"):
            plan_compression(manager.messages)
        with self.assertRaises(ValueError):
            plan_compression(manager.messages, keep_recent_turns=0)


if __name__ == "__main__":
    unittest.main()
