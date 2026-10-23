"""Run with: uv run uvicorn hyperknow.main:app --host 127.0.0.1."""

from contextlib import asynccontextmanager
import sqlite3
from typing import Literal

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from .config import Settings
from .domain import AppError, Schema
from .lesson_domain import LessonSnapshot
from .quiz_domain import AttemptSnapshot, MAX_ELAPSED_MS, QuizSnapshot
from .runtime import CourseService, EventHub
from .storage import Database


class Command(Schema):
    client_command_id: str = Field(min_length=8, max_length=120)


class CreateRun(Command):
    goal: str = Field(min_length=2, max_length=4000)


class CreateResearch(CreateRun):
    context: str = Field(default="", max_length=6000)


class ChangeRun(Command):
    expected_version: int = Field(ge=1)


class Answer(Schema):
    question_id: str
    option_ids: list[str] = Field(default_factory=list, max_length=8)
    custom_text: str = Field(default="", max_length=2000)


class SubmitAnswers(ChangeRun):
    skip: bool = False
    answers: list[Answer] = Field(default_factory=list, max_length=5)


class SubmitBlueprint(ChangeRun):
    approve: bool = Field(strict=True)
    feedback: str = Field(default="", max_length=6000)


class LessonCommand(ChangeRun):
    script_id: str = Field(min_length=1)


class SaveProgress(LessonCommand):
    cursor: int = Field(ge=-1)
    play_intent: Literal["paused", "playing"]


class AskQuestion(LessonCommand):
    cursor: int = Field(ge=-1)
    question: str = Field(min_length=2, max_length=2000)
    was_playing: bool


class AnswerQuiz(ChangeRun):
    question_id: str = Field(min_length=1, max_length=80)
    option_ids: list[str] = Field(max_length=8)
    skipped: bool = Field(strict=True)
    elapsed_ms: int = Field(strict=True, ge=0, le=MAX_ELAPSED_MS)


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

    @app.post("/api/research-runs", status_code=202)
    async def research_run(data: CreateResearch):
        return await app.state.service.research(data.goal, data.context, data.client_command_id)

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

    @app.post("/api/runs/{run_id}/blueprint", status_code=202)
    async def blueprint(run_id: str, data: SubmitBlueprint):
        return await app.state.service.blueprint(run_id, data.model_dump())

    @app.post("/api/runs/{run_id}/retry", status_code=202)
    async def retry(run_id: str, data: ChangeRun):
        return await app.state.service.retry(run_id, data.model_dump())

    @app.get("/api/courses")
    async def courses():
        return {"courses": app.state.db.list_records("courses")}

    @app.get("/api/courses/{course_id}")
    async def course(course_id: str):
        return app.state.db.get_course(course_id)

    @app.get("/api/sessions/{session_id}", response_model=LessonSnapshot)
    @app.get("/api/sessions/{session_id}/lesson", response_model=LessonSnapshot)
    async def lesson(session_id: str):
        return app.state.db.get_lesson(session_id)

    @app.post("/api/sessions/{session_id}/prepare", response_model=LessonSnapshot)
    async def prepare(session_id: str, data: Command):
        return await app.state.service.prepare(session_id, data.model_dump())

    @app.put("/api/sessions/{session_id}/progress", response_model=LessonSnapshot)
    async def progress(session_id: str, data: SaveProgress):
        return await app.state.service.progress(session_id, data.model_dump())

    @app.post("/api/sessions/{session_id}/questions", status_code=202, response_model=LessonSnapshot)
    async def question(session_id: str, data: AskQuestion):
        return await app.state.service.question(session_id, data.model_dump())

    @app.post("/api/sessions/{session_id}/complete", response_model=LessonSnapshot)
    async def complete(session_id: str, data: LessonCommand):
        return await app.state.service.complete(session_id, data.model_dump())

    @app.get("/api/sessions/{session_id}/practice", response_model=QuizSnapshot)
    async def practice(session_id: str):
        return app.state.db.get_quiz_target("practice", session_id)

    @app.post("/api/sessions/{session_id}/practice/prepare", response_model=QuizSnapshot)
    async def practice_prepare(session_id: str, data: Command):
        return await app.state.service.quiz_prepare("practice", session_id, data.model_dump())

    @app.get("/api/exams/{exam_id}", response_model=QuizSnapshot)
    async def exam(exam_id: str):
        return app.state.db.get_quiz_target("exam", exam_id)

    @app.post("/api/exams/{exam_id}/prepare", response_model=QuizSnapshot)
    async def exam_prepare(exam_id: str, data: Command):
        return await app.state.service.quiz_prepare("exam", exam_id, data.model_dump())

    @app.post("/api/quizzes/{quiz_id}/attempts", response_model=AttemptSnapshot)
    async def attempt_create(quiz_id: str, data: Command):
        return await app.state.service.attempt_create(quiz_id, data.model_dump())

    @app.get("/api/quizzes/{quiz_id}/attempts")
    async def attempts(quiz_id: str):
        return app.state.db.list_attempts(quiz_id)

    @app.get("/api/attempts/{attempt_id}", response_model=AttemptSnapshot)
    async def attempt(attempt_id: str):
        return app.state.db.get_attempt(attempt_id)

    @app.post("/api/attempts/{attempt_id}/answers", response_model=AttemptSnapshot)
    async def answer_quiz(attempt_id: str, data: AnswerQuiz):
        return await app.state.service.attempt_change(attempt_id, "answers", data.model_dump())

    @app.post("/api/attempts/{attempt_id}/next", response_model=AttemptSnapshot)
    async def attempt_next(attempt_id: str, data: ChangeRun):
        return await app.state.service.attempt_change(attempt_id, "next", data.model_dump())

    @app.post("/api/attempts/{attempt_id}/submit", response_model=AttemptSnapshot)
    async def attempt_submit(attempt_id: str, data: ChangeRun):
        return await app.state.service.attempt_change(attempt_id, "submit", data.model_dump())

    @app.websocket("/api/events")
    async def events(socket: WebSocket):
        hub = app.state.hub
        await socket.accept()
        hub.subscribers[socket] = set()
        try:
            await hub.send(socket, {"type": "connected"})
            while True:
                message = await socket.receive_json()
                if not isinstance(message, dict):
                    await hub.send(socket, {"type": "error", "message": "无效订阅请求"})
                    continue
                if message.get("type") == "ping":
                    await hub.send(socket, {"type": "pong"})
                    continue
                topic = message.get("topic", "")
                if message.get("type") != "subscribe" or not isinstance(topic, str) or ":" not in topic:
                    await hub.send(socket, {"type": "error", "message": "仅支持订阅运行、课时或课程状态"})
                    continue
                kind, resource_id = topic.split(":", 1)
                readers = {"run": app.state.db.get_run, "session": app.state.db.get_lesson,
                           "course": app.state.db.get_course,
                           "quiz_target": app.state.db.get_quiz_target_key,
                           "attempt": app.state.db.get_attempt}
                if kind not in readers:
                    await hub.send(socket, {"type": "error", "message": "未知订阅类型"})
                    continue
                try:
                    readers[kind](resource_id)
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
