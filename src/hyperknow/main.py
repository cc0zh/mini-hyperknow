"""Run with: uv run uvicorn hyperknow.main:app --host 127.0.0.1."""

from contextlib import asynccontextmanager
import sqlite3

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from .config import Settings
from .domain import AppError, Schema
from .runtime import CourseService, EventHub
from .storage import Database


class Command(Schema):
    client_command_id: str = Field(min_length=8, max_length=120)


class CreateRun(Command):
    goal: str = Field(min_length=2, max_length=4000)


class ChangeRun(Command):
    expected_version: int = Field(ge=1)


class Answer(Schema):
    question_id: str
    option_ids: list[str] = Field(default_factory=list, max_length=8)
    custom_text: str = Field(default="", max_length=2000)


class SubmitAnswers(ChangeRun):
    skip: bool = False
    answers: list[Answer] = Field(default_factory=list, max_length=5)


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings.load()
        db = Database(config.data_dir / "hyperknow.sqlite3")
        hub = EventHub()
        service = CourseService(config, db, hub)
        app.state.config, app.state.db, app.state.hub, app.state.service = config, db, hub, service
        service.start()
        try:
            yield
        finally:
            await service.close()

    app = FastAPI(title="mini-hyperknow", lifespan=lifespan)

    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content={"error": exc.public()})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc):
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_request", "message": "请求内容不符合要求，请检查输入", "retryable": False}})

    @app.exception_handler(sqlite3.Error)
    async def database_error(_request: Request, _exc):
        return JSONResponse(status_code=503, content={"error": {
            "code": "storage_unavailable", "message": "本地存储暂不可用，操作未确认保存，请重试", "retryable": True}})

    @app.get("/api/health")
    async def health():
        app.state.db.list_records("courses")
        cfg = app.state.config
        return {"status": "ok", "database": "ok", "model": {
            "configured": bool(cfg.api_key), "name": cfg.model, "verified": False}}

    @app.post("/api/course-runs", status_code=202)
    async def create_run(data: CreateRun):
        return await app.state.service.create(data.goal, data.client_command_id)

    @app.get("/api/runs")
    async def runs():
        return {"runs": app.state.db.list_records("runs")[:30]}

    @app.get("/api/runs/{run_id}")
    async def run(run_id: str):
        return app.state.db.get_run(run_id)

    @app.post("/api/runs/{run_id}/answers", status_code=202)
    async def answers(run_id: str, data: SubmitAnswers):
        return await app.state.service.answers(run_id, data.model_dump())

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str, data: ChangeRun):
        return await app.state.service.cancel(run_id, data.model_dump())

    @app.post("/api/runs/{run_id}/retry", status_code=202)
    async def retry(run_id: str, data: ChangeRun):
        return await app.state.service.retry(run_id, data.model_dump())

    @app.get("/api/courses")
    async def courses():
        return {"courses": app.state.db.list_records("courses")}

    @app.get("/api/courses/{course_id}")
    async def course(course_id: str):
        return app.state.db.get_course(course_id)

    @app.websocket("/api/events")
    async def events(socket: WebSocket):
        hub = app.state.hub
        await socket.accept()
        hub.subscribers[socket] = set()
        try:
            await hub.send(socket, {"type": "connected"})
            while True:
                message = await socket.receive_json()
                if message.get("type") == "ping":
                    await hub.send(socket, {"type": "pong"})
                    continue
                topic = message.get("topic", "")
                if message.get("type") != "subscribe" or not isinstance(topic, str) or not topic.startswith("run:"):
                    await hub.send(socket, {"type": "error", "message": "仅支持订阅课程运行状态"})
                    continue
                run_id = topic[4:]
                try:
                    app.state.db.get_run(run_id)
                except AppError:
                    await hub.send(socket, {"type": "error", "message": "任务不存在"})
                    continue
                hub.subscribers[socket].add(topic)
                await hub.send(socket, {"type": "subscribed", "topic": topic})
        except (WebSocketDisconnect, ValueError, RuntimeError):
            pass
        finally:
            hub.remove(socket)

    return app


app = create_app()
