from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def run_command[Result](
    session: Session,
    operation: Callable[[], Result],
    *,
    conflict_errors: tuple[type[Exception], ...],
    integrity_detail: str | None = None,
) -> Result:
    """Run and commit one HTTP command, translating expected conflicts."""
    try:
        result = operation()
        session.commit()
        return result
    except conflict_errors as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except IntegrityError as error:
        session.rollback()
        if integrity_detail is None:
            raise
        raise HTTPException(status_code=409, detail=integrity_detail) from error
