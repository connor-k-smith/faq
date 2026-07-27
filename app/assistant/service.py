import json
from collections.abc import Sequence
from typing import Protocol, cast

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from app.assistant.schemas import AssistantOutput, AssistantTurn, NeedsClarification, QuestionDraft
from app.config import get_settings

PROMPT_VERSION = "draft-v2"
SYSTEM_PROMPT = """You turn rough internal decision material into a concise executable Ask.
Preserve one coherent cognitive unit instead of splitting every assertion. Forward-load deferred
followups and surface unasked load-bearing questions. Return NeedsClarification when the source is
too vague to identify a useful decision. Supported templates are open_question, approval,
directional_check, and decision_fork. Every decision_fork option requires a consequence. Use
Use depends_on_question_index when a Question should activate only after another suggested Question
has been answered. The index must reference a different Question in the same generated draft.
Product-quality concerns belong in critiques and must not prevent a valid draft."""


class DraftAssistant(Protocol):
    def run(
        self,
        source: str,
        *,
        history: Sequence[ModelMessage],
        conversation_id: str | None,
    ) -> AssistantTurn: ...


class PydanticDraftAssistant:
    def __init__(self) -> None:
        settings = get_settings()
        self.agent = cast(
            Agent[None, AssistantOutput],
            Agent(
                settings.assistant_model,
                output_type=[QuestionDraft, NeedsClarification],
                system_prompt=SYSTEM_PROMPT,
                retries=2,
            ),
        )

        @self.agent.output_validator
        def validate_output(output: AssistantOutput) -> AssistantOutput:
            if isinstance(output, NeedsClarification):
                return output
            if not output.title.strip():
                raise ModelRetry("The Ask title is required")
            for index, question in enumerate(output.questions):
                if not question.prompt.strip():
                    raise ModelRetry("Every question requires a prompt")
                if question.depends_on_question_index is not None and (
                    question.depends_on_question_index < 0
                    or question.depends_on_question_index >= len(output.questions)
                    or question.depends_on_question_index == index
                ):
                    raise ModelRetry("A dependency must reference another question in this draft")
                if question.template_id == "open_question" and question.options:
                    raise ModelRetry("Open questions cannot have options")
                if question.template_id != "open_question" and len(question.options) < 2:
                    raise ModelRetry("Select-one questions require at least two options")
                values = [option.value.strip() for option in question.options]
                labels = [option.label.strip() for option in question.options]
                if (
                    any(not value for value in values)
                    or any(not label for label in labels)
                    or len(values) != len(set(values))
                ):
                    raise ModelRetry("Option keys must be present and unique")
                if question.template_id == "decision_fork" and any(
                    not (option.consequence or "").strip() for option in question.options
                ):
                    raise ModelRetry("Every decision-fork option requires a consequence")
            return output

    def run(
        self,
        source: str,
        *,
        history: Sequence[ModelMessage],
        conversation_id: str | None,
    ) -> AssistantTurn:
        result = self.agent.run_sync(
            source, message_history=history, conversation_id=conversation_id
        )
        messages = json.loads(result.all_messages_json())
        return AssistantTurn(
            output=result.output,
            conversation_id=result.conversation_id,
            messages=messages,
        )


def parse_history(payload: list[dict[str, object]]) -> list[ModelMessage]:
    return ModelMessagesTypeAdapter.validate_python(payload)


def get_draft_assistant() -> DraftAssistant:
    return PydanticDraftAssistant()
