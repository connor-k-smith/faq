from uuid import uuid4

import pytest

from app.domain.expressions import (
    evaluate_condition,
    parse_condition,
    validate_dependency_graph,
)


def test_dependency_requires_a_question_id() -> None:
    with pytest.raises(ValueError, match="question_id"):
        parse_condition({"op": "eq", "value": "yes"}, require_question_id=True)

    condition = parse_condition(
        {"question_id": str(uuid4()), "op": "in", "value": ["yes", "mostly"]},
        require_question_id=True,
    )
    assert evaluate_condition(condition, "yes", answered=True)


def test_select_many_comparisons_use_set_semantics() -> None:
    equal = parse_condition({"op": "eq", "value": ["a", "b"]})
    intersects = parse_condition({"op": "in", "value": ["c", "b"]})

    assert evaluate_condition(equal, ["b", "a"], answered=True)
    assert evaluate_condition(intersects, ["a", "b"], answered=True)


def test_unanswered_never_satisfies_value_comparisons() -> None:
    condition = parse_condition({"op": "neq", "value": "yes"})

    assert not evaluate_condition(condition, None, answered=False)
    assert evaluate_condition(parse_condition({"op": "unanswered"}), None, answered=False)


@pytest.mark.parametrize("operator", ["in", "not_in"])
def test_membership_operators_require_an_array(operator: str) -> None:
    with pytest.raises(ValueError, match="array"):
        parse_condition({"op": operator, "value": "yes"})


def test_dependency_graph_rejects_cross_ask_self_reference_and_cycles() -> None:
    first, second, outside, actor = uuid4(), uuid4(), uuid4(), uuid4()

    with pytest.raises(ValueError, match="same Ask"):
        validate_dependency_graph(
            {first: {"question_id": str(outside), "op": "answered"}},
            {first: {actor}},
        )
    with pytest.raises(ValueError, match="itself"):
        validate_dependency_graph(
            {first: {"question_id": str(first), "op": "answered"}},
            {first: {actor}},
        )
    with pytest.raises(ValueError, match="acyclic"):
        validate_dependency_graph(
            {
                first: {"question_id": str(second), "op": "answered"},
                second: {"question_id": str(first), "op": "answered"},
            },
            {first: {actor}, second: {actor}},
        )


def test_dependency_graph_requires_prerequisite_assignee_coverage() -> None:
    prerequisite, dependent, first_actor, second_actor = (uuid4() for _ in range(4))

    with pytest.raises(ValueError, match="assignee"):
        validate_dependency_graph(
            {
                prerequisite: None,
                dependent: {"question_id": str(prerequisite), "op": "answered"},
            },
            {prerequisite: {first_actor}, dependent: {first_actor, second_actor}},
        )
