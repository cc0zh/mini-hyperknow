"""Real temporary files, approval threads, ripgrep and OS processes; no substitutes."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from agent_core.tools import (
    ApprovalStore, OutputTruncator, ToolDefinition, ToolManager, ToolScheduler,
    create_workspace_tools,
)
from agent_core.tools.process import process_environment, run_process
from agent_core.tools.read_file import read_file_tool
from agent_core.tools.shared import is_link
from agent_core.tools.validation import validate
from agent_core.context import ContextManager
from agent_core.storage import SessionStore
from agent_core.types import AssistantMessage, ToolCall, ToolResult, ToolResultMessage, UserMessage


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        threading.Event().wait(0.01)
    raise AssertionError("timed out waiting for real resource")


def process_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            if ctypes.get_last_error() == 87:  # already gone
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class ToolFilesTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agent-tools-v1-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.output = self.base / "output"
        self.manager = create_workspace_tools(self.root, output_dir=self.output)

    def execute(self, name, **arguments):
        return self.manager.execute(ToolCall("direct", name, arguments))

    def approved(self, calls, *, manager=None, emit=None, on_result=None, mode="parallel"):
        """A real host approval thread, not an injected permission decision."""
        store = ApprovalStore()
        stop = threading.Event()
        decisions = []

        def approve():
            while not stop.is_set():
                for request in store.pending():
                    decisions.append(store.resolve(request.id, True))
                stop.wait(0.005)

        thread = threading.Thread(target=approve, name="host-approval")
        thread.start()
        try:
            result = ToolScheduler(manager or self.manager, store, emit=emit, mode=mode,
                                   approval_timeout=2).execute_batch(calls, on_result=on_result)
        finally:
            stop.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(all(decisions))
        self.assertEqual(store.pending(), [])
        return result

    def make_directory_link(self, target, link):
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            # Junctions work without Developer Mode/admin and exercise the same
            # real Windows reparse-point boundary. No dependency replacement.
            subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                           check=True, capture_output=True, timeout=5)
        self.addCleanup(lambda: link.rmdir() if link.exists() else None)
        self.assertTrue(is_link(link))


class OutputTests(ToolFilesTestCase):
    def test_hard_budgets_and_exact_atomic_unicode_archives(self):
        source = "原文🙂\r\n" * 2000
        for budget in (1, 8, 120, 500):
            with self.subTest(budget=budget):
                truncator = OutputTruncator(budget, output_dir=self.output)
                preview = truncator.truncate(source)
                self.assertLessEqual(len(preview), budget)
                archive = self.output / (hashlib.sha256(source.encode()).hexdigest() + ".txt")
                self.assertEqual(archive.read_bytes(), source.encode())
                self.assertEqual(truncator.truncate(source), preview)
                if budget == 500:
                    self.assertIn(str(archive), preview)
        self.assertEqual(list(self.output.glob(".output-*")), [])
        self.assertEqual(OutputTruncator(3).truncate("abc"), "abc")

    def test_manager_bound_with_larger_external_truncator_and_error_archive(self):
        source = self.root / "large.txt"
        source.write_text("long正文" * 1000, encoding="utf-8")
        manager = ToolManager([read_file_tool], max_output_chars=200,
                              truncator=OutputTruncator(20_000, output_dir=self.output))
        result = manager.execute(ToolCall("long", "read_file", {"path": str(source)}))
        self.assertFalse(result.is_error)
        self.assertLessEqual(len(result.content), 200)
        self.assertIn("truncated", result.content)
        self.assertIn("full text", result.content)
        archive = next(self.output.glob("*.txt"))
        self.assertEqual(archive.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
        failure = manager.error(ToolCall("bad", "read_file"), "错误" * 1000)
        self.assertTrue(failure.is_error)
        self.assertLessEqual(len(failure.content), 200)
        self.assertTrue(any(p.read_text(encoding="utf-8").startswith("Tool error: 错误")
                            for p in self.output.glob("*.txt")))

    def test_workspace_only_reads_its_registered_external_archives(self):
        path = self.root / "long.txt"
        path.write_text("line data\n" * 2000, encoding="utf-8")
        result = self.execute("read_file", path="long.txt", limit=2000)
        self.assertIn("truncated", result.content)
        archive = next(self.output.glob("*.txt"))
        recovered = self.execute("read_file", path=str(archive), limit=2)
        self.assertFalse(recovered.is_error)
        arbitrary = self.output / "unregistered.txt"
        arbitrary.write_text("not an artifact", encoding="utf-8")
        self.assertTrue(self.execute("read_file", path=str(arbitrary)).is_error)
        # Registration is manager-local, not carte blanche for the output dir.
        other = create_workspace_tools(self.root, output_dir=self.output)
        self.assertTrue(other.execute(ToolCall("other", "read_file", {"path": str(archive)})).is_error)
        write = self.approved([ToolCall("write-archive", "write_file", {
            "path": str(archive), "content": "cannot overwrite artifacts",
        })])[0]
        self.assertTrue(write.is_error)


class WorkspaceTests(ToolFilesTestCase):
    def test_paging_exact_newlines_and_requested_character_bound(self):
        path = self.root / "text.txt"
        path.write_bytes("第一行\r\nsecond\r\nthird\n".encode())
        page = self.execute("read_file", path="text.txt", offset=2, limit=2)
        self.assertEqual(page.content, "2|second\r\n3|third\n")
        for cap in (1, 8, 32, 100):
            result = self.execute("read_file", path="text.txt", max_chars=cap)
            self.assertFalse(result.is_error)
            self.assertLessEqual(len(result.content), cap)
        beyond = self.execute("read_file", path="text.txt", offset=20)
        self.assertEqual(beyond.content, "")
        path.write_bytes(b"a\rb\rc")
        self.assertEqual(self.execute("read_file", path="text.txt", offset=2, limit=2).content,
                         "2|b\r3|c")
        self.assertEqual(self.execute("read_file", path="text.txt", offset=3, limit=1).content, "3|c")
        # CRLF split exactly at the skip-fragment boundary is still one newline.
        path.write_bytes(b"a" * 65535 + b"\r\ntarget\rlast")
        self.assertEqual(self.execute("read_file", path="text.txt", offset=2, limit=2).content,
                         "2|target\r3|last")

    def test_create_read_before_overwrite_digest_conflicts_and_exact_edit(self):
        path = self.root / "file.txt"
        path.write_bytes(b"same\r\nsame\r\n")
        denied = self.approved([ToolCall("unread", "write_file", {"path": "file.txt", "content": "new"})])[0]
        self.assertTrue(denied.is_error)
        self.assertIn("read before", denied.content)
        self.assertFalse(self.execute("read_file", path="file.txt").is_error)
        ambiguous = self.approved([ToolCall("edit", "edit_file", {
            "path": "file.txt", "old_string": "same", "new_string": "changed",
        })])[0]
        self.assertTrue(ambiguous.is_error)
        self.assertIn("ambiguous", ambiguous.content)
        replaced = self.approved([ToolCall("all", "edit_file", {
            "path": "file.txt", "old_string": "same", "new_string": "改变", "replace_all": True,
        })])[0]
        self.assertFalse(replaced.is_error, replaced.content)
        self.assertEqual(path.read_bytes(), "改变\r\n改变\r\n".encode())
        self.assertIn("---", replaced.content)
        before = path.stat()
        path.write_bytes("外改\r\n外改\r\n".encode())  # same length and timestamp, different digest
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        stale = self.approved([ToolCall("stale", "write_file", {"path": "file.txt", "content": "lost"})])[0]
        self.assertTrue(stale.is_error)
        self.assertIn("changed since read", stale.content)
        self.assertEqual(path.read_bytes(), "外改\r\n外改\r\n".encode())
        self.execute("read_file", path="file.txt")
        missing_match = self.approved([ToolCall("absent", "edit_file", {
            "path": "file.txt", "old_string": "not present", "new_string": "x",
        })])[0]
        self.assertTrue(missing_match.is_error)
        path.unlink()
        removed = self.approved([ToolCall("removed", "write_file", {"path": "file.txt", "content": "lost"})])[0]
        self.assertTrue(removed.is_error)
        created = self.approved([ToolCall("new", "write_file", {"path": "nested/new.txt", "content": "created"})])[0]
        self.assertFalse(created.is_error, created.content)
        self.assertEqual((self.root / "nested/new.txt").read_text(), "created")
        self.assertEqual(list(self.root.rglob(".agent-write-*")), [])

    def test_workspace_escape_symlink_junction_and_write_traversal(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "private.txt").write_text("outside private marker", encoding="utf-8")
        self.make_directory_link(outside, self.root / "external-link")
        inside = self.root / "inside"
        inside.mkdir()
        (inside / "file.txt").write_text("inside", encoding="utf-8")
        self.make_directory_link(inside, self.root / "internal-link")
        for path in ("../outside/private.txt", str(outside / "private.txt"), "external-link/private.txt"):
            with self.subTest(path=path):
                self.assertTrue(self.execute("read_file", path=path).is_error)
                result = self.approved([ToolCall("escape", "write_file", {"path": path, "content": "bad"})])[0]
                self.assertTrue(result.is_error)
        self.assertFalse(self.execute("read_file", path="internal-link/file.txt").is_error)
        result = self.approved([ToolCall("link-write", "write_file", {
            "path": "internal-link/file.txt", "content": "bad",
        })])[0]
        self.assertTrue(result.is_error)
        self.assertEqual((inside / "file.txt").read_text(), "inside")
        self.assertEqual((outside / "private.txt").read_text(), "outside private marker")
        listing = self.execute("list_files")
        self.assertIn("external-link [symlink; not traversed]", listing.content)
        self.assertIn("internal-link [symlink; not traversed]", listing.content)

    def test_real_rg_search_glob_ignore_errors_and_truncation(self):
        self.assertIsNotNone(shutil.which("rg"), "real ripgrep must be installed")
        (self.root / ".git").mkdir()  # actual rg .gitignore semantics
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.root / "a.txt").write_text("first NEEDLE\nsecond needle\nthird needle\n", encoding="utf-8")
        (self.root / "b.py").write_text("needle python\n", encoding="utf-8")
        (self.root / "ignored.txt").write_text("needle ignored\n", encoding="utf-8")
        searched = self.execute("grep", pattern="needle", ignore_case=True)
        self.assertFalse(searched.is_error, searched.content)
        self.assertIn("a.txt:1:first NEEDLE", searched.content)
        self.assertIn("a.txt:3:third needle", searched.content)
        self.assertNotIn("ignored", searched.content)
        self.assertIn("b.py", searched.content)
        self.assertNotIn("truncated", searched.content)
        filtered = self.execute("grep", pattern="needle", ignore_case=True, glob="a.*")
        self.assertIn("a.txt:1:first NEEDLE", filtered.content)
        self.assertNotIn("b.py", filtered.content)
        limited = self.execute("grep", pattern="needle", path="a.txt", ignore_case=True, max_results=1)
        self.assertIn("truncated", limited.content)
        archive = Path(limited.content.split("full search output: ")[1].split("]")[0])
        self.assertIn("a.txt:3:third needle", archive.read_text(encoding="utf-8"))
        found = self.execute("glob", pattern="*.py")
        self.assertFalse(found.is_error, found.content)
        self.assertIn("b.py", found.content)
        self.assertNotIn("a.txt", found.content)
        self.assertEqual(self.execute("grep", pattern="no-such-contents").content, "No matches.")
        self.assertTrue(self.execute("grep", pattern="[").is_error)
        literal = self.execute("grep", pattern="[", literal=True)
        self.assertFalse(literal.is_error, literal.content)
        outside = self.base / "rg-outside"
        outside.mkdir()
        (outside / "private.txt").write_text("unique-external-secret", encoding="utf-8")
        self.make_directory_link(outside, self.root / "rg-link")
        self.assertEqual(self.execute("grep", pattern="unique-external-secret").content, "No matches.")
        self.assertTrue(self.execute("grep", pattern="needle", path="rg-link").is_error)


class SchedulerTests(ToolFilesTestCase):
    def test_manager_directly_rejects_any_non_readonly_or_approval_tool(self):
        def write(arguments):
            (self.root / "side-effect.txt").write_text(arguments["text"], encoding="utf-8")
            return ToolResult(True, "written")

        schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
        for readonly, approval in ((False, False), (False, True), (True, True)):
            definition = ToolDefinition("write", "Actual local file writer", schema, write,
                                        is_read_only=readonly, requires_approval=approval)
            manager = ToolManager([definition], output_dir=self.output)
            result = manager.execute(ToolCall("direct", "write", {"text": "never"}))
            self.assertTrue(result.is_error)
            self.assertIn("permission denied", result.content)
            self.assertFalse((self.root / "side-effect.txt").exists())
            refused = ToolScheduler(manager).execute_batch([ToolCall("no-store", "write", {"text": "never"})])[0]
            self.assertTrue(refused.is_error)
        allowed = self.approved([ToolCall("approved", "write", {"text": "yes"})], manager=manager)[0]
        self.assertFalse(allowed.is_error)
        self.assertEqual((self.root / "side-effect.txt").read_text(), "yes")

    def test_real_thread_approve_deny_expire_cancel_and_abort(self):
        for action in ("approve", "deny", "expire", "cancel", "abort"):
            with self.subTest(action=action):
                store = ApprovalStore()
                aborted = threading.Event()
                events = []
                scheduler = ToolScheduler(self.manager, store, emit=lambda event, **data: events.append(event),
                                          approval_timeout=0.15 if action == "expire" else 2,
                                          is_aborted=aborted.is_set)
                path = self.root / (action + ".txt")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(scheduler.execute_batch, [ToolCall(action, "write_file", {
                        "path": path.name, "content": action,
                    })])
                    request = wait_for(store.pending)[0]
                    if action in {"approve", "deny"}:
                        self.assertTrue(store.resolve(request.id, action == "approve"))
                        self.assertFalse(store.resolve(request.id, True))
                    elif action == "cancel":
                        self.assertTrue(store.cancel(request.id))
                        self.assertFalse(store.resolve(request.id, True))
                    elif action == "abort":
                        aborted.set()
                    else:
                        wait_for(lambda: not store.pending())
                        self.assertFalse(store.resolve(request.id, True))
                    result = future.result(timeout=3)[0]
                self.assertEqual(path.exists(), action == "approve")
                self.assertEqual(result.is_error, action != "approve")
                if action != "approve":
                    self.assertIn({"deny": "denied", "expire": "expired", "cancel": "cancelled",
                                   "abort": "cancelled"}[action], result.content)
                self.assertEqual(events, ["tool_start", "approval_required", "tool_end"])
                self.assertEqual(store.pending(), [])

    def test_event_and_pending_snapshots_cannot_change_approved_arguments(self):
        store = ApprovalStore()
        original = ToolCall("snapshot", "write_file", {"path": "original.txt", "content": "original"})
        events = []

        def emit(event, **data):
            events.append(event)
            data["tool_call"].arguments.update(path="event-mutated.txt", content="bad event")

        scheduler = ToolScheduler(self.manager, store, emit=emit, approval_timeout=2)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(scheduler.execute_batch, [original])
            request = wait_for(store.pending)[0]
            self.assertEqual(request.tool_call.arguments, {"path": "original.txt", "content": "original"})
            request.tool_call.arguments["content"] = "bad pending"
            original.arguments.update(path="caller-mutated.txt", content="bad caller")
            self.assertEqual(store.pending()[0].tool_call.arguments["content"], "original")
            self.assertTrue(store.resolve(request.id, True))
            result = future.result(timeout=3)[0]
        self.assertFalse(result.is_error, result.content)
        self.assertEqual((self.root / "original.txt").read_text(), "original")
        self.assertFalse((self.root / "event-mutated.txt").exists())
        self.assertFalse((self.root / "caller-mutated.txt").exists())
        self.assertEqual(events, ["tool_start", "approval_required", "tool_end"])

    def test_parallel_completion_callbacks_request_order_and_write_barrier(self):
        (self.root / "input.txt").write_text("real input", encoding="utf-8")
        slow_started = threading.Event()
        fast_reported = threading.Event()
        finished = []
        lock = threading.Lock()

        def read(args):
            phase = args["phase"]
            if phase == "slow":
                slow_started.set()
                if not fast_reported.wait(2):
                    raise RuntimeError("reads did not execute concurrently")
            elif phase == "fast":
                if not slow_started.wait(2):
                    raise RuntimeError("first read never started")
            path = self.root / ("barrier.txt" if phase == "after" else "input.txt")
            content = path.read_text(encoding="utf-8")
            with lock:
                finished.append(phase)
            return ToolResult(True, content)

        def write(args):
            with lock:
                if set(finished) != {"slow", "fast"}:
                    raise RuntimeError("write crossed read barrier")
            (self.root / "barrier.txt").write_text("after write", encoding="utf-8")
            return ToolResult(True, "written")

        manager = ToolManager([
            ToolDefinition("read", "Read actual local file with a host-controlled I/O gate", {
                "type": "object", "properties": {"phase": {"type": "string"}}, "required": ["phase"],
            }, read),
            ToolDefinition("write", "Actual local file writer", {"type": "object"}, write, is_read_only=False),
        ], output_dir=self.output)
        callbacks = []

        def on_result(result):
            callbacks.append(result.tool_call_id)
            if result.tool_call_id == "fast":
                fast_reported.set()

        calls = [ToolCall("slow", "read", {"phase": "slow"}), ToolCall("fast", "read", {"phase": "fast"}),
                 ToolCall("write", "write"), ToolCall("after", "read", {"phase": "after"})]
        results = self.approved(calls, manager=manager, on_result=on_result)
        self.assertEqual(callbacks, ["fast", "slow", "write", "after"])
        self.assertEqual([r.tool_call_id for r in results], ["slow", "fast", "write", "after"])
        self.assertFalse(any(r.is_error for r in results), results)
        self.assertEqual(results[-1].content, "after write")

    def test_observation_exceptions_do_not_lose_side_effect_results_or_later_calls(self):
        def emit(event, **data):
            if event == "tool_end":
                raise RuntimeError("host event observer failed")

        persisted = []

        def on_result(result):
            persisted.append(result.tool_call_id)

        with self.assertLogs("agent_core.tools.scheduler", level="WARNING"):
            results = self.approved([
                ToolCall("first", "write_file", {"path": "first.txt", "content": "first"}),
                ToolCall("second", "write_file", {"path": "second.txt", "content": "second"}),
            ], emit=emit, on_result=on_result)
        self.assertEqual(persisted, ["first", "second"])
        self.assertFalse(any(r.is_error for r in results), results)
        self.assertEqual((self.root / "first.txt").read_text(), "first")
        self.assertEqual((self.root / "second.txt").read_text(), "second")
        # Failed approval notification must not authorize execution or leak pending requests.
        store = ApprovalStore()

        def failed_notification(event, **data):
            if event == "approval_required":
                raise RuntimeError("host notification failed")

        with self.assertLogs("agent_core.tools.scheduler", level="WARNING"):
            result = ToolScheduler(self.manager, store, emit=failed_notification).execute_batch([
                ToolCall("no", "write_file", {"path": "never.txt", "content": "no"}),
            ])[0]
        self.assertTrue(result.is_error)
        self.assertFalse((self.root / "never.txt").exists())
        self.assertEqual(store.pending(), [])

    def test_closed_real_session_store_is_a_fail_stop_durability_barrier(self):
        calls = [ToolCall("first", "write_file", {"path": "first.txt", "content": "first"}),
                 ToolCall("second", "write_file", {"path": "second.txt", "content": "second"})]
        session_path = self.base / "closed-session.jsonl"
        store = SessionStore(session_path)
        self.addCleanup(store.close)
        context = ContextManager(session_store=store)
        context.append_message(UserMessage("write two files"))
        context.append_message(AssistantMessage(tool_calls=calls))
        store.close()  # Real closed writer, not a patched append implementation.
        with self.assertRaisesRegex(RuntimeError, "SessionStore is closed"):
            self.approved(calls, on_result=context.append_message)
        self.assertEqual((self.root / "first.txt").read_text(), "first")
        self.assertFalse((self.root / "second.txt").exists())
        self.assertFalse(any(isinstance(m, ToolResultMessage) for m in context.messages))
        with SessionStore(session_path) as reopened:
            restored = ContextManager(session_store=reopened)
            recovered = [m for m in restored.messages if isinstance(m, ToolResultMessage)]
            self.assertEqual([m.tool_call_id for m in recovered], ["first", "second"])
            self.assertTrue(all(m.is_error and "unknown" in m.content for m in recovered))
        self.assertFalse((self.root / "second.txt").exists())  # restore never replays a write

    def test_real_filesystem_commit_failure_stops_second_write(self):
        invalid_sink = self.base / "results.jsonl"
        invalid_sink.mkdir()  # Opening a directory for append is a real OS I/O error.
        observed = []

        def persist(result):
            observed.append(result)
            with invalid_sink.open("a", encoding="utf-8") as stream:
                stream.write(result.content + "\n")

        with self.assertRaises(OSError):
            self.approved([
                ToolCall("first", "write_file", {"path": "first.txt", "content": "first"}),
                ToolCall("second", "write_file", {"path": "second.txt", "content": "second"}),
            ], on_result=persist)
        self.assertEqual([m.tool_call_id for m in observed], ["first"])
        self.assertFalse(observed[0].is_error)  # real first result reached the commit callback
        self.assertEqual((self.root / "first.txt").read_text(), "first")
        self.assertFalse((self.root / "second.txt").exists())

    def test_batch_preflight_rejects_all_before_any_write(self):
        invalid_calls = [
            ToolCall("invalid", "write_file", {"path": "bad.txt", "content": 123}),
            ToolCall("invalid", "read_file", {"path": "missing", "offset": True}),
            ToolCall("invalid", "read_file", {"path": "missing", "offset": 10 ** 1000}),
            ToolCall("invalid", "read_file", {"path": "missing", "extra": 1}),
            ToolCall("invalid", "bash", {"shell": "powershell", "command": "exit", "timeout": float("nan")}),
            ToolCall("invalid", "unknown"), ToolCall("invalid", "not.a.tool"),
            ToolCall("first", "read_file", {"path": "missing"}),
        ]
        for invalid in invalid_calls:
            with self.subTest(invalid=invalid):
                store = ApprovalStore()
                events, reported = [], []
                results = ToolScheduler(self.manager, store, emit=lambda event, **data: events.append(event)).execute_batch([
                    ToolCall("first", "write_file", {"path": "never.txt", "content": "no partial writes"}), invalid,
                ], on_result=reported.append)
                self.assertEqual(len(results), 2)
                self.assertEqual(reported, results)
                self.assertTrue(all(r.is_error and "batch rejected" in r.content for r in results))
                self.assertFalse((self.root / "never.txt").exists())
                self.assertEqual(store.pending(), [])
                self.assertEqual(events, ["tool_start", "tool_end", "tool_start", "tool_end"])
        with self.assertRaisesRegex(ValueError, "unsupported"):
            validate({"path": "a"}, {"type": "object", "oneOf": []})

    def test_sequential_and_legacy_serial_and_pre_cancel(self):
        path = self.root / "read.txt"
        path.write_text("read", encoding="utf-8")
        for mode in ("sequential", "serial"):
            events, callbacks = [], []
            scheduler = ToolScheduler(self.manager, mode=mode,
                                      emit=lambda event, **data: events.append((event, data["tool_call"].id)))
            results = scheduler.execute_batch([
                ToolCall("one", "read_file", {"path": "read.txt"}),
                ToolCall("two", "read_file", {"path": "read.txt"}),
            ], on_result=lambda result: callbacks.append(result.tool_call_id))
            self.assertFalse(any(r.is_error for r in results))
            self.assertEqual(events, [("tool_start", "one"), ("tool_end", "one"),
                                      ("tool_start", "two"), ("tool_end", "two")])
            self.assertEqual(callbacks, ["one", "two"])
        cancelled = ToolScheduler(self.manager, is_aborted=lambda: True).execute_batch([
            ToolCall("cancelled", "write_file", {"path": "no.txt", "content": "no"}),
        ])[0]
        self.assertIn("cancelled", cancelled.content)
        self.assertFalse((self.root / "no.txt").exists())


class ProcessTests(ToolFilesTestCase):
    def run_python(self, source, **kwargs):
        return run_process([sys.executable, "-u", "-c", source], cwd=self.root,
                           output_dir=self.output, **kwargs)

    def test_real_stdout_stderr_nonzero_and_bounded_disk_output(self):
        normal = self.run_python("import sys; print('stdout'); print('stderr', file=sys.stderr); sys.exit(7)")
        self.assertEqual(normal.status, "completed")
        self.assertEqual(normal.exit_code, 7)
        self.assertIn("stdout", normal.preview)
        self.assertIn("stderr", normal.path.read_text(encoding="utf-8"))
        capped = self.run_python("import os; os.write(1, b'x' * 1000000)", disk_cap=8192, preview_chars=31)
        self.assertEqual(capped.status, "output_limit")
        self.assertEqual(capped.bytes_written, 8192)
        self.assertEqual(capped.path.stat().st_size, 8192)
        self.assertEqual(len(capped.preview), 31)
        self.assertIn("disk limit exceeded", capped.render())
        self.assertEqual(list(self.output.glob(".process-*")), [])
        with self.assertRaises(ValueError):
            self.run_python("print('never')", timeout=float("nan"))

    def test_output_is_streamed_before_exit_and_cancelled(self):
        aborted = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.run_python,
                                     "import os,time; os.write(1, b'streamed' * 256); time.sleep(30)",
                                     is_aborted=aborted.is_set, timeout=5, preview_chars=23)
            try:
                temporary = wait_for(lambda: next((p for p in self.output.glob(".process-*")
                                                   if p.stat().st_size > 100), None))
                self.assertGreater(temporary.stat().st_size, 100)
                self.assertFalse(future.done())
            finally:
                aborted.set()
            result = future.result(timeout=7)
        self.assertEqual(result.status, "cancelled")
        self.assertLessEqual(len(result.preview), 23)
        self.assertEqual(result.path.stat().st_size, result.bytes_written)
        self.assertEqual(list(self.output.glob(".process-*")), [])

    def test_inherited_credentials_stripped_and_split_output_redacted(self):
        name, secret = "AGENT_TOOLS_TEST_TOKEN", "only-for-real-subprocess-redaction-0123456789"
        old = os.environ.get(name)
        os.environ[name] = secret
        try:
            self.assertNotIn(name, process_environment())
            result = self.run_python(
                f"import os,time; print(os.environ.get({name!r}, 'absent'), flush=True); "
                f"os.write(1, {secret[:17].encode()!r}); time.sleep(.03); "
                f"os.write(1, {secret[17:].encode()!r})"
            )
        finally:
            if old is None:
                del os.environ[name]
            else:
                os.environ[name] = old
        text = result.path.read_text(encoding="utf-8")
        self.assertIn("absent", text)
        self.assertIn("[REDACTED]", text)
        self.assertNotIn(secret, text)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object lifetime integration")
    def test_windows_timeout_and_cancel_kill_actual_descendant_tree(self):
        leaf = (
            "import os,pathlib,sys,time; "
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
            "heartbeat=pathlib.Path(sys.argv[2]); "
            "\nwhile True:\n heartbeat.write_text(str(time.monotonic())); time.sleep(.02)\n"
        )
        for action in ("timeout", "cancel", "parent_exit"):
            with self.subTest(action=action):
                child_pid = self.root / (action + "-child.pid")
                leaf_pid = self.root / (action + "-leaf.pid")
                parent_pid = self.root / (action + "-parent.pid")
                heartbeat = self.root / (action + "-heartbeat.txt")
                child = (
                    "import os,pathlib,subprocess,sys,time; "
                    f"subprocess.Popen([sys.executable,'-u','-c',{leaf!r},{str(leaf_pid)!r},{str(heartbeat)!r}]); "
                    f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid())); time.sleep(30)"
                )
                parent = (
                    "import os,pathlib,subprocess,sys,time; "
                    f"pathlib.Path({str(parent_pid)!r}).write_text(str(os.getpid())); "
                    f"subprocess.Popen([sys.executable,'-u','-c',{child!r}]); "
                    f"\nwhile not pathlib.Path({str(leaf_pid)!r}).exists(): time.sleep(.01)\n"
                    + ("print('parent exited',flush=True)" if action == "parent_exit" else "time.sleep(30)")
                )
                aborted = threading.Event()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self.run_python, parent, timeout=1.5,
                                             is_aborted=aborted.is_set)
                    try:
                        wait_for(lambda: leaf_pid.exists() and leaf_pid.stat().st_size > 0)
                    finally:
                        if action == "cancel":
                            aborted.set()
                    result = future.result(timeout=7)
                self.assertEqual(result.status, {"timeout": "timed_out", "cancel": "cancelled",
                                                 "parent_exit": "completed"}[action])
                self.assertFalse(process_alive(int(parent_pid.read_text())))
                self.assertFalse(process_alive(int(child_pid.read_text())))
                self.assertFalse(process_alive(int(leaf_pid.read_text())))
                # No surviving process can keep changing the real file.
                if heartbeat.exists():
                    stamp = heartbeat.read_bytes()
                    threading.Event().wait(.06)
                    self.assertEqual(heartbeat.read_bytes(), stamp)

    def test_explicit_shell_requires_approval_and_real_exit_status(self):
        shell = "powershell" if os.name == "nt" else "sh"
        self.assertIsNotNone(shutil.which(shell))
        command = "Write-Output 'tool-command-ok'" if os.name == "nt" else "printf tool-command-ok"
        denied = self.execute("bash", shell=shell, command=command)
        self.assertTrue(denied.is_error)
        result = self.approved([ToolCall("shell", "bash", {"shell": shell, "command": command})])[0]
        self.assertFalse(result.is_error, result.content)
        self.assertIn("tool-command-ok", result.content)
        self.assertIn("status=completed", result.content)
        nonzero = self.approved([ToolCall("nonzero", "bash", {"shell": shell, "command": "exit 7"})])[0]
        self.assertTrue(nonzero.is_error)
        self.assertIn("exit_code=7", nonzero.content)
        for command in ("echo\u2003bad", "echo\x00bad"):
            result = self.approved([ToolCall("invalid", "bash", {"shell": shell, "command": command})])[0]
            self.assertTrue(result.is_error)


if __name__ == "__main__":
    unittest.main()
