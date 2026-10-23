"""Pure UTF-8 budgets and real SQLite contention; no model/provider stand-ins."""

import asyncio
from copy import deepcopy
import json
import logging
from pathlib import Path
import tempfile
import unittest

from agent_core.tokens import TokenEstimator
from agent_core.types import AgentContext, UserMessage

from hyperknow.blueprint_domain import UnitExpansionDraft, planning_context
from hyperknow.config import Settings
from hyperknow.domain import AppError
from hyperknow.generation import (PLANNING_CONTEXT_BUDGET, PLANNING_OUTPUT_RESERVE,
                                 PLANNING_REPAIR_RESERVE, bounded_repair_message)
from hyperknow.runtime import CourseService, EventHub
from hyperknow.storage import Database
import test_blueprint


def json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def planning_inputs(completed_sessions=53, title="长" * 200):
    """A 60-session approved plan, seven expanded units and one current unit."""
    units = []
    for index in range(8):
        count = completed_sessions // 7 + (index < completed_sessions % 7) if index < 7 else 60 - completed_sessions
        units.append({"unit_id": f"unit-{index}", "title": title, "description": "掌握任务调度和取消边界。",
                      "learning_objectives": ["区分协程、任务与调度器"], "estimated_sessions": count,
                      "project_keys": [], "exam_goal": "保留批准的考核目标" if index == 7 else "",
                      "generation_status": "ready" if index < 7 else "generating",
                      "lectures": [{"title": title, "sessions": [
                          {"title": title} for _ in range(min(4, count - offset))]}
                          for offset in range(0, count, 4)] if index < 7 else [],
                      "exams": [], "project_stages": []})
    course = {"blueprint_version": 3, "title": "Python异步编程", "language": "zh-CN",
              "projects": [], "units": units}
    run = {"goal": "理解异步" * 1000, "questions": [{"id": "level", "text": "基础？"}],
           "answers": {"level": "会Python"}, "skipped": False, "stage": "units",
           "current_unit_id": "unit-7", "blueprint_feedback": "侧重取消传播，不改批准的目标。",
           "research": {"report": {"summary": "协程暂停与任务调度的资料结论。", "source_refs": ["source-1"]},
                        "sources": [{"source_id": f"source-{index}", "url": f"https://example.org/{index}",
                                     "title": "任务文档", "content_sha256": str(index) * 64,
                                     "text": "资料😀\n\t\r\x00\b\"\\" * 8000} for index in (1, 2)]}}
    return run, course


