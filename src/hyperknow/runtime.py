"""One process, one real model call at a time; committed state notifications."""

import asyncio
from contextlib import suppress
import json
import logging
import sqlite3

from fastapi import WebSocket

from .config import Settings
from .domain import AppError, resolve_answers
from .generation import Generator
from .research import Researcher
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
        await self.resource_changed("run", run["run_id"], run["version"], run["status"])

    async def resource_changed(self, kind: str, resource_id: str, version: int, state: str | None = None):
        topic = f"{kind}:{resource_id}"
        event = {"type": "resource_changed", "resource_type": kind, "resource_id": resource_id,
                 "version": version}
        if state is not None:
            event["state"] = state
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
        self.enqueued: set[tuple[str, str]] = set()

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
        if run["status"] not in {"queued", "generating"}:
            return
        phase = run["stage"] if run.get("kind", "course") == "course" else "generating"
        entry = (run["run_id"], phase)
        if entry not in self.enqueued:
            self.enqueued.add(entry)
            self.queue.put_nowait(entry)

    async def notify_lesson(self, snapshot: dict):
        await self.hub.resource_changed("session", snapshot["session"]["session_id"], snapshot["version"])

    async def notify_run(self, run: dict):
        await self.hub.changed(run)
        if run.get("kind") == "assistance":
            await self.notify_assistance(self.db.get_assistance_conversation(run["conversation_id"]))
        elif run.get("kind") == "quiz":
            await self.notify_quiz_target(self.db.get_quiz_target(run["target_type"], run["target_id"]))
        elif run.get("session_id"):
            await self.notify_lesson(self.db.get_lesson(run["session_id"]))
        if run.get("course_id") and (run.get("kind", "course") == "course" or run["status"] == "ready"):
            course = self.db.get_course(run["course_id"])
            await self.hub.resource_changed("course", course["course_id"], course["version"])

    async def notify_assistance(self, snapshot: dict):
        await self.hub.resource_changed("conversation", snapshot["conversation_id"], snapshot["version"])
        for turn in snapshot["turns"]:
            for artifact in turn["artifacts"]:
                await self.hub.resource_changed("artifact", artifact["artifact_id"], artifact["version"])

    async def assistance_turn(self, conversation_id: str, data: dict):
        from .assistance_generation import build_skill_snapshots
        snapshot = self.db.assistance_turn(conversation_id, data, self.settings.model,
                                           bool(self.settings.api_key), build_skill_snapshots)
        if snapshot["active_run"]:
            self.enqueue(snapshot["active_run"])
        await self.notify_assistance(snapshot)
        return snapshot

    async def prepare(self, session_id: str, data: dict):
        snapshot = self.db.prepare_lesson(session_id, data["client_command_id"], self.settings.model,
                                          bool(self.settings.api_key))
        if snapshot["generation_run"]:
            self.enqueue(snapshot["generation_run"])
        await self.notify_lesson(snapshot)
        return snapshot

    async def delete_course(self, course_id: str, data: dict):
        result = self.db.delete_course(course_id, data)
        await self.hub.resource_changed("course", course_id, data["expected_version"] + 1, "deleted")
        return result

    async def progress(self, session_id: str, data: dict):
        snapshot = self.db.save_progress(session_id, data)
        await self.notify_lesson(snapshot)
        return snapshot

    async def question(self, session_id: str, data: dict):
        snapshot = self.db.ask_question(session_id, data, self.settings.model, bool(self.settings.api_key))
        for interaction in snapshot["interactions"]:
            if interaction["status"] == "pending":
                self.enqueue(self.db.get_run(interaction["run_id"]))
        await self.notify_lesson(snapshot)
        return snapshot

    async def complete(self, session_id: str, data: dict):
        snapshot = self.db.complete_lesson(session_id, data)
        await self.notify_lesson(snapshot)
        await self.notify_quiz_target(self.db.get_quiz_target("practice", session_id))
        course = self.db.get_course(snapshot["course_id"])
        await self.hub.resource_changed("course", course["course_id"], course["version"])
        return snapshot

    async def notify_quiz_target(self, snapshot: dict):
        key = f"{snapshot['target_type']}:{snapshot['target_id']}"
        await self.hub.resource_changed("quiz_target", key, snapshot["version"])

    async def quiz_prepare(self, target_type: str, target_id: str, data: dict):
        snapshot = self.db.prepare_quiz(target_type, target_id, data["client_command_id"],
                                        self.settings.model, bool(self.settings.api_key))
        if snapshot["generation_run"]:
            self.enqueue(snapshot["generation_run"])
        await self.notify_quiz_target(snapshot)
        return snapshot

    async def notify_attempt(self, snapshot: dict):
        attempt = snapshot["attempt"]
        await self.hub.resource_changed("attempt", attempt["attempt_id"], attempt["version"])
        await self.notify_quiz_target(self.db.get_quiz_target(attempt["target_type"], attempt["target_id"]))
        if attempt["status"] == "submitted":
            if attempt["target_type"] == "practice":
                await self.notify_lesson(self.db.get_lesson(attempt["target_id"]))
            course = snapshot["course"]
            await self.hub.resource_changed("course", course["course_id"], course["version"])

    async def attempt_create(self, quiz_id: str, data: dict):
        snapshot = self.db.create_attempt(quiz_id, data["client_command_id"])
        await self.notify_attempt(snapshot)
        return snapshot

    async def attempt_change(self, attempt_id: str, action: str, data: dict):
        methods = {"answers": self.db.answer_quiz, "next": self.db.next_question,
                   "submit": self.db.submit_quiz}
        snapshot = methods[action](attempt_id, data)
        await self.notify_attempt(snapshot)
        return snapshot

    async def create(self, goal: str, command_id: str):
        run = self.db.create_run(command_id, goal, self.settings.model, configured=bool(self.settings.api_key),
                                  search_configured=bool(self.settings.tavily_api_key))
        self.enqueue(run)
        return run

    async def research(self, goal: str, context: str, command_id: str):
        Researcher(self.settings, self.db, self.generator.stopping).validate_input(goal, context)
        run = self.db.create_research(command_id, goal, context, self.settings.model,
                                      configured=bool(self.settings.api_key),
                                      search_configured=bool(self.settings.tavily_api_key))
        self.enqueue(run)
        return run

    async def answers(self, run_id: str, data: dict):
        def submit(run):
            if run.get("kind", "course") != "course" or run["status"] != "awaiting_answers":
                raise AppError("state_conflict", "当前任务不在等待澄清答案", 409)
            self.db._model_configured(bool(self.settings.api_key))
            run["answers"] = resolve_answers(run["questions"], data["answers"], data["skip"])
            run.update(skipped=data["skip"], answers_submitted=True, status="generating", stage="research", error=None)
            run["input"] = {"goal": run["goal"], "context": json.dumps({
                "questions": run["questions"], "answers": run["answers"],
                "clarification_skipped": run["skipped"]}, ensure_ascii=False)}
            return run
        run = self.db.mutate_command(data["client_command_id"], run_id, data["expected_version"],
                                     {"action": "answers", "answers": data["answers"], "skip": data["skip"]}, submit)
        self.enqueue(run)
        await self.notify_run(run)
        return run

    async def blueprint(self, run_id: str, data: dict):
        run = self.db.blueprint_command(run_id, data, configured=bool(self.settings.api_key))
        self.enqueue(run)
        await self.notify_run(run)
        return run

    async def cancel(self, run_id: str, data: dict):
        def cancel(run):
            if run["status"] not in {"queued", "clarifying", "awaiting_answers", "awaiting_blueprint", "generating"}:
                raise AppError("state_conflict", "任务已经结束，不能再取消", 409)
            run.update(status="cancelled", error=None)
            return run
        run = self.db.mutate_command(data["client_command_id"], run_id, data["expected_version"],
                                     {"action": "cancel"}, cancel)
        await self.notify_run(run)
        return run

    async def retry(self, run_id: str, data: dict):
        run = self.db.retry_run(data["client_command_id"], run_id, data["expected_version"],
                                configured=bool(self.settings.api_key),
                                search_configured=bool(self.settings.tavily_api_key))
        self.enqueue(run)
        await self.notify_run(run)
        return run

    async def work(self):
        while True:
            run_id, phase = await self.queue.get()
            committed = False
            try:
                try:
                    run = self.db.get_run(run_id)
                except AppError as exc:
                    if exc.code == "not_found":
                        continue  # A cancelled course can be deleted while still queued.
                    raise
                allowed = {"queued"} if phase == "clarifying" else {"queued", "generating"}
                if run.get("kind", "course") == "course" and run["stage"] != phase:
                    continue
                run = self.db.transition(run_id, allowed,
                                         status="clarifying" if phase == "clarifying" else "generating", error=None)
                if run is None:
                    continue
                if phase == "units":
                    run = self.db.begin_unit(run_id)
                    if run is None:
                        continue
                await self.notify_run(run)
                # The worker remains occupied until this real network call returns.
                if run.get("kind") == "assistance":
                    from .assistance_generation import AssistantGenerator
                    loop = asyncio.get_running_loop()

                    def changed(snapshot):
                        loop.call_soon_threadsafe(asyncio.create_task, self.notify_run(snapshot))

                    generator = AssistantGenerator(self.settings, self.db, self.generator.stopping, changed)
                    result = await asyncio.to_thread(generator.generate, run)
                elif run.get("kind") == "research" or phase == "research":
                    loop = asyncio.get_running_loop()

                    def changed(snapshot):
                        loop.call_soon_threadsafe(asyncio.create_task, self.notify_run(snapshot))

                    researcher = Researcher(self.settings, self.db, self.generator.stopping, changed)
                    result = await asyncio.to_thread(researcher.generate, run)
                else:
                    result = await asyncio.to_thread(self.generator.generate, run, phase)
                if not self.accepting:
                    continue
                if phase == "clarifying":
                    updated = self.db.transition(run_id, {"clarifying"}, status="awaiting_answers",
                                                 questions=result.model_dump()["questions"])
                elif run.get("kind") == "research" or phase == "research":
                    updated = self.db.finish_research(run_id, result)
                elif phase == "blueprint":
                    updated = self.db.finish_blueprint(run_id, result)
                elif phase == "units":
                    updated = self.db.finish_unit(run_id, run["current_unit_id"], result)
                elif run.get("kind") == "quiz":
                    updated = self.db.finish_quiz(run_id, result)
                elif run.get("kind") == "assistance":
                    updated = self.db.finish_assistance(run_id, result)
                else:
                    updated = self.db.finish_lesson(run_id, result)
                committed = updated is not None
                if updated:
                    calls = self.db.calls(run_id)
                    reported = [c["usage"] for c in calls if c.get("usage")]
                    if reported:
                        totals = {key: sum(u.get(key, 0) for u in reported)
                                  for key in {k for u in reported for k in u}}
                        updated = self.db.transition(run_id, {updated["status"]}, usage=totals) or updated
                    await self.notify_run(updated)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Course run failed: %s (%s)", run_id, type(exc).__name__)
                # Notification/usage failures cannot undo a committed unit or
                # turn its pending successors into a failed generation.
                if committed:
                    continue
                with suppress(Exception):
                    updated = self.db.transition(run_id, {"queued", "clarifying", "generating"}, status="failed",
                        error=exc.public() if isinstance(exc, AppError) else {
                            "code": "generation_failed", "message": "生成或保存失败，未创建完成课程，请重试", "retryable": True})
                    if updated:
                        await self.notify_run(updated)
            finally:
                self.enqueued.discard((run_id, phase))
                # In particular units→units must enqueue only after removing this entry.
                try:
                    if committed and self.accepting:
                        await self.continue_committed_run(run_id)
                finally:
                    self.queue.task_done()

    async def continue_committed_run(self, run_id: str):
        """Retry only the latest-state read, never a model call or a commit.

        SQLite reads currently acquire a write transaction and can time out under
        contention. Keep that wait off the event loop and cancellable on close.
        Nothing is persisted to resume this retry after a process restart.
        """
        delay = 0.1
        while self.accepting and not self.generator.stopping.is_set():
            try:
                current = await asyncio.to_thread(self.db.get_run, run_id)
            except sqlite3.OperationalError as exc:
                code = getattr(exc, "sqlite_errorcode", None)
                locked = (code & 0xff in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} if code is not None
                          else str(exc) in {"database is locked", "database table is locked"})
                if locked:
                    logger.warning("Committed run state read deferred (%s)", type(exc).__name__)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 2)
                    continue
                logger.error("Committed run state read failed (%s)", type(exc).__name__)
                return
            except Exception as exc:
                logger.error("Committed run state read failed (%s)", type(exc).__name__)
                return
            if self.accepting and not self.generator.stopping.is_set():
                # A confirmation/revision can arrive while notifications await.
                # Only committed generating workflows continue automatically;
                # failed/in-flight calls need an explicit user retry.
                if current.get("kind", "course") == "course" and current["status"] == "generating":
                    self.enqueue(current)
            return
