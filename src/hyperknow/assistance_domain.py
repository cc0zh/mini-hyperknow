"""Independent teaching content and artifact validation, without course identities."""

import re
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from .domain import Schema
from .lesson_domain import BoardScriptDraft, BoardStepDraft

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
    """A concrete next message the learner can send with one click.

    The label is what the learner reads and the text is the message itself.
    Artifact kind is not a user-facing choice: the model decides which tool to
    call, so a suggestion never names a turn action.
    """

    label: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=600)


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


class WhiteboardData(Schema):
    steps: list[BoardStepDraft] = Field(min_length=1, max_length=18)

    @model_validator(mode="after")
    def board(self):
        BoardScriptDraft(title="独立课堂", steps=self.steps)
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

# The model chooses the artifact; the learner never picks a kind. Only an
# explicit request in the learner's own text still guarantees that a concrete
# artifact of the named kind is produced, and that responsibility is one item
# of this closed vocabulary.
ARTIFACT_INTENTS = {
    "flashcards": ("闪卡", "抽认卡", "记忆卡", "flashcard"),
    "quiz": ("测验", "自测", "测试题", "选择题", "出题", "做题", "quiz"),
    "whiteboard": ("白板", "板书", "whiteboard"),
    "animation": ("动画", "animation"),
    "diagram": ("流程图", "结构图", "示意图", "关系图", "思维导图", "mermaid"),
}
NEGATIONS = ("不", "别", "无需", "不要", "不需要", "跳过", "取消")
# A phrase like "解释当前白板第一步" talks about the artifact that already
# exists. Naming one is not a request to make another, so a reference marker
# immediately before the keyword suppresses the request; the model still
# decides freely when no kind was requested.
REFERENCES = ("当前", "现在", "这一", "这块", "这个", "刚才", "上面", "上述", "以上",
              "已确认", "已有的", "现有", "本轮")


def requested_artifacts(text: str) -> list[str]:
    """Return the artifact kinds the learner named, never more than one.

    A request is read per clause so "不要闪卡，要一道选择题" names only the
    quiz. This decides whether a turn keeps the hard guarantee that a named
    artifact must exist; it never grants a tool or widens model permissions.
    """
    requested = []
    for clause in re.split(r"[，。；！？,.;!?\n]", text or ""):
        lowered = clause.lower()
        for kind, keywords in ARTIFACT_INTENTS.items():
            position = min((lowered.find(keyword) for keyword in keywords if keyword in lowered), default=-1)
            if position < 0 or kind in requested:
                continue
            prefix = lowered[max(0, position - 6):position]
            if any(negation in prefix for negation in NEGATIONS):
                continue
            if any(marker in prefix for marker in REFERENCES):
                continue
            requested.append(kind)
    return requested[:1]


def forbidden_artifacts(text: str) -> list[str]:
    """Return the artifact kinds the learner explicitly refused.

    "不生成新白板" is a prohibition, not a missing request. A real model
    created a second board while the learner had just asked it not to, so the
    negative case is recorded on its own instead of being inferred from an
    empty request list.
    """
    refused = []
    for clause in re.split(r"[，。；！？,.;!?\n]", text or ""):
        lowered = clause.lower()
        for kind, keywords in ARTIFACT_INTENTS.items():
            position = min((lowered.find(keyword) for keyword in keywords if keyword in lowered), default=-1)
            if position < 0 or kind in refused:
                continue
            if any(negation in lowered[max(0, position - 6):position] for negation in NEGATIONS):
                refused.append(kind)
    return refused


class ArtifactDraft(Schema):
    kind: Literal["flashcards", "quiz", "whiteboard", "animation", "diagram"]
    title: str = Field(min_length=1, max_length=200)
    data: dict

    @model_validator(mode="after")
    def validate_payload(self):
        self.data = ARTIFACT_SCHEMAS[self.kind].model_validate(self.data).model_dump()
        return self
