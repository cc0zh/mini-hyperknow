"""HTTP commands for independent assistance, using the shared service/worker."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field, model_validator

from .domain import Schema


class AssistanceCommand(Schema):
    client_command_id: str = Field(min_length=8, max_length=120)


class SubmitTurn(AssistanceCommand):
    expected_version: int = Field(strict=True, ge=1)
    text: str = Field(default="", max_length=12000)
    action: Literal["message", "continue"] = "message"
    artifact_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def valid_question(self):
        if self.action == "message" and not self.text.strip():
            raise ValueError("message requires nonempty text")
        if self.artifact_id and self.action != "message":
            raise ValueError("artifact references are only for whiteboard questions")
        return self


class ArtifactProgress(AssistanceCommand):
    expected_version: int = Field(strict=True, ge=1)
    cursor: int = Field(strict=True, ge=-1)


class ArtifactFeedback(AssistanceCommand):
    expected_version: int = Field(strict=True, ge=1)
    vote: Literal["up", "down"]


router = APIRouter(prefix="/api/assistance")


@router.post("/conversations")
async def create_conversation(data: AssistanceCommand, request: Request):
    snapshot = request.app.state.db.create_assistance_conversation(data.client_command_id)
    await request.app.state.service.notify_assistance(snapshot)
    return snapshot


@router.get("/conversations")
async def conversations(request: Request):
    return {"conversations": request.app.state.db.list_assistance_conversations()}


@router.get("/conversations/{conversation_id}")
async def conversation(conversation_id: str, request: Request):
    return request.app.state.db.get_assistance_conversation(conversation_id)


@router.post("/conversations/{conversation_id}/turns", status_code=202)
async def turn(conversation_id: str, data: SubmitTurn, request: Request):
    return await request.app.state.service.assistance_turn(conversation_id, data.model_dump())


@router.get("/artifacts/{artifact_id}")
async def artifact(artifact_id: str, request: Request):
    return request.app.state.db.get_assistance_artifact(artifact_id)


@router.put("/artifacts/{artifact_id}/progress")
async def progress(artifact_id: str, data: ArtifactProgress, request: Request):
    snapshot = request.app.state.db.assistance_progress(artifact_id, data.model_dump())
    await request.app.state.hub.resource_changed("artifact", artifact_id, snapshot["version"])
    return snapshot


@router.put("/artifacts/{artifact_id}/feedback")
async def feedback(artifact_id: str, data: ArtifactFeedback, request: Request):
    snapshot = request.app.state.db.assistance_feedback(artifact_id, data.model_dump())
    await request.app.state.hub.resource_changed("artifact", artifact_id, snapshot["version"])
    return snapshot
