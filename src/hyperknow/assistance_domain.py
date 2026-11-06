"""Independent teaching content and artifact validation, without course identities."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from .domain import Schema
from .lesson_domain import BoardFrame, validate_board_references

Text = Annotated[str, Field(min_length=1, max_length=3000)]


class TeachingQuestion(Schema):
    question_id: str = Field(min_length=1, max_length=60)
    question: str = Field(min_length=1, max_length=600)
    options: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=6)
    multiple: bool = False

    @model_validator(mode="after")
    def choices(self):
        if len(self.options) == 1 or len(set(self.options)) != len(self.options):
            raise ValueError("choices must be distinct and either empty or at least two")
        if self.multiple and not self.options:
            raise ValueError("multiple choice requires options")
        return self


class TeachingSuggestion(Schema):
    """A learner message with explicit intent, independent of its wording."""

    label: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=600)
    action: Literal["message", "continue"]


class TeachingResponse(Schema):
    text: str = Field(min_length=1, max_length=12000)
    questions: list[TeachingQuestion] = Field(default_factory=list, max_length=3)
    plan: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=6)
    current_step: int = Field(default=0, ge=0, le=5, strict=True)
    waiting_for: Literal["answer", "continue", "none"] = "none"
    suggestions: list[TeachingSuggestion] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def consistent_state(self):
        if len({q.question_id for q in self.questions}) != len(self.questions):
            raise ValueError("question identities must be unique")
        if bool(self.questions) != (self.waiting_for == "answer"):
            raise ValueError("questions require waiting_for=answer and vice versa")
        if self.current_step >= max(1, len(self.plan)):
            raise ValueError("current_step must belong to the plan")
        if self.waiting_for == "continue" and self.current_step + 1 >= len(self.plan):
            raise ValueError("continue requires a pending next plan step")
        # While clarifying, there is no answer yet to branch from.
        if self.questions and self.suggestions:
            raise ValueError("suggestions and clarification questions are mutually exclusive")
        if any(s.action == "continue" for s in self.suggestions) and self.waiting_for != "continue":
            raise ValueError("continue suggestions require a pending next plan step")
        return self


class Flashcard(Schema):
    question: Text
    answer: Text


class ContinuationState(Schema):
    """Small authoritative state, independent of the optional history budget."""

    plan: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(min_length=2, max_length=6)
    current_step: int = Field(ge=1, le=5, strict=True)
    is_last_step: bool

    @model_validator(mode="after")
    def valid_next_step(self):
        if self.current_step >= len(self.plan) or self.is_last_step != (self.current_step + 1 == len(self.plan)):
            raise ValueError("continuation must name an actual next step and its exact final-step state")
        return self


class FlashcardsData(Schema):
    cards: list[Flashcard] = Field(min_length=1, max_length=6)


class QuizOption(Schema):
    id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=1500)


class ChatQuizQuestion(Schema):
    question_id: str = Field(min_length=1, max_length=60)
    question: Text
    options: list[QuizOption] = Field(min_length=2, max_length=6)
    correct_ids: list[str] = Field(min_length=1, max_length=6)
    explanation: Text

    @model_validator(mode="after")
    def valid_answers(self):
        ids = {option.id for option in self.options}
        if len(ids) != len(self.options) or len(set(self.correct_ids)) != len(self.correct_ids):
            raise ValueError("option and answer identities must be unique")
        if not set(self.correct_ids) <= ids:
            raise ValueError("correct answers must refer to actual options")
        return self


class QuizData(Schema):
    questions: list[ChatQuizQuestion] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_questions(self):
        if len({q.question_id for q in self.questions}) != len(self.questions):
            raise ValueError("question identities must be unique")
        return self


class AnimationData(Schema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    html: str = Field(min_length=1, max_length=80000)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.html.strip():
            raise ValueError("animation HTML must not be blank")
        return self


class AssistanceBoardStep(BoardFrame):
    """An independent artifact frame, not a course lesson step."""


class WhiteboardData(Schema):
    steps: list[AssistanceBoardStep] = Field(min_length=1, max_length=18)

    @model_validator(mode="after")
    def board(self):
        positions = [(step.page, step.column) for step in self.steps]
        if positions != sorted(positions) or positions[0][0] != 1:
            raise ValueError("whiteboard frames must start on page 1 in page/column order")
        validate_board_references(self.steps)
        return self


class DiagramData(Schema):
    """Mermaid source plus a caption; no rendered SVG is stored."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    source: str = Field(min_length=1, max_length=4000)
    caption: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.source.strip():
            raise ValueError("diagram source must not be blank")
        return self


ARTIFACT_SCHEMAS = {"flashcards": FlashcardsData, "quiz": QuizData, "whiteboard": WhiteboardData,
                    "animation": AnimationData, "diagram": DiagramData}


class ArtifactDraft(Schema):
    kind: Literal["flashcards", "quiz", "whiteboard", "animation", "diagram"]
    title: str = Field(min_length=1, max_length=200)
    data: dict

    @model_validator(mode="after")
    def validate_payload(self):
        self.data = ARTIFACT_SCHEMAS[self.kind].model_validate(self.data).model_dump()
        return self