class PlanningBudgetTests(unittest.TestCase):
    def test_sixty_session_plan_with_long_utf8_titles_preserves_required_inputs(self):
        for count in (53, 59):
            for title in ("长" * 200, ("中😀\"\\\n\x00" * 40)[:200]):
                with self.subTest(completed_sessions=count, title=repr(title[:8])):
                    run, course = planning_inputs(count, title)
                    original = deepcopy((run, course))
                    context = planning_context(run, course, budget=36000)
                    self.assertLessEqual(json_bytes(context), 36000)
                    self.assertEqual(sum(u["estimated_sessions"] for u in course["units"]), 60)
                    for key, value in (("goal", run["goal"]), ("questions", run["questions"]),
                                       ("answers", run["answers"]), ("feedback", run["blueprint_feedback"]),
                                       ("research_report", run["research"]["report"]), ("unit", course["units"][-1])):
                        self.assertEqual(context[key], value)
                    history = context["expanded_units_excerpt"]
                    self.assertTrue(history["context_truncated"])
                    self.assertEqual(history["total_items"], 7)
                    self.assertLessEqual(json_bytes(history), history["byte_limit"])
                    self.assertLessEqual(json_bytes(context["unit_sequence_excerpt"]), 6000)
                    for excerpt, source in zip(context["sources"], run["research"]["sources"]):
                        self.assertTrue(excerpt["context_excerpt"])
                        self.assertTrue(excerpt["context_truncated"])
                        self.assertTrue(source["text"].startswith(excerpt["context_excerpt"]))
                        self.assertEqual(excerpt["source_id"], source["source_id"])
                        self.assertEqual(excerpt["content_sha256"], source["content_sha256"])
                    self.assertEqual((run, course), original)

    def test_large_global_sequence_is_explicitly_an_excerpt_not_a_changed_approved_unit(self):
        run, course = planning_inputs()
        course["units"][0]["learning_objectives"] = ["其他单元的很长目标" * 10000]
        original = deepcopy((run, course))
        context = planning_context(run, course, budget=30000)
        self.assertTrue(context["unit_sequence_excerpt"]["context_truncated"])
        self.assertEqual(context["unit_sequence_excerpt"]["total_items"], 8)
        self.assertEqual(context["unit"], course["units"][-1])
        self.assertLessEqual(json_bytes(context), 30000)
        self.assertEqual((run, course), original)

    def test_required_overflow_is_rejected_instead_of_silently_truncated(self):
        for field in ("goal", "feedback", "report", "current_objectives"):
            with self.subTest(field=field):
                run, course = planning_inputs()
                run["goal"] = "理解异步"
                text = "必须完整保留😀\"\\\n" * 2000
                if field == "goal":
                    run["goal"] = text
                elif field == "feedback":
                    run["blueprint_feedback"] = text
                elif field == "report":
                    run["research"]["report"]["summary"] = text
                else:
                    course["units"][-1]["learning_objectives"] = [text]
                original = deepcopy((run, course))
                with self.assertRaises(AppError) as raised:
                    planning_context(run, course, budget=6000)
                self.assertEqual(raised.exception.code, "context_too_large")
                self.assertEqual((run, course), original)

    def test_source_truncation_counts_json_escapes_and_leaves_original_text_intact(self):
        run, _ = planning_inputs()
        run.update(stage="blueprint", goal="理解任务取消")
        original = deepcopy(run)
        context = planning_context(run, budget=4000)
        self.assertLessEqual(json_bytes(context), 4000)
        self.assertEqual(context["research_report"], run["research"]["report"])
        for excerpt, source in zip(context["sources"], run["research"]["sources"]):
            self.assertTrue(excerpt["context_truncated"])
            self.assertTrue(excerpt["context_excerpt"])
            self.assertLessEqual(len(excerpt["context_excerpt"].encode("utf-8")), 6000)
            self.assertEqual(excerpt["stored_excerpt_bytes"], len(source["text"].encode("utf-8")))
            self.assertTrue(source["text"].startswith(excerpt["context_excerpt"]))
        self.assertEqual(run, original)


