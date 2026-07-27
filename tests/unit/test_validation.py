import pytest

from app.domain.enums import QuestionPrimitive
from app.domain.validation import (
    DomainValidationError,
    parse_date_value,
    parse_number_value,
    validate_comment_requirement,
    validate_value,
)


def test_select_one_accepts_only_stable_values_from_the_question() -> None:
    validate_value(
        QuestionPrimitive.SELECT_ONE,
        "yes",
        validation={},
        option_values={"yes", "mostly", "no"},
    )

    with pytest.raises(DomainValidationError, match="does not belong"):
        validate_value(
            QuestionPrimitive.SELECT_ONE,
            "Yes, directionally right",
            validation={},
            option_values={"yes", "mostly", "no"},
        )


def test_text_validation_counts_trimmed_content_for_minimum() -> None:
    with pytest.raises(DomainValidationError, match="at least 4"):
        validate_value(QuestionPrimitive.TEXT, "  no  ", validation={"min_length": 4})


def test_conditional_comment_is_server_authoritative() -> None:
    condition = {"op": "neq", "value": "yes"}

    validate_comment_requirement("yes", None, condition)
    with pytest.raises(DomainValidationError, match="comment is required"):
        validate_comment_requirement("mostly", "  ", condition)


def test_number_values_are_canonical_finite_json_numbers() -> None:
    assert parse_number_value("42") == 42
    assert parse_number_value(" 3.5 ") == 3.5
    validate_value(QuestionPrimitive.NUMBER, 3.5, validation={"min": 1, "max": 4})
    with pytest.raises(DomainValidationError, match="numeric"):
        validate_value(QuestionPrimitive.NUMBER, True, validation={})
    with pytest.raises(DomainValidationError, match="at least 1"):
        validate_value(QuestionPrimitive.NUMBER, 0, validation={"min": 1})
    with pytest.raises(DomainValidationError, match="finite"):
        parse_number_value("NaN")


def test_select_many_requires_unique_known_options_and_selection_bounds() -> None:
    validate_value(
        QuestionPrimitive.SELECT_MANY,
        ["email", "slack"],
        validation={"min_selections": 1, "max_selections": 2},
        option_values={"email", "slack", "web"},
    )
    with pytest.raises(DomainValidationError, match="unique"):
        validate_value(
            QuestionPrimitive.SELECT_MANY,
            ["email", "email"],
            validation={},
            option_values={"email"},
        )
    with pytest.raises(DomainValidationError, match="does not belong"):
        validate_value(
            QuestionPrimitive.SELECT_MANY,
            ["sms"],
            validation={},
            option_values={"email"},
        )


def test_date_values_are_canonical_and_respect_inclusive_bounds() -> None:
    assert parse_date_value(" 2026-07-30 ") == "2026-07-30"
    validate_value(
        QuestionPrimitive.DATE,
        "2026-07-30",
        validation={"not_before": "2026-07-30", "not_after": "2026-08-01"},
    )
    with pytest.raises(DomainValidationError, match="valid ISO 8601"):
        validate_value(QuestionPrimitive.DATE, "2026-02-29", validation={})
    with pytest.raises(DomainValidationError, match="on or after 2026-07-30"):
        validate_value(
            QuestionPrimitive.DATE,
            "2026-07-29",
            validation={"not_before": "2026-07-30"},
        )
def test_reserved_primitive_is_not_silently_accepted() -> None:
    with pytest.raises(DomainValidationError, match="not renderable"):
        validate_value(QuestionPrimitive.RANK, ["first"], validation={})
