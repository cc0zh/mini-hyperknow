"""Exercise real tool handlers only on pre-network rejection paths."""

from pathlib import Path
import hashlib
import json
import tempfile
from threading import Event
from time import monotonic
import unittest

from agent_core.types import AgentContext, ToolCall, UserMessage
from hyperknow.config import Settings
from hyperknow.domain import AppError
from hyperknow.research import (
    CONTEXT_BUDGET, OUTPUT_RESERVE, REPORT_MARGIN, Researcher, fit_page, fit_search,
    research_prompt, tool_byte_budget,
)
from hyperknow.research_web import WebError
from hyperknow.storage import Database


class ResearchAdmissionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="research-admission-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.db = Database(root / "hyperknow.sqlite3")
        run = self.db.create_research("admission-research-command", "学习异步任务", "", "stored-model",
                                      configured=True, search_configured=True)
        self.run = self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.stopping = Event()
        self.researcher = Researcher(Settings(data_dir=root), self.db, self.stopping)
        self.researcher.run = self.run
        self.researcher.deadline = monotonic() + 300

    def test_cancel_and_shutdown_reject_tools_without_network_or_saved_sources(self):
        self.researcher.require_active()
        self.stopping.set()
        with self.assertRaises(AppError) as raised:
            self.researcher._execute("read_webpage", {"question_id": "q1", "url": "https://example.com/",
                                                       "query": "asyncio tasks", "provider": "page"})
        self.assertEqual(raised.exception.code, "run_inactive")
        self.stopping.clear()
        cancelled = self.db.transition(self.run["run_id"], {"generating"}, status="cancelled")
        with self.assertRaises(AppError):
            self.researcher.require_active()
        self.assertEqual(self.db.get_run(self.run["run_id"]), cancelled)
        self.assertEqual(self.db.calls(self.run["run_id"]), [])

    def test_deadline_and_failed_persistence_block_further_admission(self):
        self.researcher.deadline = monotonic() - 1
        with self.assertRaises(AppError) as raised:
            self.researcher.require_active()
        self.assertEqual(raised.exception.code, "research_budget_exceeded")
        self.researcher.deadline = monotonic() + 300
        self.researcher.persistence_failed = True
        with self.assertRaises(AppError) as raised:
            self.researcher.require_active()
        self.assertEqual(raised.exception.code, "research_storage_failed")

    def test_actual_loopback_tool_error_is_saved_not_promoted_to_source(self):
        result = self.researcher._tools().execute(ToolCall(
            "loopback-call", "read_webpage", {"question_id": "q1", "url": "http://127.0.0.1/",
                                                  "query": "asyncio tasks", "provider": "page"}))
        self.assertTrue(result.is_error)
        self.assertIn("unsafe_url", result.content)
        research = self.db.get_run(self.run["run_id"])["research"]
        self.assertEqual(research["sources"], [])
        self.assertEqual(len(research["steps"]), 1)
        self.assertEqual(research["steps"][0]["status"], "failed")

    def test_search_and_read_budgets_include_failures_and_never_exceed_ten(self):
        # Missing key and literal loopback both fail before opening a socket.
        for _ in range(4):
            self.assertFalse(self.researcher._execute("web_search", {"question_id": "q1", "query": "asyncio",
                                                                      "provider": "tavily"}).success)
        for _ in range(6):
            self.assertFalse(self.researcher._execute("read_webpage", {"question_id": "q1",
                "url": "http://127.0.0.1/", "query": "asyncio", "provider": "page"}).success)
        before = self.db.get_run(self.run["run_id"])
        self.assertEqual(len(before["research"]["steps"]), 10)
        for tool, arguments in (("web_search", {"question_id": "q1", "query": "asyncio",
                                                  "provider": "tavily"}),
                                 ("read_webpage", {"question_id": "q1", "url": "https://example.com/",
                                                    "query": "asyncio", "provider": "page"})):
            result = self.researcher._execute(tool, arguments)
            self.assertFalse(result.success)
            self.assertIn("budget", result.error)
        self.assertEqual(self.db.get_run(self.run["run_id"]), before)
        self.assertEqual(before["research"]["sources"], [])

    def test_tool_schema_rejects_invalid_arguments_without_spending_budget(self):
        tools = self.researcher._tools()
        for call in (ToolCall("short-query", "web_search", {"question_id": "q1", "query": "x",
                                                               "provider": "tavily"}),
                     ToolCall("extra-argument", "read_webpage", {"question_id": "q1",
                         "url": "https://example.com", "query": "asyncio", "provider": "page", "execute": True}),
                     ToolCall("unknown-tool", "bash", {"command": "never executed"})):
            self.assertTrue(tools.execute(call).is_error)
        self.assertEqual(self.researcher.counts, {"web_search": 0, "read_webpage": 0})
        self.assertEqual(self.db.get_run(self.run["run_id"])["research"]["steps"], [])

    def test_keys_are_excluded_from_configuration_repr(self):
        settings = Settings(data_dir=Path("data"), api_key="model-key-not-sent",
                            tavily_api_key="search-key-not-sent", exa_api_key="exa-key-not-sent")
        self.assertNotIn("model-key-not-sent", repr(settings))
        self.assertNotIn("search-key-not-sent", repr(settings))
        self.assertNotIn("exa-key-not-sent", repr(settings))

    def test_exa_provider_is_exposed_without_networking_and_still_rejects_loopback(self):
        settings = Settings(data_dir=Path(self.db.path).parent, exa_api_key="exa-local-test-key")
        researcher = Researcher(settings, self.db, self.stopping)
        researcher.run = self.run
        researcher.deadline = monotonic() + 300
        result = researcher._tools().execute(ToolCall("unsafe-exa", "read_webpage", {
            "question_id": "q1", "url": "http://127.0.0.1/private", "query": "asyncio",
            "provider": "exa"}))
        self.assertTrue(result.is_error)
        self.assertIn("unsafe_url", result.content)
        self.assertNotIn("exa-local-test-key", result.content)
        self.assertEqual(researcher.counts["read_webpage"], 1)

    def test_maximum_chinese_input_fits_but_escaped_input_is_rejected_before_calls(self):
        self.researcher.validate_input("中" * 4000, "文" * 6000)
        with self.assertRaises(AppError) as raised:
            self.researcher.validate_input("\x00" * 4000, "\x00" * 6000)
        self.assertEqual(raised.exception.code, "context_too_large")
        self.assertEqual(self.db.calls(self.run["run_id"]), [])

    def test_page_budget_uses_serialized_utf8_and_updates_excerpt_hash(self):
        text = '中文"\\\n' * 2000
        page = {"url": "https://example.com/", "title": "文档", "text": text,
                "truncated": False, "fetched_at": "2026-10-23T00:00:00+00:00", "content_sha256": "original"}
        fitted = fit_page(page, 5000)
        payload = json.dumps({"source_id": "source_" + "0" * 32, **fitted}, ensure_ascii=False).encode("utf-8")
        self.assertLessEqual(len(payload), 5000)
        self.assertTrue(fitted["truncated"])
        self.assertEqual(fitted["content_sha256"], hashlib.sha256(fitted["text"].encode()).hexdigest())
        self.assertTrue(text.startswith(fitted["text"]))
        self.assertEqual(page["text"], text)
        with self.assertRaises(WebError):
            fit_page(page, 100)

    def test_search_clipping_keeps_explicit_discovery_and_truncation_labels(self):
        items = [{"url": f"https://example.com/{index}", "title": "标题" * 150, "snippet": "摘要" * 400}
                 for index in range(5)]
        payload = fit_search(items, 4096)
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode()), 4096)
        self.assertTrue(payload["truncated"])
        self.assertIn("not read page", payload["notice"])
        self.assertTrue(payload["results"])

    def test_tool_budget_leaves_space_for_report_and_declines_more_evidence(self):
        from agent_core.tokens import TokenEstimator
        context = AgentContext(research_prompt(), [UserMessage("学习目标")])
        admitted = 0
        while admitted < 10:
            budget = tool_byte_budget(context)
            if budget < 4096:
                break
            page = {"url": "https://example.com/", "title": "资料", "text": "中文" * 3000,
                    "truncated": False, "content_sha256": "original", "fetched_at": "now"}
            fitted = fit_page(page, budget)
            context.messages.append(UserMessage(json.dumps(fitted, ensure_ascii=False)))
            used = TokenEstimator().estimate(context, reserve_output_tokens=OUTPUT_RESERVE).total_tokens
            self.assertLess(used, CONTEXT_BUDGET)
            self.assertGreater(CONTEXT_BUDGET - used, REPORT_MARGIN - 1000)
            admitted += 1
        self.assertGreater(admitted, 0)
        self.assertLess(admitted, 10)
        self.assertLess(tool_byte_budget(context), 4096)
