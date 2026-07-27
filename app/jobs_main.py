from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException

from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.domain.ports import SystemClock
from app.google_identity import (
    GoogleIdentityError,
    GoogleIdentityVerifier,
    get_google_identity_verifier,
)
from app.jobs.metrics import MetricsSink, get_metrics_sink
from app.jobs.scheduler import TickSummary, run_tick
from app.logging import configure_logging
from app.models.session import get_session_factory


def require_job_identity(
    settings: Annotated[Settings, Depends(get_settings)],
    verifier: Annotated[GoogleIdentityVerifier, Depends(get_google_identity_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if (
        settings.jobs_audience is None
        or settings.jobs_caller_email is None
        or authorization is None
        or not authorization.startswith("Bearer ")
    ):
        raise HTTPException(status_code=401, detail="valid job identity required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="valid job identity required")
    try:
        principal = verifier.verify(token, settings.jobs_audience)
        if principal.email != settings.jobs_caller_email:
            raise GoogleIdentityError("unexpected job caller")
    except GoogleIdentityError as error:
        raise HTTPException(status_code=401, detail="valid job identity required") from error


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_jobs_startup()
    configure_logging(settings.log_level)
    application = FastAPI(
        title="FAQ Jobs",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    application.include_router(health_router)

    @application.post("/jobs/tick", dependencies=[Depends(require_job_identity)])
    def tick(metrics: Annotated[MetricsSink, Depends(get_metrics_sink)]) -> TickSummary:
        return run_tick(
            get_session_factory(),
            SystemClock(),
            metrics,
            run_id=uuid4(),
            batch_size=settings.jobs_batch_size,
            max_batches=settings.jobs_max_batches,
        )

    return application


app = create_app()
