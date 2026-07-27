from fastapi import APIRouter, Depends, FastAPI, HTTPException

from app.api.health import router as health_router
from app.api.operator_inspection import router as operator_inspection_router
from app.api.operator_recipients import router as operator_recipients_router
from app.config import get_settings
from app.logging import configure_logging
from app.operator_identity import require_operator_identity

operator_router = APIRouter(prefix="/admin")


@operator_router.get("/health", include_in_schema=False)
def operator_health() -> dict[str, str]:
    return {"status": "ok"}


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_operator_startup()
    configure_logging(settings.log_level)
    application = FastAPI(title="FAQ Operator", version="0.1.0", docs_url=None, redoc_url=None)
    application.include_router(health_router)
    application.include_router(operator_router)
    identity_required = [Depends(require_operator_identity)]
    application.include_router(operator_recipients_router, dependencies=identity_required)
    application.include_router(operator_inspection_router, dependencies=identity_required)

    @application.api_route(
        "/jobs/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def reject_jobs_route(path: str) -> None:
        raise HTTPException(status_code=404, detail="Not Found")
    return application


app = create_app()
