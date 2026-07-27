import math
import re
from collections.abc import Collection, Mapping
from datetime import date
from typing import cast

from pydantic import JsonValue

from app.domain.enums import QuestionPrimitive
from app.domain.expressions import evaluate_condition, parse_condition


class DomainValidationError(ValueError):
    pass


def validate_value(
    primitive: QuestionPrimitive,
    value: JsonValue,
    *,
    validation: Mapping[str, object],
    option_values: Collection[str] = (),
) -> None:
    if primitive == QuestionPrimitive.SELECT_ONE:
        _validate_select_one(value, option_values)
        return
    if primitive == QuestionPrimitive.SELECT_MANY:
        _validate_select_many(value, option_values, validation)
        return
    if primitive == QuestionPrimitive.TEXT:
        _validate_text(value, validation)
        return
    if primitive == QuestionPrimitive.NUMBER:
        _validate_number(value, validation)
        return
    if primitive == QuestionPrimitive.DATE:
        _validate_date(value, validation)
        return
    raise DomainValidationError(f"{primitive.value} is not renderable")


def parse_number_value(raw: str) -> int | float:
    normalized = raw.strip()
    if not normalized:
        raise DomainValidationError("number requires a value")
    try:
        value: int | float = (
            int(normalized) if re.fullmatch(r"[+-]?\d+", normalized) else float(normalized)
        )
    except ValueError as error:
        raise DomainValidationError("number requires a valid numeric value") from error
    if isinstance(value, float) and not math.isfinite(value):
        raise DomainValidationError("number must be finite")
    return value


def parse_date_value(raw: str) -> str:
    value = raw.strip()
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise DomainValidationError("date requires a valid ISO 8601 date") from error
    if parsed.isoformat() != value:
        raise DomainValidationError("date requires a valid ISO 8601 date")
    return value


def validate_comment_requirement(
    value: JsonValue,
    comment: str | None,
    raw_condition: object | None,
) -> None:
    if raw_condition is None:
        return
    condition = parse_condition(raw_condition)
    if evaluate_condition(condition, value, answered=True) and not (comment and comment.strip()):
        raise DomainValidationError("a comment is required for this answer")


def _validate_select_one(value: JsonValue, option_values: Collection[str]) -> None:
    if not isinstance(value, str):
        raise DomainValidationError("select_one requires an option value string")
    if value not in option_values:
        raise DomainValidationError("selected option does not belong to this question")


def _validate_select_many(
    value: JsonValue, option_values: Collection[str], validation: Mapping[str, object]
) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DomainValidationError("select_many requires an array of option value strings")
    if len(set(value)) != len(value):
        raise DomainValidationError("selected options must be unique")
    if any(item not in option_values for item in value):
        raise DomainValidationError("selected option does not belong to this question")
    minimum = validation.get("min_selections", 0)
    maximum = validation.get("max_selections")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        raise DomainValidationError("select_many min_selections must be a non-negative integer")
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < minimum
    ):
        raise DomainValidationError(
            "select_many max_selections must be an integer not below min_selections"
        )
    if len(value) < minimum:
        raise DomainValidationError(f"select at least {minimum} options")
    if maximum is not None and len(value) > maximum:
        raise DomainValidationError(f"select at most {maximum} options")


def _validate_text(value: JsonValue, validation: Mapping[str, object]) -> None:
    if not isinstance(value, str):
        raise DomainValidationError("text requires a string")
    minimum = validation.get("min_length", 0)
    maximum = validation.get("max_length")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        raise DomainValidationError("text min_length must be a non-negative integer")
    if maximum is not None and (
        not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < minimum
    ):
        raise DomainValidationError("text max_length must be an integer not below min_length")
    if len(value.strip()) < minimum:
        raise DomainValidationError(f"text must contain at least {minimum} characters")
    if maximum is not None and len(value) > maximum:
        raise DomainValidationError(f"text must contain at most {maximum} characters")


def _validate_number(value: JsonValue, validation: Mapping[str, object]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainValidationError("number requires a numeric value")
    if isinstance(value, float) and not math.isfinite(value):
        raise DomainValidationError("number must be finite")
    minimum = validation.get("min")
    maximum = validation.get("max")
    for name, boundary in (("min", minimum), ("max", maximum)):
        if boundary is not None and (
            isinstance(boundary, bool) or not isinstance(boundary, (int, float))
        ):
            raise DomainValidationError(f"number {name} must be numeric")
    numeric_minimum = cast(int | float | None, minimum)
    numeric_maximum = cast(int | float | None, maximum)
    if (
        numeric_minimum is not None
        and numeric_maximum is not None
        and numeric_minimum > numeric_maximum
    ):
        raise DomainValidationError("number max must not be below min")
    if numeric_minimum is not None and value < numeric_minimum:
        raise DomainValidationError(f"number must be at least {numeric_minimum}")
    if numeric_maximum is not None and value > numeric_maximum:
        raise DomainValidationError(f"number must be at most {numeric_maximum}")


def _validate_date(value: JsonValue, validation: Mapping[str, object]) -> None:
    if not isinstance(value, str):
        raise DomainValidationError("date requires an ISO 8601 date string")
    parsed = _parse_date(value, "date")
    not_before = _optional_date_boundary(validation, "not_before")
    not_after = _optional_date_boundary(validation, "not_after")
    if not_before is not None and not_after is not None and not_before > not_after:
        raise DomainValidationError("date not_after must not be before not_before")
    if not_before is not None and parsed < not_before:
        raise DomainValidationError(f"date must be on or after {not_before.isoformat()}")
    if not_after is not None and parsed > not_after:
        raise DomainValidationError(f"date must be on or before {not_after.isoformat()}")


def _optional_date_boundary(validation: Mapping[str, object], name: str) -> date | None:
    value = validation.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainValidationError(f"date {name} must be an ISO 8601 date string")
    return _parse_date(value, f"date {name}")


def _parse_date(value: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise DomainValidationError(f"{label} must be a valid ISO 8601 date") from error
    if parsed.isoformat() != value:
        raise DomainValidationError(f"{label} must be a valid ISO 8601 date")
    return parsed