class RepairBudgetTests(unittest.TestCase):
    def added_bytes(self, message):
        estimator = TokenEstimator()
        system = "系统/Schema必须计入\"\\\n" * 20
        initial = UserMessage("原输入😀\"\\\n" * 20)
        before = estimator.estimate(AgentContext(system, [initial])).input_tokens
        after = estimator.estimate(AgentContext(system, [initial, message])).input_tokens
        return after - before

    def test_small_repair_preserves_complete_response_and_error(self):
        response, error = '{"title": "异步😀\\n\\\""}', '校验错误："缺少目标"\n'
        message = bounded_repair_message(response, error)
        payload = json.loads(message.content)
        self.assertEqual(payload["response_excerpt"], response)
        self.assertEqual(payload["validation_error_excerpt"], error)
        self.assertFalse(payload["response_truncated"])
        self.assertFalse(payload["validation_error_truncated"])
        self.assertFalse(payload["response_omitted"])
        self.assertIn("完整JSON", payload["instruction"])
        self.assertLessEqual(self.added_bytes(message), PLANNING_REPAIR_RESERVE)

    def test_large_cjk_and_escaped_repairs_are_bounded_after_all_serialization(self):
        for text in ("长标题😀" * 10000, '\"\\\n\r\t\b\x00中' * 10000):
            for budget in (1000, 2000, PLANNING_REPAIR_RESERVE):
                with self.subTest(text=repr(text[:8]), budget=budget):
                    message = bounded_repair_message(text, text, budget=budget)
                    payload = json.loads(message.content)
                    self.assertLessEqual(self.added_bytes(message), budget)
                    self.assertLessEqual(len(payload["validation_error_excerpt"].encode("utf-8")), 6000)
                    self.assertTrue(payload["validation_error_truncated"])
                    self.assertTrue(payload["response_truncated"])
                    self.assertEqual(payload["response_omitted"], not payload["response_excerpt"])
                    self.assertTrue(text.startswith(payload["response_excerpt"]))
                    self.assertTrue(text.startswith(payload["validation_error_excerpt"]))
                    self.assertIn("重新生成完整JSON", payload["instruction"])

    def test_too_small_budget_fails_without_returning_an_unbounded_message(self):
        with self.assertRaises(ValueError):
            bounded_repair_message("响应", "错误", budget=50)

    def test_initial_and_repair_requests_fit_system_schema_messages_and_output_reserves(self):
        for title in ("长" * 200, ("中😀\"\\\n\x00" * 40)[:200]):
            with self.subTest(title=repr(title[:8])):
                run, course = planning_inputs(title=title)
                system = "只生成当前批准的单元。\n" + json.dumps(UnitExpansionDraft.model_json_schema(), ensure_ascii=False)
                estimator = TokenEstimator()
                overhead = estimator.estimate(AgentContext(system, [UserMessage("")])).input_tokens
                reserve = PLANNING_OUTPUT_RESERVE + PLANNING_REPAIR_RESERVE
                budget = PLANNING_CONTEXT_BUDGET - overhead - reserve - 512
                user = planning_context(run, course, budget=budget)
                initial = UserMessage(json.dumps(user, ensure_ascii=False))
                estimate = estimator.estimate(AgentContext(system, [initial]), reserve_output_tokens=reserve)
                if estimate.total_tokens > PLANNING_CONTEXT_BUDGET:
                    budget -= estimate.total_tokens - PLANNING_CONTEXT_BUDGET + 256
                    user = planning_context(run, course, budget=budget)
                    initial = UserMessage(json.dumps(user, ensure_ascii=False))
                self.assertLessEqual(estimator.estimate(AgentContext(system, [initial]),
                                     reserve_output_tokens=reserve).total_tokens, PLANNING_CONTEXT_BUDGET)
                repair = bounded_repair_message("原始响应😀\"\\\n\x00" * 20000, "很长的校验错误😀\"\\\n" * 20000)
                self.assertLessEqual(estimator.estimate(AgentContext(system, [initial, repair]),
                                     reserve_output_tokens=PLANNING_OUTPUT_RESERVE).total_tokens,
                                     PLANNING_CONTEXT_BUDGET)


class ReadFailureObserver(logging.Handler):
    def __init__(self):
        super().__init__()
        self.failed = asyncio.Event()
        self.records = []

    def emit(self, record):
        self.records.append(record)
        if record.getMessage().startswith("Committed run state read deferred"):
            self.failed.set()


class CommittedContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hyperknow-blueprint-budget-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "hyperknow.sqlite3"
        self.db = Database(self.path)
        self.service = CourseService(Settings(data_dir=Path(directory.name)), self.db, EventHub())
        self.helper = test_blueprint.BlueprintStorageTests()
        self.helper.db = self.db
        # Cancelling to_thread cancels the await, not SQLite's in-flight read.
        # Drain the real executor before Windows removes the temporary database.
        self.addAsyncCleanup(asyncio.get_running_loop().shutdown_default_executor)
        self.addAsyncCleanup(self.service.close)

    async def test_committed_continuation_starts_only_next_unit_and_ignores_terminal_runs(self):
        approved = self.helper.expanding()
        first = self.db.begin_unit(approved["run_id"])
        committed = self.db.finish_unit(first["run_id"], first["current_unit_id"],
                                      UnitExpansionDraft.model_validate(test_blueprint.expansion_input()))
        saved_unit = deepcopy(self.db.get_course(committed["course_id"])["units"][0])
        await self.service.continue_committed_run(committed["run_id"])
        entry = self.service.queue.get_nowait()
        self.assertEqual(entry, (committed["run_id"], "units"))
        self.service.enqueued.discard(entry)
        self.service.queue.task_done()
        second = self.db.begin_unit(committed["run_id"])
        self.assertNotEqual(second["current_unit_id"], first["current_unit_id"])
        self.assertEqual(self.db.get_course(committed["course_id"])["units"][0], saved_unit)
        self.db.transition(committed["run_id"], {"generating"}, status="failed")
        await self.service.continue_committed_run(committed["run_id"])
        self.assertTrue(self.service.queue.empty())
        self.assertEqual(self.db.calls(committed["run_id"]), [])
        self.service.accepting = False
        another = self.helper.research("after-shutdown")
        await self.service.continue_committed_run(another["run_id"])
        self.assertTrue(self.service.queue.empty())

    async def test_real_sqlite_timeout_retries_only_read_and_respects_latest_cancel(self):
        approved = self.helper.expanding()
        first = self.db.begin_unit(approved["run_id"])
        committed = self.db.finish_unit(first["run_id"], first["current_unit_id"],
                                      UnitExpansionDraft.model_validate(test_blueprint.expansion_input()))
        saved_unit = deepcopy(self.db.get_course(committed["course_id"])["units"][0])
        observer = ReadFailureObserver()
        logger = logging.getLogger("hyperknow.runtime")
        logger.addHandler(observer)
        self.addCleanup(logger.removeHandler, observer)
        self.service.worker = asyncio.create_task(self.service.work())
        with self.db.transaction() as conn:
            continuation = asyncio.create_task(self.service.continue_committed_run(committed["run_id"]))
            try:
                await asyncio.wait_for(observer.failed.wait(), timeout=8)
                self.assertFalse(continuation.done())
                self.assertTrue(self.service.queue.empty())
                # Persist a cancellation while retaining the write lock. The next
                # successful read must see it, not enqueue the committed snapshot.
                current = self.db._get(conn, "runs", committed["run_id"])
                current.update(status="cancelled", version=current["version"] + 1)
                self.db._save_run(conn, current)
            except BaseException:
                continuation.cancel()
                await asyncio.gather(continuation, return_exceptions=True)
                raise
        await asyncio.wait_for(continuation, timeout=3)
        self.assertTrue(self.service.queue.empty())
        self.assertFalse(self.service.worker.done())
        self.assertEqual(self.db.calls(committed["run_id"]), [])
        self.assertEqual(self.db.get_course(committed["course_id"])["units"][0], saved_unit)
        self.assertTrue(all(record.getMessage() == "Committed run state read deferred (OperationalError)"
                            for record in observer.records))
        # A separate committed workflow can still enqueue; make it terminal before
        # the real worker consumes it, so no provider or network is involved.
        another = self.helper.research("after-contention")
        await self.service.continue_committed_run(another["run_id"])
        self.db.transition(another["run_id"], {"generating"}, status="cancelled")
        await asyncio.wait_for(self.service.queue.join(), timeout=3)
        self.assertFalse(self.service.worker.done())
        self.assertEqual(self.db.calls(another["run_id"]), [])

    async def test_pending_sqlite_read_can_be_cancelled_without_waiting_for_lock_timeout(self):
        committed = self.helper.research()
        with self.db.transaction():
            task = asyncio.create_task(self.service.continue_committed_run(committed["run_id"]))
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=0.5)
        self.assertTrue(self.service.queue.empty())
        self.assertEqual(self.db.calls(committed["run_id"]), [])
