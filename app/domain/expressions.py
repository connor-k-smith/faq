from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

ConditionOperator = Literal["eq", "neq", "in", "not_in", "answered", "unanswered"]


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: ConditionOperator
    value: JsonValue = None
    question_id: UUID | None = None

    @model_validator(mode="after")
    def validate_operator_value(self) -> "Condition":
        if self.op in {"eq", "neq"} and self.value is None:
            raise ValueError(f"{self.op} requires value")
        if self.op in {"in", "not_in"} and not isinstance(self.value, list):
            raise ValueError(f"{self.op} requires an array value")
        if self.op in {"answered", "unanswered"} and self.value is not None:
            raise ValueError(f"{self.op} does not accept value")
        return self


def parse_condition(raw: object, *, require_question_id: bool = False) -> Condition:
    condition = Condition.model_validate(raw)
    if require_question_id and condition.question_id is None:
        raise ValueError("depends_on requires question_id")
    return condition


def evaluate_condition(condition: Condition, value: JsonValue, *, answered: bool) -> bool:
    if condition.op == "answered":
        return answered
    if condition.op == "unanswered":
        return not answered
    if not answered:
        return False

    expected = condition.value
    if condition.op in {"eq", "neq"}:
        equal = _equal(value, expected)
        return equal if condition.op == "eq" else not equal

    assert isinstance(expected, list)
    if isinstance(value, list):
        intersects = bool(_as_comparable_set(value) & _as_comparable_set(expected))
    else:
        intersects = value in expected
    return intersects if condition.op == "in" else not intersects


def validate_dependency_graph(
    dependencies: dict[UUID, object | None],
    assignees: dict[UUID, set[UUID]],
) -> dict[UUID, Condition]:
    """Parse dependencies and validate their graph and recipient coverage."""
    parsed: dict[UUID, Condition] = {}
    for question_id, raw in dependencies.items():
        if raw is None:
            continue
        condition = parse_condition(raw, require_question_id=True)
        prerequisite_id = condition.question_id
        assert prerequisite_id is not None
        if prerequisite_id == question_id:
            raise ValueError("a Question cannot depend on itself")
        if prerequisite_id not in dependencies:
            raise ValueError("depends_on must reference a Question in the same Ask")
        if not assignees.get(question_id, set()).issubset(assignees.get(prerequisite_id, set())):
            raise ValueError("every dependent assignee must also receive its prerequisite")
        parsed[question_id] = condition

    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(question_id: UUID) -> None:
        if question_id in visiting:
            raise ValueError("Question dependencies must be acyclic")
        if question_id in visited:
            return
        visiting.add(question_id)
        condition = parsed.get(question_id)
        if condition is not None:
            assert condition.question_id is not None
            visit(condition.question_id)
        visiting.remove(question_id)
        visited.add(question_id)

    for question_id in dependencies:
        visit(question_id)
    return parsed


def _equal(left: JsonValue, right: JsonValue) -> bool:
    if isinstance(left, list) and isinstance(right, list):
        return _as_comparable_set(left) == _as_comparable_set(right)
    return left == right


def _as_comparable_set(values: list[JsonValue]) -> set[str]:
    return {repr(value) for value in values}
