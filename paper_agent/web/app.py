from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from paper_agent.config import Settings, load_settings
from paper_agent.web.api_models import ErrorBody, ErrorResponse
from paper_agent.web.artifacts import ArtifactReader
from paper_agent.web.demo import DEMO_ROOT, seed_bundled_demo
from paper_agent.web.errors import WebError
from paper_agent.web.execution import PipelineRunner, SingleRunExecutor
from paper_agent.web.registry import RunRegistry
from paper_agent.web.routes.runs import router
from paper_agent.web.service import RunService


def _error(code: str, message: str, details: dict[str, object] | None = None, status: int = 500) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or {}))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


def create_app(
    *,
    state_root: Path = Path("outputs/.web"),
    output_root: Path = Path("outputs"),
    demo_root: Path | None = DEMO_ROOT,
    web_dist: Path | None = None,
    allowed_origins: tuple[str, ...] = (),
    queue_capacity: int = 4,
    runner: PipelineRunner | None = None,
    settings_loader: Callable[[], Settings] = load_settings,
) -> FastAPI:
    if "*" in allowed_origins:
        raise ValueError("allowed_origins must contain exact origins, never '*'")
    allowed_origins = tuple(origin.rstrip("/") for origin in allowed_origins)
    state_root = state_root.resolve()
    output_root = output_root.resolve()
    registry = RunRegistry(state_root / "run-registry.sqlite3")
    artifacts = ArtifactReader(output_root, demo_root)
    seed_bundled_demo(registry, artifacts)
    executor = SingleRunExecutor(
        registry, artifacts, output_root,
        runner=runner or __import__("paper_agent.pipeline", fromlist=["run_pipeline"]).run_pipeline,
        settings_loader=settings_loader,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        executor.start()
        try:
            yield
        finally:
            executor.close()

    app = FastAPI(title="MOMO Scholar Web API", version="1.0.0", lifespan=lifespan)
    app.state.run_service = RunService(registry, artifacts, executor, queue_capacity)
    app.include_router(router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        origin = request.headers.get("origin")
        same_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin and origin.rstrip("/") not in {same_origin, *allowed_origins}:
            return _error(
                "origin_not_allowed", "The request origin is not allowed.", status=403,
            )
        if request.method == "POST" and request.url.path == "/api/v1/runs":
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json" or len(await request.body()) > 16 * 1024:
                return _error("validation_error", "The request did not satisfy the API contract.", status=422)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(WebError)
    async def web_error_handler(request: Request, error: WebError):
        return _error(error.code, error.message, error.details, error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError):
        details = {"fields": [".".join(str(part) for part in item["loc"][1:]) for item in error.errors()]}
        return _error("validation_error", "The request did not satisfy the API contract.", details, 422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, error: StarletteHTTPException):
        code = "artifact_not_found" if "/artifacts/" in request.url.path else "run_not_found"
        return _error(code, "The requested artifact was not found." if code == "artifact_not_found" else "The requested run was not found.", status=404)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, error: Exception):
        correlation_id = secrets.token_hex(8)
        logging.getLogger("paper_agent.web").error("unexpected API error", extra={"correlation_id": correlation_id})
        return _error("internal_error", "The request could not be completed.", {"correlation_id": correlation_id}, 500)

    resolved_web_dist = web_dist.resolve() if web_dist else Path(__file__).parents[2] / "web" / "dist"
    if resolved_web_dist.is_dir() and (resolved_web_dist / "index.html").is_file():
        assets = resolved_web_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="web-assets")

        @app.get("/", include_in_schema=False)
        @app.get("/{client_path:path}", include_in_schema=False)
        def serve_spa(client_path: str = "") -> FileResponse:
            if client_path.startswith("api/"):
                code = "artifact_not_found" if "/artifacts/" in client_path else "run_not_found"
                raise WebError(404, code)
            return FileResponse(resolved_web_dist / "index.html")

    return app
