from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.models.session import get_engine


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, include_in_schema=False)
def health() -> HealthResponse:
    return HealthResponse()


@router.get("/readyz", response_model=HealthResponse, include_in_schema=False)
def readiness() -> HealthResponse:
    try:
        expected_head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        with get_engine().connect() as connection:
            current_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        if expected_head is None or current_head != expected_head:
            raise RuntimeError("database schema is not current")
    except Exception as error:
        raise HTTPException(status_code=503, detail="service not ready") from error
    return HealthResponse()
