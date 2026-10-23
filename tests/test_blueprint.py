"""Explicit domain inputs on real SQLite; not model/search acceptance evidence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from hyperknow.blueprint_domain import BlueprintDraft, UnitExpansionDraft, planning_context
from hyperknow.domain import AppError
from hyperknow.research_domain import ResearchReport
from hyperknow.storage import Database
from test_research import page_input, read_step, report_input, search_step


def blueprint_input():
    return {"title": "异步任务学习路径", "description": "理解暂停、恢复和任务取消。",
            "target_learner": "会Python基础的学习者", "difficulty": "beginner", "tags": ["asyncio"],
            "language": "zh-CN", "projects": [], "units": [
                {"title": "协程与调度", "description": "区分协程和任务。", "learning_objectives": ["理解await"],
                 "estimated_sessions": 2, "project_keys": [], "exam_goal": ""},
                {"title": "任务取消", "description": "理解取消传播与清理。", "learning_objectives": ["理解取消传播"],
                 "estimated_sessions": 2, "project_keys": [], "exam_goal": "辨别任务取消与异常清理"}]}


def expansion_input(exam_goal=""):
    return {"lectures": [{"title": "暂停与恢复", "description": "认识调度边界。", "sessions": [
        {"title": "await让出控制权", "description": "比较普通调用和协程暂停。", "outline": "比较两种调用的控制流。",
         "key_points": ["协程暂停", "任务调度"], "estimated_minutes": 10, "depths": ["intuition", "definition"]}]}],
        "exams": [{"title": "取消考核", "goal": exam_goal}] if exam_goal else [], "project_stages": []}


class BlueprintStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hyperknow-blueprint-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "hyperknow.sqlite3"
        self.db = Database(self.path)

    def research(self, command="create-blueprint"):
        run = self.db.create_run(command, "理解Python异步任务", "stored-model")
        self.assertEqual(run["workflow"], "blueprint-v1")
        run = self.db.transition(run["run_id"], {"queued"}, status="generating", stage="research",
                                 answers_submitted=True, input={"goal": run["goal"], "context": "会Python"},
                                 research={"steps": [], "sources": [], "report": None})
        self.db.research_step(run["run_id"], search_step())
        source = self.db.research_step(run["run_id"], read_step(), page_input())
        report = ResearchReport.model_validate(report_input(source["source_id"]))
        return self.db.finish_research(run["run_id"], report)

    def awaiting(self, command="create-blueprint"):
        run = self.research(command)
        self.assertEqual((run["status"], run["stage"]), ("generating", "blueprint"))
        return self.db.finish_blueprint(run["run_id"], BlueprintDraft.model_validate(blueprint_input()))

    def decide(self, run, approve=True, feedback="", command="confirm-blueprint"):
        return self.db.blueprint_command(run["run_id"], {
            "client_command_id": command, "expected_version": run["version"],
            "approve": approve, "feedback": feedback}, configured=True)

    def expanding(self):
        return self.decide(self.awaiting())

    def cancel(self, run):
        return self.db.mutate_command("cancel-" + run["run_id"], run["run_id"], run["version"],
                                      {"action": "cancel"}, lambda current: {**current, "status": "cancelled"})

    def test_blueprint_persists_only_units_and_waits_without_synthesizing_sessions(self):
        run = self.awaiting()
        self.assertEqual(run["status"], "awaiting_blueprint")
        course = Database(self.path).get_course(run["course_id"])
        self.assertEqual(course["structure_status"], "blueprint")
        self.assertEqual(course["session_count"], 0)
        self.assertIsNone(course["progress"])
        self.assertEqual(course["creation_run_id"], run["run_id"])
        self.assertTrue(all(not u["lectures"] and u["generation_status"] == "pending" for u in course["units"]))
        self.assertEqual(course["next_item"]["type"], "generation")
        before = self.db.get_run(run["run_id"])
        with self.assertRaises(AppError):
            self.db.begin_unit(run["run_id"])
        self.assertEqual(self.db.get_run(run["run_id"]), before)

    def test_approval_is_versioned_idempotent_and_only_once(self):
        waiting = self.awaiting()
        with self.assertRaises(AppError):
            self.decide({**waiting, "version": waiting["version"] - 1})
        approved = self.decide(waiting)
        self.assertEqual((approved["status"], approved["stage"]), ("generating", "units"))
        self.assertEqual(self.decide(waiting), approved)
        with self.assertRaises(AppError):
            self.decide(approved, command="approve-twice")
        with self.assertRaises(AppError):
            self.decide(approved, approve=False, feedback="修改已经确认的蓝图", command="revise-approved")

    def test_revision_keeps_course_identity_and_requires_a_new_approval(self):
        waiting = self.awaiting()
        before = self.db.get_course(waiting["course_id"])
        with self.assertRaises(AppError):
            self.decide(waiting, approve=False, feedback=" ", command="empty-revision")
        revised = self.decide(waiting, approve=False, feedback="第二单元增加清理边界", command="revise-blueprint")
        self.assertEqual((revised["status"], revised["stage"]), ("generating", "blueprint"))
        data = blueprint_input()
        data["units"][1]["description"] = "重点讨论取消时的资源清理。"
        again = self.db.finish_blueprint(revised["run_id"], BlueprintDraft.model_validate(data))
        after = self.db.get_course(again["course_id"])
        self.assertEqual(again["status"], "awaiting_blueprint")
        self.assertEqual(before["course_id"], after["course_id"])
        self.assertGreater(after["blueprint_version"], before["blueprint_version"])
        with self.assertRaises(AppError):
            self.decide(waiting, command="stale-confirmation")

    def test_two_units_commit_incrementally_without_changing_existing_ids(self):
        approved = self.expanding()
        first = self.db.begin_unit(approved["run_id"])
        unit_id = first["current_unit_id"]
        updated = self.db.finish_unit(first["run_id"], unit_id, UnitExpansionDraft.model_validate(expansion_input()))
        partial = self.db.get_course(updated["course_id"])
        self.assertEqual(partial["units"][0]["generation_status"], "ready")
        self.assertEqual(partial["units"][1]["generation_status"], "pending")
        self.assertIsNone(partial["progress"])
        saved_first = deepcopy(partial["units"][0])
        second = self.db.begin_unit(updated["run_id"])
        self.assertNotEqual(unit_id, second["current_unit_id"])
        finished = self.db.finish_unit(second["run_id"], second["current_unit_id"],
                                       UnitExpansionDraft.model_validate(expansion_input(partial["units"][1]["exam_goal"])))
        final = Database(self.path).get_course(finished["course_id"])
        self.assertEqual(finished["status"], "ready")
        self.assertEqual(final["structure_status"], "ready")
        self.assertEqual(final["session_count"], 2)
        self.assertEqual(final["progress"], 0)
        self.assertEqual(final["units"][0], saved_first)
        self.assertEqual(final["units"][1]["generation_status"], "ready")

    def test_cancel_rejects_late_unit_and_retry_reuses_completed_structure(self):
        run = self.expanding()
        first = self.db.begin_unit(run["run_id"])
        self.db.finish_unit(run["run_id"], first["current_unit_id"], UnitExpansionDraft.model_validate(expansion_input()))
        second = self.db.begin_unit(run["run_id"])
        parent = self.db.get_run(run["run_id"])
        cancelled = self.cancel(parent)
        old_course = self.db.get_course(cancelled["course_id"])
        self.assertIsNone(self.db.finish_unit(run["run_id"], second["current_unit_id"],
                          UnitExpansionDraft.model_validate(expansion_input(old_course["units"][1]["exam_goal"]))))
        retry = self.db.retry_run("retry-blueprint", cancelled["run_id"], cancelled["version"],
                                  configured=True, search_configured=True)
        course = self.db.get_course(retry["course_id"])
        self.assertEqual(retry["course_id"], cancelled["course_id"])
        self.assertEqual(course["units"][0], old_course["units"][0])
        self.assertEqual(course["creation_run_id"], retry["run_id"])
        self.assertEqual(retry["research"], cancelled["research"])
        self.assertEqual(self.db.begin_unit(retry["run_id"])["current_unit_id"], second["current_unit_id"])

    def test_restart_preserves_waiting_confirmation_and_interrupts_only_active_work(self):
        waiting = self.awaiting("waiting-course")
        active = self.decide(self.awaiting("active-course"), command="approve-active")
        self.db.begin_unit(active["run_id"])
        saved = self.db.get_course(waiting["course_id"])
        reopened = Database(self.path)
        reopened.interrupt_inflight()
        self.assertEqual(reopened.get_run(waiting["run_id"]), waiting)
        self.assertEqual(reopened.get_course(waiting["course_id"]), saved)
        self.assertEqual(reopened.get_run(active["run_id"])["status"], "interrupted")
        self.assertEqual(reopened.get_course(active["course_id"])["units"][0]["generation_status"], "interrupted")

    def test_concurrent_finish_has_one_winner_and_wrong_unit_cannot_commit(self):
        approved = self.expanding()
        run = self.db.begin_unit(approved["run_id"])
        data = UnitExpansionDraft.model_validate(expansion_input())
        course = self.db.get_course(run["course_id"])
        with self.assertRaises(AppError):
            self.db.finish_unit(run["run_id"], course["units"][1]["unit_id"], data)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.db.finish_unit(run["run_id"], run["current_unit_id"], data), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.db.get_course(run["course_id"])["session_count"], 1)

    def test_planned_project_keys_exam_goal_and_depths_are_enforced(self):
        broken = blueprint_input()
        broken["units"][0]["project_keys"] = ["unknown"]
        with self.assertRaises(ValidationError):
            BlueprintDraft.model_validate(broken)
        approved = self.expanding()
        first = self.db.begin_unit(approved["run_id"])
        with self.assertRaises((ValueError, AppError)):
            self.db.finish_unit(first["run_id"], first["current_unit_id"],
                                UnitExpansionDraft.model_validate(expansion_input("没有批准的考核")))
        invalid = expansion_input()
        invalid["lectures"][0]["sessions"][0]["depths"] = ["unknown"]
        with self.assertRaises(ValidationError):
            UnitExpansionDraft.model_validate(invalid)

    def test_creation_configuration_rejection_is_atomic_and_replay_needs_no_keys(self):
        with self.assertRaises(AppError) as rejected:
            self.db.create_run("search-config-boundary", "理解Python协程", "stored-model", search_configured=False)
        self.assertEqual(rejected.exception.code, "search_not_configured")
        self.assertEqual(self.db.list_records("runs"), [])
        created = self.db.create_run("search-config-boundary", "理解Python协程", "stored-model")
        replayed = self.db.create_run("search-config-boundary", "理解Python协程", "other-model",
                                     configured=False, search_configured=False)
        self.assertEqual(created, replayed)

    def test_retry_before_complete_research_resets_only_child_evidence(self):
        run = self.db.create_run("incomplete-research", "理解Python协程", "stored-model")
        run = self.db.transition(run["run_id"], {"queued"}, status="generating", stage="research",
                                 answers_submitted=True)
        self.db.research_step(run["run_id"], search_step())
        self.db.research_step(run["run_id"], read_step(), page_input())
        cancelled = self.cancel(self.db.get_run(run["run_id"]))
        with self.assertRaises(AppError):
            self.db.retry_run("missing-search-retry", run["run_id"], cancelled["version"], search_configured=False)
        retry = self.db.retry_run("configured-search-retry", run["run_id"], cancelled["version"], search_configured=True)
        self.assertEqual(retry["stage"], "research")
        self.assertEqual(retry["research"], {"steps": [], "sources": [], "report": None})
        self.assertEqual(self.db.get_run(run["run_id"]), cancelled)

    def test_retry_saved_blueprint_does_not_require_search_or_duplicate_sources(self):
        waiting = self.awaiting()
        cancelled = self.cancel(waiting)
        retry = self.db.retry_run("saved-blueprint-retry", waiting["run_id"], cancelled["version"], search_configured=False)
        self.assertEqual(retry["status"], "awaiting_blueprint")
        self.assertEqual(retry["research"], waiting["research"])
        self.assertEqual(retry["course_id"], waiting["course_id"])
        self.assertEqual(self.db.calls(retry["run_id"]), [])

    def test_context_preserves_evidence_identity_and_labels_utf8_truncation(self):
        run = self.research()
        source = run["research"]["sources"][0]
        source["text"] = "字符与换行\n" * 3000
        context = planning_context(run, budget=6000)
        excerpt = context["sources"][0]
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False).encode("utf-8")), 6000)
        self.assertTrue(excerpt["context_truncated"])
        self.assertEqual(excerpt["source_id"], source["source_id"])
        self.assertEqual(excerpt["content_sha256"], source["content_sha256"])
        self.assertTrue(source["text"].startswith(excerpt["context_excerpt"]))
        self.assertEqual(excerpt["stored_excerpt_bytes"], len(source["text"].encode("utf-8")))
        run["blueprint_feedback"] = "不可丢弃的修改意见" * 3000
        with self.assertRaises(AppError) as overflow:
            planning_context(run, budget=6000)
        self.assertEqual(overflow.exception.code, "context_too_large")
        self.assertEqual(self.db.calls(run["run_id"]), [])

    def test_planned_project_stage_maps_stable_project_id_and_rejects_duplicates(self):
        run = self.research()
        data = blueprint_input()
        data["projects"] = [{"project_key": "manager", "name": "任务管理器", "description": "管理任务生命周期",
                             "final_deliverable": "一个支持取消与清理的并发任务管理器"}]
        data["units"][0]["project_keys"] = ["manager"]
        waiting = self.db.finish_blueprint(run["run_id"], BlueprintDraft.model_validate(data))
        approved = self.decide(waiting)
        active = self.db.begin_unit(approved["run_id"])
        expansion = expansion_input()
        stage = {"project_key": "manager", "title": "任务创建", "description": "建立任务登记与等待",
                 "deliverable": "能够登记并等待两个任务的小程序"}
        expansion["project_stages"] = [stage, deepcopy(stage)]
        with self.assertRaises(ValueError):
            self.db.finish_unit(active["run_id"], active["current_unit_id"], UnitExpansionDraft.model_validate(expansion))
        expansion["project_stages"] = [stage]
        self.db.finish_unit(active["run_id"], active["current_unit_id"], UnitExpansionDraft.model_validate(expansion))
        course = self.db.get_course(active["course_id"])
        saved = course["units"][0]["project_stages"][0]
        self.assertEqual(saved["project_id"], course["projects"][0]["project_id"])
        self.assertTrue(saved["stage_id"])
        self.assertFalse(saved["completed"])
