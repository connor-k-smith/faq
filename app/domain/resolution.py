from collections import Counter
from dataclasses import dataclass

from pydantic import JsonValue

from app.domain.enums import DecisionBasis, QuestionPrimitive

RENDERER_VERSION = "deterministic-v1"


@dataclass(frozen=True)
class ResolutionInput:
    eligible_count: int
    substantive_values: tuple[JsonValue, ...]
    primitive: QuestionPrimitive
    deadline: bool = False


@dataclass(frozen=True)
class Resolution:
    basis: DecisionBasis
    value: JsonValue
    has_winner: bool
    conflict: bool


def resolve(input_: ResolutionInput) -> Resolution:
    values = input_.substantive_values
    if not values:
        basis = (
            DecisionBasis.EXPIRED_NO_RESPONSE if input_.deadline else DecisionBasis.ASKER_JUDGMENT
        )
        return Resolution(basis, None, False, False)
    if input_.eligible_count == 1:
        return Resolution(DecisionBasis.SINGLE_RESPONDENT, values[0], True, False)
    if input_.primitive != QuestionPrimitive.SELECT_ONE:
        value = values[0] if len(values) == 1 else None
        return Resolution(DecisionBasis.ASKER_JUDGMENT, value, False, False)

    scalar_values = tuple(value for value in values if isinstance(value, str))
    conflict = len(set(scalar_values)) >= 2
    counts = Counter(scalar_values)
    if len(values) <= input_.eligible_count / 2 or not counts:
        return Resolution(DecisionBasis.ASKER_JUDGMENT, None, False, conflict)
    winner, votes = counts.most_common(1)[0]
    if votes <= len(values) / 2:
        return Resolution(DecisionBasis.ASKER_JUDGMENT, None, False, conflict)
    unanimous = len(values) == input_.eligible_count and votes == input_.eligible_count
    basis = DecisionBasis.UNANIMOUS if unanimous else DecisionBasis.MAJORITY
    return Resolution(basis, winner, True, False)


def render_select_one(prompt: str, option_label: str) -> str:
    """Render canonical prose without ambient state or nondeterministic inputs."""
    return f"{prompt.strip()}: {option_label.strip()}."
