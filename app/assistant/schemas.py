from typing import Literal

from pydantic import BaseModel, Field


class DraftOption(BaseModel):
    value: str
    label: str
    consequence: str | None = None


class ProductCritique(BaseModel):
    code: Literal[
        "compound_question",
        "missing_escape_hatch",
        "missing_deadline",
        "dependency_flattened",
    ]
    message: str
    question_index: int | None = None


class DraftQuestion(BaseModel):
    template_id: Literal["open_question", "approval", "directional_check", "decision_fork"]
    prompt: str
    help_text: str | None = None
    allow_comment: bool = True
    options: list[DraftOption] = Field(default_factory=list)
    depends_on_question_index: int | None = None


class QuestionDraft(BaseModel):
    title: str
    intro: str | None = None
    questions: list[DraftQuestion] = Field(min_length=1)
    critiques: list[ProductCritique] = Field(default_factory=list)


class NeedsClarification(BaseModel):
    question: str
    reason: str


AssistantOutput = QuestionDraft | NeedsClarification


class AssistantTurn(BaseModel):
    output: AssistantOutput
    conversation_id: str | None
    messages: list[dict[str, object]]
