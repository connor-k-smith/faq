from typing import cast

from pydantic import JsonValue

from app.domain.enums import AssignmentState, ResponseDisposition
from app.domain.expressions import Condition, evaluate_condition


def derive_assignment_state(
    condition: Condition | None,
    prerequisite_state: AssignmentState | None,
    prerequisite_value: object | None,
    prerequisite_disposition: ResponseDisposition | None,
    own_disposition: ResponseDisposition | None,
) -> AssignmentState:
    """Derive current assignment state without discarding its own response."""
    if condition is not None:
        if prerequisite_state is None:
            raise ValueError("every dependent assignee must also receive its prerequisite")
        if prerequisite_state in (AssignmentState.EXPIRED, AssignmentState.WITHDRAWN):
            return AssignmentState.WITHDRAWN
        if prerequisite_disposition is None:
            return AssignmentState.BLOCKED
        if not evaluate_condition(
            condition,
            cast(JsonValue, prerequisite_value),
            answered=prerequisite_disposition == ResponseDisposition.ANSWERED,
        ):
            return AssignmentState.WITHDRAWN
    if own_disposition == ResponseDisposition.DELEGATED:
        return AssignmentState.DELEGATED
    if own_disposition is not None:
        return AssignmentState.RESPONDED
    return AssignmentState.PENDING
