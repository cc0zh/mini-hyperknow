"""One process, one real model call at a time; committed state notifications."""

import asyncio
from contextlib import suppress
import logging

from fastapi import WebSocket

from .config import Settings
from .domain import AppError, resolve_answers
from .generation import Generator
from .storage import Database

logger = logging.getLogger(__name__)


class EventHub:
    def __init__(self):
        self.subscribers: dict[WebSocket, set[str]] = {}
        self.locks: dict[WebSocket, asyncio.Lock] = {}

    async def send(self, socket: WebSocket, event: dict):
        lock = self.locks.setdefault(socket, asyncio.Lock())
        async with lock:
            await asyncio.wait_for(socket.send_json(event), timeout=3)

    async def changed(self, run: dict):
        topic = f"run:{run['run_id']}"
        event = {"type": "resource_changed", "resource_type": "run", "resource_id": run["run_id"],
                 "version": run["version"], "state": run["status"]}
        for socket, topics in list(self.subscribers.items()):
            if topic in topics:
                try:
                    await self.send(socket, event)
                except Exception:
                    self.remove(socket)

    def remove(self, socket: WebSocket):
        self.subscribers.pop(socket, None)
        self.locks.pop(socket, None)


class CourseService:
    def __init__(self, settings: Settings, db: Database, hub: EventHub):
        self.settings, self.db, self.hub = settings, db, hub
        self.generator = Generator(settings, db)
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.worker: asyncio.Task | None = None
        self.accepting = True

    def require_model(self):
        if not self.settings.api_key:
            raise AppError("model_not_configured", "尚未配置真实模型，请在本地 .env 设置 OPENAI_API_KEY 后重启后端", 503)

    def start(self):
        self.db.interrupt_inflight()
        self.worker = asyncio.create_task(self.work())

    async def close(self):
        self.accepting = False
        self.generator.stopping.set()
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
        self.db.interrupt_inflight()

    def enqueue(self, run: dict):
        if run["status"] == "queued":
            self.queue.put_nowait((run["run_id"], "generating" if run["answers_submitted"] else "clarifying"))
        elif run["status"] == "generating":
            self.queue.put_nowait((run["run_id"], "generating"))

    async def create(self, goal: str, command_id: str):
        self.require_model()
        run = self.db.create_run(command_id, goal, self.settings.model)
        self.enqueue(run)
        return run

    async def answers(self, run_id: str, data: dict):
        self.require_model()
        def submit(run):
            if run["status"] != "awaiting_answers":
                raise AppError("state_conflict", "当前任务不在等待澄清答案", 409)
            run["answers"] = resolve_answers(run["questions"], data["answers"], data["skip"])
            run.update(skipped=data["skip"], answers_submitted=True, status="generating", error=None)
            return run
        run = self.db.mutate_command(data["client_command_id"], run_id, data["expected_version"],
                                     {"action": "answers", "answers": data["answers"], "skip": data["skip"]}, submit)
        self.enqueue(run)
        await self.hub.changed(run)
        return run

    async def cancel(self, run_id: str, data: dict):
        def cancel(run):
            if run["status"] not in {"queued", "clarifying", "awaiting_answers", "generating"}:
                raise AppError("state_conflict", "任务已经结束，不能再取消", 409)
            run.update(status="cancelled", error=None)
            return run
        run = self.db.mutate_command(data["client_command_id"], run_id, data["expected_version"],
                                     {"action": "cancel"}, cancel)
        await self.hub.changed(run)
        return run

    async def retry(self, run_id: str, data: dict):
        self.require_model()
        run = self.db.retry_run(data["client_command_id"], run_id, data["expected_version"])
        self.enqueue(run)
        return run

    async def work(self):
        while True:
            run_id, phase = await self.queue.get()
            try:
                run = self.db.get_run(run_id)
                allowed = {"queued"} if phase == "clarifying" else {"queued", "generating"}
                run = self.db.transition(run_id, allowed, status=phase, error=None)
                if run is None:
                    continue
                await self.hub.changed(run)
                # The worker remains occupied until this real network call returns.
                result = await asyncio.to_thread(self.generator.generate, run, phase)
                if not self.accepting:
                    continue
                if phase == "clarifying":
                    updated = self.db.transition(run_id, {"clarifying"}, status="awaiting_answers",
                                                 questions=result.model_dump()["questions"])
                else:
                    updated = self.db.finish_course(run_id, result)
                if updated:
                    calls = self.db.calls(run_id)
                    reported = [c["usage"] for c in calls if c.get("usage")]
                    if reported:
                        totals = {key: sum(u.get(key, 0) for u in reported)
                                  for key in {k for u in reported for k in u}}
                        updated = self.db.transition(run_id, {updated["status"]}, usage=totals) or updated
                    await self.hub.changed(updated)
            except AppError as exc:
                updated = self.db.transition(run_id, {"queued", "clarifying", "generating"},
                                             status="failed", error=exc.public())
                if updated:
                    await self.hub.changed(updated)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Course run failed: %s (%s)", run_id, type(exc).__name__)
                with suppress(Exception):
                    updated = self.db.transition(run_id, {"queued", "clarifying", "generating"}, status="failed",
                        error={"code": "generation_failed", "message": "生成或保存失败，未创建完成课程，请重试", "retryable": True})
                    if updated:
                        await self.hub.changed(updated)
            finally:
                self.queue.task_done()
