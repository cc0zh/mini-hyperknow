"""Research facts share the existing SQLite run/command transaction boundary."""

from .domain import AppError, uid
from .research_domain import ResearchReport, validate_report


class ResearchStorage:
    @staticmethod
    def _research_active(run: dict) -> bool:
        return run["status"] == "generating" and (
            run.get("kind") == "research" or (
                run.get("kind", "course") == "course" and run.get("workflow") == "blueprint-v1"
                and run.get("stage") == "research"))

    def create_research(self, command_id: str, goal: str, context: str, model: str,
                        *, configured: bool, search_configured: bool) -> dict:
        def create(conn):
            self._model_configured(configured)
            self._search_configured(search_configured)
            run = self._new_run(goal, model)
            run.update(kind="research", input={"goal": goal, "context": context},
                       research={"steps": [], "sources": [], "report": None})
            self._save_run(conn, run)
            return run
        return self.command(command_id, {"action": "research", "goal": goal, "context": context}, create)

    @staticmethod
    def _search_configured(configured: bool):
        if not configured:
            raise AppError("search_not_configured", "网页调研需要 TAVILY_API_KEY，请在本地配置后重启", 503)

    def research_step(self, run_id: str, step: dict, page: dict | None = None) -> dict | None:
        from .storage import now
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if not self._research_active(run):
                raise AppError("run_inactive", "调研已取消或中断，未保存晚到结果", 409)
            source = None
            research = run["research"]
            if len(research["steps"]) >= 10:
                raise AppError("research_budget_exceeded", "调研工具次数已达上限", 422)
            if page is not None:
                source = next((s for s in research["sources"] if s["url"] == page["url"]), None)
                if source is None:
                    source = {**page, "source_id": uid("source")}
                    research["sources"].append(source)
                step = {**step, "source_id": source["source_id"]}
            research["steps"].append(step)
            run.update(version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return source

    def finish_research(self, run_id: str, report: ResearchReport) -> dict | None:
        from .storage import now
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if not self._research_active(run):
                return None
            validate_report(report, run["research"])
            run["research"]["report"] = report.model_dump()
            if run.get("kind", "course") == "course":
                run.update(stage="blueprint", blueprint_pending=True)
            else:
                run["status"] = "ready"
            run.update(error=None, version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run
