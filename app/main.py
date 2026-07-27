from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.asks import router as asks_router
from app.api.assistant import router as assistant_router
from app.api.auth import router as auth_router
from app.api.feed import router as feed_router
from app.api.health import router as health_router
from app.api.inbox import router as inbox_router
from app.api.projects import router as projects_router
from app.config import get_settings
from app.logging import configure_logging
from app.web.decisions import router as decisions_router
from app.web.respondents import router as respondent_router


def create_app(frontend_dir: Path | None = None) -> FastAPI:
    settings = get_settings()
    settings.validate_public_startup()
    configure_logging(settings.log_level)
    application = FastAPI(title="FAQ", version="0.1.0")
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(admin_router)
    application.include_router(projects_router)
    application.include_router(feed_router)
    application.include_router(inbox_router)
    application.include_router(asks_router)
    application.include_router(assistant_router)
    application.include_router(respondent_router)
    application.include_router(decisions_router)

    @application.api_route(
        "/admin/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def reject_operator_route(path: str) -> None:
        raise HTTPException(status_code=404, detail="Not Found")

    @application.api_route(
        "/admin",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def reject_operator_root() -> None:
        raise HTTPException(status_code=404, detail="Not Found")

    @application.api_route(
        "/jobs/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def reject_jobs_route(path: str) -> None:
        raise HTTPException(status_code=404, detail="Not Found")

    @application.api_route(
        "/jobs",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def reject_jobs_root() -> None:
        raise HTTPException(status_code=404, detail="Not Found")

    static = Path(__file__).parent.parent / "static"
    application.mount("/static", StaticFiles(directory=static), name="static")
    frontend = frontend_dir or Path(__file__).parent.parent / "frontend" / "dist"
    if frontend.is_dir():
        assets = frontend / "assets"
        if assets.is_dir():
            application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")
        index = frontend / "index.html"

        @application.get("/", include_in_schema=False)
        @application.get("/login", include_in_schema=False)
        @application.get("/inbox", include_in_schema=False)
        @application.get("/organization", include_in_schema=False)
        @application.get("/p/{path:path}", include_in_schema=False)
        @application.get("/a/{path:path}", include_in_schema=False)
        def serve_spa(path: str = "") -> FileResponse:
            return FileResponse(index)
    return application


app = create_app()
