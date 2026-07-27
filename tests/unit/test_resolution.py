import pytest

from app.domain.enums import DecisionBasis, QuestionPrimitive
from app.domain.resolution import ResolutionInput, render_select_one, resolve


@pytest.mark.parametrize(
    ("eligible", "values", "basis", "winner", "conflict"),
    [
        (1, ("yes",), DecisionBasis.SINGLE_RESPONDENT, True, False),
        (2, ("yes", "yes"), DecisionBasis.UNANIMOUS, True, False),
        (2, ("yes", "no"), DecisionBasis.ASKER_JUDGMENT, False, True),
        (4, ("yes", "yes", "no"), DecisionBasis.MAJORITY, True, False),
        (4, ("yes", "no"), DecisionBasis.ASKER_JUDGMENT, False, True),
        (4, ("yes", "yes"), DecisionBasis.ASKER_JUDGMENT, False, False),
    ],
)
def test_select_one_resolution(
    eligible: int,
    values: tuple[str, ...],
    basis: DecisionBasis,
    winner: bool,
    conflict: bool,
) -> None:
    result = resolve(ResolutionInput(eligible, values, QuestionPrimitive.SELECT_ONE))

    assert result.basis == basis
    assert result.has_winner is winner
    assert result.conflict is conflict


def test_deadline_without_substantive_response_expires_without_deciding() -> None:
    result = resolve(ResolutionInput(2, (), QuestionPrimitive.SELECT_ONE, deadline=True))

    assert result.basis == DecisionBasis.EXPIRED_NO_RESPONSE
    assert result.value is None
    assert result.has_winner is False


@pytest.mark.parametrize(
    "primitive",
    [
        QuestionPrimitive.SELECT_MANY,
        QuestionPrimitive.TEXT,
        QuestionPrimitive.NUMBER,
        QuestionPrimitive.DATE,
    ],
)
def test_non_scalar_primitives_never_compute_a_multi_assignee_winner(
    primitive: QuestionPrimitive,
) -> None:
    result = resolve(ResolutionInput(2, ("same", "same"), primitive))

    assert result.basis == DecisionBasis.ASKER_JUDGMENT
    assert result.has_winner is False


def test_sole_assignee_non_scalar_value_is_carried_as_a_proposal() -> None:
    result = resolve(ResolutionInput(1, (42,), QuestionPrimitive.NUMBER))

    assert result.basis == DecisionBasis.SINGLE_RESPONDENT
    assert result.value == 42
    assert result.has_winner is True


def test_renderer_is_deterministic_and_normalizes_outer_whitespace() -> None:
    assert render_select_one(" Ship this? ", " Yes ") == "Ship this?: Yes."
    assert render_select_one(" Ship this? ", " Yes ") == render_select_one("Ship this?", "Yes")
