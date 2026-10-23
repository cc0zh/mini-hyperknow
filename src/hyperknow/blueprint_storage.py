"""Course planning and unit commits use the same SQLite command boundary."""

from copy import deepcopy

from .blueprint_domain import (BlueprintDraft, UnitExpansionDraft, expansion_budget,
                               materialize_blueprint, materialize_expansion, validate_expansion)
from .domain import AppError


class BlueprintStorage:
    def finish_blueprint(self, run_id: str, draft: BlueprintDraft) -> dict | None:
        from .storage import now
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if run["status"] != "generating" or run.get("stage") != "blueprint":
                return None
            previous = self._get(conn, "courses", run["course_id"]) if run.get("course_id") else None
            if run.get("approved_blueprint_version") or (previous and (
                    previous["creation_run_id"] != run_id or previous["structure_status"] != "blueprint")):
                return None
            if not run["research"].get("report"):
                raise AppError("research_required", "蓝图必须依据已保存的调研报告", 409)
            course = materialize_blueprint(draft, run, now(), previous)
            self._write(conn, "courses", course["course_id"], course)
            run.update(status="awaiting_blueprint", course_id=course["course_id"],
                       blueprint_version=course["blueprint_version"], blueprint_pending=False,
                       error=None, version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run

    def blueprint_command(self, run_id: str, data: dict, *, configured: bool = True) -> dict:
        from .storage import now
        feedback = data.get("feedback", "").strip()

        def change(conn):
            run = self._get(conn, "runs", run_id)
            if run["version"] != data["expected_version"]:
                raise AppError("version_conflict", "记录已更新，请刷新后再试", 409, True,
                               latest_version=run["version"])
            if run.get("kind", "course") != "course" or run["status"] != "awaiting_blueprint":
                raise AppError("state_conflict", "当前任务不在等待全局蓝图确认", 409)
            course = self._get(conn, "courses", run["course_id"])
            if (course["creation_run_id"] != run_id or course["structure_status"] != "blueprint"
                    or run.get("approved_blueprint_version")
                    or course["blueprint_version"] != run["blueprint_version"]):
                raise AppError("state_conflict", "已确认或已被替换的蓝图不能调整", 409)
            self._model_configured(configured)
            if data["approve"]:
                run.update(approved_blueprint_version=course["blueprint_version"], stage="units")
                course["structure_status"] = "expanding"
                course["version"] += 1
                self._write(conn, "courses", course["course_id"], course)
            else:
                if not feedback:
                    raise AppError("feedback_required", "调整蓝图需要填写具体意见", 422)
                run.update(stage="blueprint", blueprint_feedback=feedback, blueprint_pending=True)
            run.update(status="generating", error=None, version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run

        return self.command(data["client_command_id"], {"action": "blueprint", "run_id": run_id,
            "version": data["expected_version"], "approve": data["approve"], "feedback": feedback}, change)

    @staticmethod
    def _units_active(run: dict, course: dict) -> bool:
        return (run["status"] == "generating" and run.get("stage") == "units"
                and course["creation_run_id"] == run["run_id"]
                and course["structure_status"] == "expanding"
                and run.get("approved_blueprint_version") == course["blueprint_version"])

    def begin_unit(self, run_id: str) -> dict | None:
        from .storage import now
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if not run.get("course_id"):
                raise AppError("state_conflict", "课程蓝图尚未确认，不能展开单元", 409)
            course = self._get(conn, "courses", run["course_id"])
            if run["status"] == "queued":
                run["status"] = "generating"
            if not self._units_active(run, course):
                raise AppError("state_conflict", "当前任务不允许展开单元", 409)
            unit = next((unit for unit in course["units"] if unit["generation_status"] != "ready"), None)
            if unit is None or unit["generation_status"] != "pending":
                raise AppError("state_conflict", "单元生成状态不允许开始，请刷新或显式重试", 409)
            unit["generation_status"] = "generating"
            course["version"] += 1
            self._write(conn, "courses", course["course_id"], course)
            run.update(current_unit_id=unit["unit_id"], version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run

    def finish_unit(self, run_id: str, unit_id: str, draft: UnitExpansionDraft) -> dict | None:
        from .storage import now
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if not run.get("course_id"):
                return None
            course = self._get(conn, "courses", run["course_id"])
            if not self._units_active(run, course):
                return None
            unit = next((unit for unit in course["units"] if unit["unit_id"] == unit_id), None)
            if unit and unit["generation_status"] == "ready":
                return None
            if not unit or run.get("current_unit_id") != unit_id or unit["generation_status"] != "generating":
                raise AppError("state_conflict", "不能提交未在生成的单元", 409)
            validate_expansion(draft, unit, expansion_budget(course, unit_id))
            unit.update(materialize_expansion(draft, course), generation_status="ready")
            course.update(version=course["version"] + 1,
                          session_count=sum(len(lecture["sessions"]) for u in course["units"] for lecture in u["lectures"]),
                          exam_count=sum(len(u["exams"]) for u in course["units"]))
            if all(u["generation_status"] == "ready" for u in course["units"]):
                course["structure_status"] = "ready"
                run["status"] = "ready"
            self._write(conn, "courses", course["course_id"], course)
            run.update(current_unit_id=None, error=None, version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run

    def _blueprint_run_changed(self, conn, run: dict):
        if not run.get("course_id") or run["status"] not in {"failed", "cancelled", "interrupted"}:
            return
        course = self._get(conn, "courses", run["course_id"])
        if course.get("creation_run_id") != run["run_id"] or course["structure_status"] == "ready":
            return
        changed = False
        for unit in course["units"]:
            if unit["generation_status"] not in {"ready", run["status"]}:
                unit["generation_status"] = run["status"]
                changed = True
        if changed:
            course["version"] += 1
            self._write(conn, "courses", course["course_id"], course)

    def _retry_blueprint(self, conn, parent: dict, run: dict, *, search_configured: bool):
        run["current_unit_id"] = None
        for key in ("workflow", "stage", "research", "input", "blueprint_version",
                    "approved_blueprint_version", "blueprint_feedback", "blueprint_pending", "course_id"):
            if key in parent:
                run[key] = deepcopy(parent[key])
        if not run["answers_submitted"]:
            run["stage"] = "clarifying"
            return
        if not run["research"].get("report"):
            self._search_configured(search_configured)
            run.update(stage="research", research={"steps": [], "sources": [], "report": None})
            return
        if not run.get("course_id"):
            run.update(stage="blueprint", blueprint_pending=True)
            return
        course = self._get(conn, "courses", run["course_id"])
        if course["creation_run_id"] != parent["run_id"]:
            raise AppError("state_conflict", "课程已有其他生成任务，请继续该任务", 409)
        course.update(creation_run_id=run["run_id"], version=course["version"] + 1)
        for unit in course["units"]:
            if unit["generation_status"] != "ready":
                unit["generation_status"] = "pending"
        if run.get("approved_blueprint_version"):
            run.update(stage="units", status="ready" if course["structure_status"] == "ready" else "queued")
        elif run.get("blueprint_pending"):
            run["stage"] = "blueprint"
        else:
            run.update(stage="blueprint", status="awaiting_blueprint")
        self._write(conn, "courses", course["course_id"], course)
