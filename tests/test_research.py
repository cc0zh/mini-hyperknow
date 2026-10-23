"""Direct domain inputs and real disk SQLite, not real web/model acceptance.

Page/step/report dictionaries below are explicit rule inputs, never responses
from a substitute search service or provider. No network requests are made.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from hyperknow.domain import AppError
from hyperknow.research_domain import ResearchReport, validate_report
from hyperknow.storage import Database


def report_input(source_id="source_test"):
    return {
        "summary": "协程学习顺序的规则测试输入",
        "findings": [{"title": "暂停与恢复", "summary": "先理解 await，再学习任务调度。",
                      "source_ids": [source_id]}],
        "suggested_sequence": ["认识协程", "理解 await", "比较任务调度"],
        "limitations": ["此内容仅用于校验规则，不代表真实网页调研。"],
    }


def page_input(url="https://docs.python.org/3/library/asyncio-task.html"):
    text = "Explicit test input: await suspends a coroutine."
    return {"url": url, "title": "Coroutines and Tasks — rule input", "text": text,
            "fetched_at": "2026-10-22T00:00:00+00:00", "truncated": True,
            "content_sha256": hashlib.sha256(text.encode()).hexdigest()}


def search_step(status="ready"):
    return {"tool": "web_search", "arguments": {"query": "Python asyncio tasks"},
            "status": status, "started_at": "2026-10-22T00:00:00+00:00", "elapsed_ms": 1,
            "results": [{"url": page_input()["url"], "title": "Search rule input",
                         "content": "A search snippet is not a read page."}]}


def read_step(url=None):
    return {"tool": "read_webpage", "arguments": {"url": url or page_input()["url"]},
            "status": "ready", "started_at": "2026-10-22T00:00:00+00:00", "elapsed_ms": 1}


class ResearchReportTests(unittest.TestCase):
    def test_report_round_trip_and_whitespace_normalization(self):
        data = report_input()
        data["summary"] = "  协程学习  "
        report = ResearchReport.model_validate(data)
        self.assertEqual(report.summary, "协程学习")
        self.assertEqual(ResearchReport.model_validate_json(report.model_dump_json()), report)

    def test_empty_duplicate_and_extra_fields_are_rejected(self):
        cases = [
            {"summary": " "}, {"findings": []}, {"suggested_sequence": []},
            {"suggested_sequence": [" "]}, {"limitations": [" "]}, {"unknown": True},
        ]
        for patch in ({"title": " "}, {"summary": " "}, {"source_ids": []},
                      {"source_ids": ["source_test", "source_test"]}, {"unknown": True}):
            cases.append({"findings": [{**report_input()["findings"][0], **patch}]})
        for patch in cases:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                ResearchReport.model_validate({**report_input(), **patch})

    def test_report_text_and_collection_budgets_are_enforced(self):
        data = report_input()
        cases = [
            {"summary": "x" * 4001}, {"findings": data["findings"] * 13},
            {"suggested_sequence": ["step"] * 13}, {"limitations": ["limit"] * 13},
        ]
        for patch in ({"title": "x" * 201}, {"summary": "x" * 2001},
                      {"source_ids": [f"source_{index}" for index in range(9)]}):
            cases.append({"findings": [{**data["findings"][0], **patch}]})
        for patch in cases:
            with self.subTest(field=next(iter(patch))), self.assertRaises(ValidationError):
                ResearchReport.model_validate({**data, **patch})

    def test_report_requires_successful_search_and_read_page_not_snippets(self):
        report = ResearchReport.model_validate(report_input())
        source = {**page_input(), "source_id": "source_test"}
        for steps, sources in (([], []), ([search_step()], []), ([], [source]),
                               ([search_step("failed")], [source])):
            with self.subTest(steps=steps, sources=sources), self.assertRaises(ValueError):
                validate_report(report, {"steps": steps, "sources": sources, "report": None})

    def test_only_read_source_ids_can_be_cited_and_inputs_are_not_mutated(self):
        research = {"steps": [search_step(), read_step()],
                    "sources": [{**page_input(), "source_id": "source_test"}], "report": None}
        before = deepcopy(research)
        report = ResearchReport.model_validate(report_input())
        self.assertIs(validate_report(report, research), report)
        for citation in ("source_unknown", page_input()["url"], "https://example.com/unread"):
            with self.subTest(citation=citation), self.assertRaises(ValueError):
                validate_report(ResearchReport.model_validate(report_input(citation)), research)
        mixed = report_input()
        mixed["findings"][0]["source_ids"].append("source_unknown")
        with self.assertRaises(ValueError):
            validate_report(ResearchReport.model_validate(mixed), research)
        self.assertEqual(research, before)


class ResearchStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hyperknow-research-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "hyperknow.sqlite3"
        self.db = Database(self.path)

    def create(self, command="create-research-1", **configuration):
        return self.db.create_research(
            command, "理解 Python 协程", "会基础 Python，关注调度顺序", "stored-model",
            **{"configured": True, "search_configured": True, **configuration})

    def generating(self, command="create-research-1"):
        run = self.create(command)
        return self.db.transition(run["run_id"], {"queued"}, status="generating")

    def evidence(self, run):
        self.db.research_step(run["run_id"], search_step())
        return self.db.research_step(run["run_id"], read_step(), page_input())

    def test_create_preserves_input_and_empty_research_after_reopening(self):
        run = self.create()
        self.assertEqual((run["kind"], run["status"], run["version"]), ("research", "queued", 1))
        self.assertEqual(run["input"], {"goal": run["goal"], "context": "会基础 Python，关注调度顺序"})
        self.assertEqual(run["research"], {"steps": [], "sources": [], "report": None})
        self.assertIsNone(run["parent_run_id"])
        self.assertIsNone(run["course_id"])
        reopened = Database(self.path)
        self.assertTrue(self.path.is_file())
        self.assertEqual(reopened.get_run(run["run_id"]), run)
        self.assertEqual(reopened.list_records("courses"), [])
        self.assertEqual(reopened.calls(run["run_id"]), [])

    def test_missing_configuration_creates_neither_run_nor_command_receipt(self):
        for index, (model, search, code) in enumerate((
            (False, False, "model_not_configured"), (False, True, "model_not_configured"),
            (True, False, "search_not_configured"),
        )):
            command = f"missing-configuration-{index}"
            with self.subTest(model=model, search=search):
                before = self.db.list_records("runs")
                with self.assertRaises(AppError) as raised:
                    self.create(command, configured=model, search_configured=search)
                self.assertEqual((raised.exception.code, raised.exception.status), (code, 503))
                self.assertEqual(self.db.list_records("runs"), before)
                with self.db.transaction() as conn:
                    self.assertIsNone(conn.execute(
                        "SELECT id FROM command_receipts WHERE id=?", (command,)).fetchone())
                self.assertEqual(self.create(command)["status"], "queued")

    def test_command_replay_ignores_new_model_and_missing_configuration(self):
        run = self.create()
        reopened = Database(self.path)
        replay = reopened.create_research("create-research-1", run["goal"], run["input"]["context"],
                                          "changed-default-model", configured=False, search_configured=False)
        self.assertEqual(replay, run)
        for goal, context in (("学习其他主题", run["input"]["context"]), (run["goal"], "不同背景")):
            with self.subTest(goal=goal, context=context), self.assertRaises(AppError) as raised:
                reopened.create_research("create-research-1", goal, context, run["model"],
                                         configured=True, search_configured=True)
            self.assertEqual((raised.exception.code, raised.exception.status), ("command_conflict", 409))
        with self.assertRaises(AppError) as raised:
            reopened.create_run("create-research-1", run["goal"], run["model"])
        self.assertEqual(raised.exception.code, "command_conflict")
        self.assertEqual(reopened.list_records("runs"), [run])

    def test_concurrent_identical_create_has_one_run(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(lambda _: self.create(), range(2)))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(self.db.list_records("runs"), [runs[0]])

    def test_steps_persist_page_fields_and_reuse_source_id_for_same_url(self):
        run = self.generating()
        step, page = read_step(), page_input()
        before_step, before_page = deepcopy(step), deepcopy(page)
        self.assertIsNone(self.db.research_step(run["run_id"], search_step("failed")))
        self.assertIsNone(self.db.research_step(run["run_id"], search_step()))
        source = self.db.research_step(run["run_id"], step, page)
        repeated = self.db.research_step(run["run_id"], step, {**page, "title": "Later input"})
        other_page = page_input("https://docs.python.org/3/library/asyncio-eventloop.html")
        other = self.db.research_step(run["run_id"], read_step(other_page["url"]), other_page)
        self.assertEqual(repeated, source)
        self.assertTrue(source["source_id"])
        self.assertNotEqual(source["source_id"], other["source_id"])
        self.assertEqual({key: source[key] for key in page}, page)
        saved = Database(self.path).get_run(run["run_id"])
        self.assertEqual(saved["research"]["sources"], [source, other])
        self.assertEqual(saved["research"]["steps"], [search_step("failed"), search_step(),
                         {**step, "source_id": source["source_id"]},
                         {**step, "source_id": source["source_id"]},
                         {**read_step(other_page["url"]), "source_id": other["source_id"]}])
        self.assertEqual(saved["version"], run["version"] + 5)
        self.assertEqual((step, page), (before_step, before_page))

    def test_step_budget_rejection_does_not_append_page_or_increment_version(self):
        run = self.generating()
        for _ in range(10):
            self.db.research_step(run["run_id"], search_step("failed"))
        before = self.db.get_run(run["run_id"])
        with self.assertRaises(AppError) as raised:
            self.db.research_step(run["run_id"], read_step(), page_input())
        self.assertEqual((raised.exception.code, raised.exception.status), ("research_budget_exceeded", 422))
        self.assertEqual(Database(self.path).get_run(run["run_id"]), before)

    def test_only_generating_research_accepts_steps_or_report(self):
        for status in ("queued", "failed", "cancelled", "interrupted", "ready"):
            with self.subTest(status=status):
                run = self.create(f"inactive-{status}")
                if status != "queued":
                    run = self.db.transition(run["run_id"], {"queued"}, status=status)
                with self.assertRaises(AppError) as raised:
                    self.db.research_step(run["run_id"], read_step(), page_input())
                self.assertEqual(raised.exception.code, "run_inactive")
                self.assertIsNone(self.db.finish_research(run["run_id"], ResearchReport.model_validate(report_input())))
                self.assertEqual(self.db.get_run(run["run_id"]), run)
        course = self.db.create_run("course-not-research", "理解协程", "stored-model")
        course = self.db.transition(course["run_id"], {"queued"}, status="generating")
        with self.assertRaises(AppError):
            self.db.research_step(course["run_id"], read_step(), page_input())
        self.assertIsNone(self.db.finish_research(course["run_id"], ResearchReport.model_validate(report_input())))
        self.assertEqual(self.db.get_run(course["run_id"]), course)

    def test_finish_revalidates_saved_evidence_and_rolls_back_invalid_report(self):
        for case in ("no_search", "failed_search", "no_page", "unknown_source", "url_citation"):
            with self.subTest(case=case):
                run = self.generating(f"invalid-report-{case}")
                if case != "no_search":
                    self.db.research_step(run["run_id"], search_step("failed" if case == "failed_search" else "ready"))
                source = None
                if case != "no_page":
                    source = self.db.research_step(run["run_id"], read_step(), page_input())
                citation = source["source_id"] if source else "source_missing"
                if case == "unknown_source":
                    citation = "source_unknown"
                elif case == "url_citation":
                    citation = page_input()["url"]
                before = self.db.get_run(run["run_id"])
                with self.assertRaises(ValueError):
                    self.db.finish_research(run["run_id"], ResearchReport.model_validate(report_input(citation)))
                self.assertEqual(Database(self.path).get_run(run["run_id"]), before)

    def test_finish_persists_ready_report_and_has_one_concurrent_winner(self):
        run = self.generating()
        source = self.evidence(run)
        before = self.db.get_run(run["run_id"])
        report = ResearchReport.model_validate(report_input(source["source_id"]))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.db.finish_research(run["run_id"], report), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        saved = Database(self.path).get_run(run["run_id"])
        self.assertEqual(saved, next(result for result in results if result is not None))
        self.assertEqual((saved["status"], saved["version"]), ("ready", before["version"] + 1))
        self.assertEqual(saved["research"], {**before["research"], "report": report.model_dump()})
        self.assertIsNone(saved["course_id"])
        self.assertEqual(self.db.list_records("courses"), [])

    def test_cancel_transaction_replay_and_stale_version_block_late_evidence(self):
        run = self.generating()
        source = self.evidence(run)
        run = self.db.get_run(run["run_id"])
        with self.assertRaises(AppError) as raised:
            self.db.mutate_command("stale-cancel", run["run_id"], run["version"] - 1,
                                   {"action": "cancel"}, lambda current: {**current, "status": "cancelled"})
        self.assertEqual(raised.exception.code, "version_conflict")
        self.assertEqual(self.db.get_run(run["run_id"]), run)
        args = ("cancel-research", run["run_id"], run["version"], {"action": "cancel"},
                lambda current: {**current, "status": "cancelled"})
        cancelled = self.db.mutate_command(*args)
        self.assertEqual(Database(self.path).mutate_command(*args), cancelled)
        with self.assertRaises(AppError):
            self.db.research_step(run["run_id"], read_step(), page_input("https://example.com/late"))
        self.assertIsNone(self.db.finish_research(run["run_id"], ResearchReport.model_validate(
            report_input(source["source_id"]))))
        self.assertEqual(Database(self.path).get_run(run["run_id"]), cancelled)

    def test_restart_interrupts_inflight_without_losing_evidence_or_ready_report(self):
        saved = {}
        for status in ("queued", "generating", "failed", "cancelled", "ready"):
            run = self.create(f"restart-{status}")
            if status != "queued":
                run = self.db.transition(run["run_id"], {"queued"}, status="generating")
                source = self.evidence(run)
                if status == "ready":
                    self.db.finish_research(run["run_id"], ResearchReport.model_validate(report_input(source["source_id"])))
                elif status != "generating":
                    self.db.transition(run["run_id"], {"generating"}, status=status)
            saved[status] = self.db.get_run(run["run_id"])
        reopened = Database(self.path)
        reopened.interrupt_inflight()
        for status, old in saved.items():
            with self.subTest(status=status):
                current = reopened.get_run(old["run_id"])
                if status in {"queued", "generating"}:
                    self.assertEqual((current["status"], current["version"]), ("interrupted", old["version"] + 1))
                    self.assertEqual(current["error"]["code"], "interrupted")
                    self.assertTrue(current["error"]["retryable"])
                    self.assertEqual(current["research"], old["research"])
                    self.assertEqual(current["input"], old["input"])
                    with self.assertRaises(AppError):
                        reopened.research_step(old["run_id"], read_step(), page_input())
                    self.assertIsNone(reopened.finish_research(old["run_id"], ResearchReport.model_validate(report_input())))
                else:
                    self.assertEqual(current, old)
                self.assertEqual(reopened.calls(old["run_id"]), [])
        before = reopened.list_records("runs")
        reopened.interrupt_inflight()
        self.assertEqual(reopened.list_records("runs"), before)

    def test_retry_terminal_research_preserves_parent_and_resets_child(self):
        for status in ("failed", "cancelled", "interrupted"):
            with self.subTest(status=status):
                run = self.generating(f"retry-parent-{status}")
                self.evidence(run)
                parent = self.db.transition(run["run_id"], {"generating"}, status=status,
                                            error={"code": status, "message": "Rule input", "retryable": True})
                command = f"retry-child-{status}"
                child = self.db.retry_run(command, parent["run_id"], parent["version"],
                                          configured=True, search_configured=True)
                self.assertEqual((child["kind"], child["status"], child["version"]), ("research", "queued", 1))
                self.assertNotEqual(child["run_id"], parent["run_id"])
                self.assertEqual(child["parent_run_id"], parent["run_id"])
                self.assertEqual((child["input"], child["model"]), (parent["input"], parent["model"]))
                self.assertEqual(child["research"], {"steps": [], "sources": [], "report": None})
                self.assertIsNone(child["error"])
                reopened = Database(self.path)
                self.assertEqual(reopened.get_run(parent["run_id"]), parent)
                self.assertEqual(reopened.retry_run(command, parent["run_id"], parent["version"],
                                                    configured=False, search_configured=False), child)
                with self.assertRaises(AppError) as raised:
                    reopened.retry_run(f"second-{command}", parent["run_id"], parent["version"],
                                       configured=True, search_configured=True)
                self.assertEqual(raised.exception.code, "state_conflict")

    def test_retry_configuration_and_version_errors_do_not_create_child_or_receipt(self):
        run = self.generating()
        parent = self.db.transition(run["run_id"], {"generating"}, status="failed")
        for name, version, configured, search, code in (
            ("model", parent["version"], False, True, "model_not_configured"),
            ("search", parent["version"], True, False, "search_not_configured"),
            ("version", parent["version"] - 1, True, True, "version_conflict"),
        ):
            with self.subTest(name=name), self.assertRaises(AppError) as raised:
                self.db.retry_run(f"retry-invalid-{name}", parent["run_id"], version,
                                  configured=configured, search_configured=search)
            self.assertEqual(raised.exception.code, code)
        self.assertEqual(self.db.list_records("runs"), [parent])
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0], 1)
        child = self.db.retry_run("retry-invalid-search", parent["run_id"], parent["version"],
                                  configured=True, search_configured=True)
        self.assertEqual(child["parent_run_id"], parent["run_id"])

    def test_active_and_ready_research_cannot_be_retried(self):
        for status in ("queued", "generating", "ready"):
            with self.subTest(status=status):
                run = self.create(f"retry-ineligible-{status}")
                if status != "queued":
                    run = self.db.transition(run["run_id"], {"queued"}, status="generating")
                if status == "ready":
                    source = self.evidence(run)
                    run = self.db.finish_research(run["run_id"], ResearchReport.model_validate(report_input(source["source_id"])))
                before = self.db.list_records("runs")
                with self.assertRaises(AppError) as raised:
                    self.db.retry_run(f"retry-{status}", run["run_id"], run["version"],
                                      configured=True, search_configured=True)
                self.assertEqual((raised.exception.code, raised.exception.status), ("state_conflict", 409))
                self.assertEqual(self.db.list_records("runs"), before)

    def test_concurrent_retries_have_one_successor_and_preserve_old_evidence(self):
        run = self.generating()
        self.evidence(run)
        parent = self.db.transition(run["run_id"], {"generating"}, status="failed")

        def retry(index):
            try:
                return self.db.retry_run(f"retry-tab-{index}", parent["run_id"], parent["version"],
                                          configured=True, search_configured=True)
            except AppError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(retry, range(2)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual([result.code for result in results if isinstance(result, AppError)], ["state_conflict"])
        self.assertEqual(len(self.db.list_records("runs")), 2)
        self.assertEqual(Database(self.path).get_run(parent["run_id"]), parent)
