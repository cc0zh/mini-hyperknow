"""New classroom contract on direct inputs and real SQLite, never model evidence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from hyperknow.assistance_domain import WhiteboardData
from hyperknow.domain import AppError
from hyperknow.lesson_domain import (
    BoardOperation, BoardScript, BoardScriptDraft, LessonAnswer, LessonSnapshot,
    materialize_script, validate_lesson_coverage,
)
from hyperknow.storage import Database
from test_lesson import persist_domain_input, script_input


def diagram_input():
    data = script_input()
    data["steps"][1]["operations"] = [{"object_id": "states", "kind": "diagram",
        "nodes": [{"id": "running", "label": "运行"}, {"id": "waiting", "label": "等待"}],
        "edges": [{"from_id": "running", "to_id": "waiting", "label": "遇到await"}]}]
    data["steps"][-1]["focus_ids"] = ["running", "resume"]
    return data


class CompleteLessonSchemaTests(unittest.TestCase):
    def test_teaching_structure_rejects_missing_stages_and_keypoints(self):
        mutations = [
            lambda d: d.pop("schema_version"),
            lambda d: d.update(schema_version=1),
            lambda d: d.pop("objectives"),
            lambda d: d.update(objectives=[" "]),
            lambda d: d.update(roadmap=[]),
            lambda d: d["roadmap"].append(deepcopy(d["roadmap"][0])),
            lambda d: d["roadmap"][0].pop("source_keypoint_index"),
            lambda d: d["roadmap"][0].update(source_keypoint_index=1),
            lambda d: d["roadmap"][0].update(source_keypoint_index=True),
            lambda d: d["steps"][0].update(stage="explain", keypoint_id="await"),
            lambda d: d["steps"][-1].update(stage="explain", keypoint_id="await"),
            lambda d: d["steps"][1].pop("stage"),
            lambda d: d["steps"][1].update(keypoint_id=None),
            lambda d: d["steps"][1].update(keypoint_id="unknown"),
            lambda d: d["steps"][2].update(stage="explain"),
            lambda d: d["steps"].pop(3),
            lambda d: d["steps"][3].update(check=None),
            lambda d: d["steps"][1].update(check={"question": "为什么？", "expected_answer": "让出控制权"}),
            lambda d: d["steps"][0].update(keypoint_id="await"),
        ]
        for mutate in mutations:
            data = script_input()
            mutate(data)
            with self.subTest(data=data), self.assertRaises(ValidationError):
                BoardScriptDraft.model_validate(data)

    def test_roadmap_coverage_maps_short_titles_to_long_original_points(self):
        draft = BoardScriptDraft.model_validate(script_input())
        validate_lesson_coverage(draft, {"session": {"key_points": ["很长的原始要点；标题不应完整复制原始大纲。"]}})
        for points in ([], ["要点一", "要点二"]):
            with self.assertRaises(ValueError):
                validate_lesson_coverage(draft, {"session": {"key_points": points}})

    def test_eight_keypoints_fit_without_weakening_structure(self):
        data = script_input()
        data["roadmap"] = [{"keypoint_id": f"k{i}", "source_keypoint_index": i,
                            "title": f"要点{i}", "question": f"怎样解释{i}？"} for i in range(8)]
        steps = [data["steps"][0]]
        for i in range(8):
            for stage in ("explain", "example"):
                steps.append({"title": f"{stage}{i}", "narration": "具体解释与输入输出。",
                              "stage": stage, "keypoint_id": f"k{i}", "page": 1, "column": 1,
                              "operations": [{"kind": "text", "object_id": f"{stage}{i}", "content": "具体板书"}]})
        check = deepcopy(data["steps"][3])
        check["keypoint_id"] = None
        summary = deepcopy(data["steps"][-1])
        summary["focus_ids"] = ["explain0", "example7"]
        steps.extend([check, summary])
        for i, step in enumerate(steps):
            step.update(page=i // 2 + 1, column=i % 2 + 1)
        data["steps"] = steps
        self.assertEqual(len(BoardScriptDraft.model_validate(data).steps), 19)
        changed = deepcopy(data)
        changed["steps"][3], changed["steps"][1] = changed["steps"][1], changed["steps"][3]
        for step in changed["steps"]:
            step.update(page=1, column=1)
        with self.assertRaises(ValidationError):
            BoardScriptDraft.model_validate(changed)

    def test_check_cannot_precede_its_explanation_or_example(self):
        data = script_input()
        for step in data["steps"]:
            step.update(page=1, column=1)
        data["steps"][2], data["steps"][3] = data["steps"][3], data["steps"][2]
        for keypoint in (None, "await"):
            data["steps"][2]["keypoint_id"] = keypoint
            with self.assertRaises(ValidationError):
                BoardScriptDraft.model_validate(data)

    def test_structured_table_and_diagram_payloads_are_bounded_and_rectangular(self):
        table = {"kind": "table", "object_id": "comparison", "columns": ["状态", "控制权"],
                 "rows": [["运行", "当前任务"], ["等待", "调度器"]]}
        self.assertEqual(BoardOperation.model_validate(table).rows[1][1], "调度器")
        for patch in ({"columns": []}, {"rows": []}, {"rows": [["缺列"]]}, {"rows": [["运行", " "]]},
                      {"rows": [["运行", "调度器"]] * 17}, {"nodes": [{"id": "x", "label": "x"}]}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                BoardOperation.model_validate({**table, **patch})
        operation = diagram_input()["steps"][1]["operations"][0]
        self.assertEqual(len(BoardOperation.model_validate(operation).nodes), 2)
        for patch in ({"nodes": []}, {"nodes": [{"id": "running", "label": "a"}] * 2},
                      {"edges": [{"from_id": "running", "to_id": "future", "label": "非法边"}]}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                BoardOperation.model_validate({**operation, **patch})

    def test_references_are_incremental_and_object_node_namespace_is_unique(self):
        data = diagram_input()
        data["steps"][2]["operations"].append({"object_id": "emphasis", "kind": "circle", "target_ids": ["running"]})
        data["steps"][2]["focus_ids"] = ["states", "running", "emphasis"]
        BoardScriptDraft.model_validate(data)
        mutations = [
            lambda d: d["steps"][0]["operations"][0].pop("object_id"),
            lambda d: d["steps"][0]["operations"][0].update(object_id="running"),
            lambda d: d["steps"][2]["operations"][0].update(object_id="call"),
            lambda d: d["steps"][0].update(focus_ids=["states"]),
            lambda d: d["steps"][2].update(focus_ids=["running", "running"]),
            lambda d: d["steps"][2]["operations"][1].update(target_ids=["summary"]),
            lambda d: d["steps"][2]["operations"][1].update(target_ids=[]),
            lambda d: d["steps"][1]["operations"][0].update(object_id="running"),
        ]
        for mutate in mutations:
            changed = deepcopy(data)
            mutate(changed)
            with self.subTest(data=changed), self.assertRaises(ValidationError):
                BoardScriptDraft.model_validate(changed)

    def test_independent_whiteboard_is_an_explicit_frame_model_not_legacy_lesson(self):
        frame = {"title": "关系图", "narration": "运行到等待。", "page": 1, "column": 1,
                 "operations": diagram_input()["steps"][1]["operations"]}
        WhiteboardData(steps=[frame])
        with self.assertRaises(ValidationError):
            BoardScriptDraft(title="关系图", steps=[frame])
        invalid = deepcopy(frame)
        invalid["operations"][0].pop("object_id")
        with self.assertRaises(ValidationError):
            WhiteboardData(steps=[invalid])
        with self.assertRaises(ValidationError):
            WhiteboardData(steps=[{**frame, "stage": "opening"}])

    def test_persisted_step_id_uniqueness_is_validated(self):
        script = materialize_script(BoardScriptDraft.model_validate(script_input()),
                                    {"session_id": "session", "course_id": "course"}, "timestamp")
        BoardScript.model_validate(script)
        script["steps"][1]["step_id"] = script["steps"][0]["step_id"]
        with self.assertRaises(ValidationError):
            BoardScript.model_validate(script)


class CompleteLessonStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hyperknow-complete-lesson-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "lesson.sqlite3"
        self.db = Database(self.path)
        self.course, self.sid = persist_domain_input(self.db)

    def ready(self, data=None):
        run = self.db.prepare_lesson(self.sid, "complete-input", "stored-model", True)["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(data or script_input()))
        return self.db.get_lesson(self.sid)

    @staticmethod
    def command(snapshot, identity, **patch):
        return {"client_command_id": identity, "expected_version": snapshot["progress"]["version"],
                "script_id": snapshot["script"]["script_id"], **patch}

    def advance(self, saved, end):
        for cursor in range(saved["progress"]["cursor"] + 1, end + 1):
            saved = self.db.save_progress(self.sid, self.command(saved, f"advance-{cursor}",
                cursor=cursor, play_intent="playing"))
        return saved

    def test_anchor_revisit_persists_in_model_input_without_rewinding_cursor(self):
        saved = self.advance(self.ready(diagram_input()), 2)
        anchor = saved["script"]["steps"][1]["step_id"]
        asked = self.db.ask_question(self.sid, self.command(saved, "anchor-question", cursor=2,
            question="等待节点为什么让出控制权？", was_playing=True,
            anchor_step_id=anchor, anchor_object_id="waiting"), "stored-model", True)
        interaction = asked["interactions"][0]
        self.assertEqual((asked["progress"]["cursor"], asked["progress"]["play_intent"]), (2, "paused"))
        self.assertEqual(interaction["step_id"], saved["script"]["steps"][2]["step_id"])
        self.assertEqual((interaction["anchor_step_id"], interaction["anchor_object_id"]), (anchor, "waiting"))
        run = self.db.get_run(interaction["run_id"])
        self.assertEqual((run["input"]["cursor"], len(run["input"]["displayed_steps"])), (2, 3))
        self.assertEqual((run["input"]["anchor_step_id"], run["input"]["anchor_object_id"]), (anchor, "waiting"))
        reopened = Database(self.path)
        self.assertEqual(reopened.get_lesson(self.sid)["interactions"], asked["interactions"])
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_lesson(run["run_id"], LessonAnswer(answer="等待时控制权交还调度器。"))
        restored = self.db.get_lesson(self.sid)
        self.assertEqual((restored["progress"]["cursor"], restored["progress"]["play_intent"]), (2, "paused"))
        resumed = self.db.save_progress(self.sid, self.command(restored, "explicit-resume", cursor=2, play_intent="playing"))
        self.assertEqual(resumed["progress"]["play_intent"], "playing")

    def test_future_foreign_and_inconsistent_anchors_are_rejected_without_runs(self):
        saved = self.advance(self.ready(), 1)
        first, last = saved["script"]["steps"][0]["step_id"], saved["script"]["steps"][-1]["step_id"]
        for i, patch in enumerate(({"anchor_step_id": last}, {"anchor_step_id": "foreign-step"},
                {"anchor_object_id": "summary"}, {"anchor_object_id": "foreign-object"},
                {"anchor_step_id": first, "anchor_object_id": "pause"})):
            with self.subTest(patch=patch), self.assertRaises(AppError) as raised:
                self.db.ask_question(self.sid, self.command(saved, f"invalid-anchor-{i}", cursor=1,
                    question="这一步为什么？", was_playing=False, **patch), "stored-model", True)
            self.assertEqual(raised.exception.code, "invalid_anchor")
        self.assertEqual(self.db.get_lesson(self.sid), saved)

    def test_early_exit_never_completes_but_final_summary_can(self):
        saved = self.ready()
        for cursor in range(-1, len(saved["script"]["steps"]) - 1):
            saved = self.advance(saved, cursor)
            with self.assertRaises(AppError) as raised:
                self.db.complete_lesson(self.sid, self.command(saved, f"early-complete-{cursor}"))
            self.assertEqual(raised.exception.code, "lesson_incomplete")
            self.assertFalse(self.db.get_lesson(self.sid)["completed"])
            self.assertEqual(self.db.get_course(self.course["course_id"])["version"], 1)
        saved = self.advance(saved, len(saved["script"]["steps"]) - 1)
        self.assertTrue(self.db.complete_lesson(self.sid, self.command(saved, "final-summary"))["completed"])

    def test_pending_final_check_answer_blocks_completion(self):
        saved = self.advance(self.ready(), 4)
        asked = self.db.ask_question(self.sid, self.command(saved, "final-question", cursor=4,
            question="我的理解是否正确？", was_playing=False), "stored-model", True)
        with self.assertRaises(AppError) as raised:
            self.db.complete_lesson(self.sid, self.command(asked, "complete-while-answering"))
        self.assertEqual(raised.exception.code, "question_active")
        self.assertFalse(self.db.get_lesson(self.sid)["completed"])

    def legacy(self):
        raw = '{ "schema_version": 1, "script_id": "legacy-script", "steps": [{"title":"旧内容"}] }'
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO lesson_scripts VALUES (?,?,?)", ("legacy-script", self.sid, raw))
        return raw

    def stored_raw(self):
        with self.db.transaction() as conn:
            return conn.execute("SELECT data FROM lesson_scripts WHERE session_id=?", (self.sid,)).fetchone()["data"]

    def test_cached_v2_text_is_reused_without_style_gates_rewriting_or_model_calls(self):
        data = script_input()
        data["steps"][1]["narration"] = "甲"
        data["steps"][2]["narration"] = "保留第一段。\n\n保留第二段。"
        saved = self.ready(data)
        self.assertEqual([step["narration"] for step in saved["script"]["steps"]],
                         [step["narration"] for step in data["steps"]])
        raw = self.stored_raw()
        for i, db in enumerate((self.db, Database(self.path))):
            reused = db.prepare_lesson(self.sid, f"reuse-cached-v2-{i}", "unused-model", False)
            self.assertEqual(reused, saved)
            self.assertEqual(db.calls(saved["generation_run"]["run_id"]), [])
            self.assertEqual(self.stored_raw(), raw)

    def test_legacy_format_is_explicit_read_error_without_migration_or_generation(self):
        raw = self.legacy()
        for _ in range(2):
            saved = Database(self.path).get_lesson(self.sid)
            self.assertIsNone(saved["script"])
            self.assertEqual(saved["format_error"]["code"], "lesson_format_unsupported")
            self.assertIsNone(saved["generation_run"])
            LessonSnapshot.model_validate(saved)
            self.assertEqual(self.stored_raw(), raw)
        with self.assertRaises(AppError) as raised:
            self.db.prepare_lesson(self.sid, "do-not-autoreplace", "stored-model", True)
        self.assertEqual(raised.exception.code, "lesson_format_unsupported")
        self.assertIsNone(self.db.get_lesson(self.sid)["generation_run"])

    def test_explicit_regeneration_archives_original_and_survives_failure_and_retry(self):
        raw = self.legacy()
        initial = self.db.get_lesson(self.sid)
        data = {"client_command_id": "explicit-regenerate", "expected_version": initial["progress"]["version"]}
        with self.assertRaises(AppError):
            self.db.regenerate_lesson(self.sid, data, "stored-model", False)
        queued = self.db.regenerate_lesson(self.sid, data, "stored-model", True)
        run = queued["generation_run"]
        self.assertEqual(self.db.regenerate_lesson(self.sid, data, "stored-model", False), queued)
        self.assertEqual((self.stored_raw(), run["previous_script_data"]), (raw, raw))
        self.assertNotIn("previous_script_data", run["input"])
        self.assertEqual(self.db.calls(run["run_id"]), [])
        self.db.interrupt_inflight()
        stopped = Database(self.path).get_lesson(self.sid)
        self.assertEqual(stopped["generation_run"]["status"], "interrupted")
        self.assertEqual(self.stored_raw(), raw)
        retry = self.db.retry_run("explicit-regenerate-retry", run["run_id"], stopped["generation_run"]["version"])
        self.assertEqual(retry["previous_script_data"], raw)
        self.assertIsNone(self.db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(script_input())))
        self.db.transition(retry["run_id"], {"queued"}, status="generating")
        self.db.finish_lesson(retry["run_id"], BoardScriptDraft.model_validate(script_input()))
        result = self.db.get_lesson(self.sid)
        self.assertIsNone(result["format_error"])
        self.assertEqual((result["script"]["schema_version"], result["progress"]["cursor"]), (2, -1))
        self.assertEqual(self.db.get_run(retry["run_id"])["previous_script_data"], raw)
        self.assertEqual(Database(self.path).get_lesson(self.sid)["script"], result["script"])

    def test_regeneration_concurrent_commands_have_one_winner_and_no_implicit_calls(self):
        saved = self.ready()
        def regenerate(i):
            try:
                return self.db.regenerate_lesson(self.sid, {"client_command_id": f"concurrent-regenerate-{i}",
                    "expected_version": saved["progress"]["version"]}, "stored-model", True)
            except AppError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(regenerate, range(2)))
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertIn("version_conflict", results)
        current = self.db.get_lesson(self.sid)
        self.assertEqual(current["script"], saved["script"])
        with self.assertRaises(AppError) as raised:
            self.db.save_progress(self.sid, self.command(current, "blocked-during-regenerate", cursor=0, play_intent="paused"))
        self.assertEqual(raised.exception.code, "lesson_generation_active")
        self.assertEqual(self.db.calls(current["generation_run"]["run_id"]), [])

    def test_regeneration_retry_cannot_take_a_pending_question_slot(self):
        saved = self.ready()
        queued = self.db.regenerate_lesson(self.sid, {"client_command_id": "regen-before-question",
            "expected_version": saved["progress"]["version"]}, "stored-model", True)
        run = queued["generation_run"]
        failed = self.db.transition(run["run_id"], {"queued"}, status="failed", error={"code": "direct-input"})
        saved = self.db.get_lesson(self.sid)
        asked = self.db.ask_question(self.sid, self.command(saved, "question-after-regen-failure", cursor=-1,
            question="讲义准备好了吗？", was_playing=False), "stored-model", True)
        with self.assertRaises(AppError) as raised:
            self.db.retry_run("blocked-regen-retry", failed["run_id"], failed["version"])
        self.assertEqual(raised.exception.code, "question_active")
        self.assertEqual(self.db.get_lesson(self.sid), asked)

    def test_old_question_cannot_retry_after_explicit_script_replacement(self):
        saved = self.ready()
        asked = self.db.ask_question(self.sid, self.command(saved, "old-script-question", cursor=-1,
            question="这课讲什么？", was_playing=False), "stored-model", True)
        question = asked["interactions"][0]
        failed = self.db.transition(question["run_id"], {"queued"}, status="failed", error={"code": "direct-input"})
        saved = self.db.get_lesson(self.sid)
        queued = self.db.regenerate_lesson(self.sid, {"client_command_id": "replace-after-question",
            "expected_version": saved["progress"]["version"]}, "stored-model", True)
        run = queued["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(script_input()))
        with self.assertRaises(AppError) as raised:
            self.db.retry_run("old-question-retry", failed["run_id"], failed["version"])
        self.assertEqual(raised.exception.code, "script_conflict")
        self.assertEqual(self.db.get_lesson(self.sid)["interactions"], [])
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM lesson_interactions WHERE id=?", (question["interaction_id"],)).fetchone()[0], 1)
