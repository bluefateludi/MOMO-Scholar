from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from paper_agent.config import Settings, load_settings
from paper_agent.web.api_models import ErrorBody, ErrorResponse
from paper_agent.web.artifacts import ArtifactReader
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
    demo_root: Path | None = None,
    queue_capacity: int = 4,
    runner: PipelineRunner | None = None,
    settings_loader: Callable[[], Settings] = load_settings,
) -> FastAPI:
    state_root = state_root.resolve()
    output_root = output_root.resolve()
    registry = RunRegistry(state_root / "run-registry.sqlite3")
    artifacts = ArtifactReader(output_root, demo_root)
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
        if request.method == "POST" and request.url.path == "/api/v1/runs":
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json" or len(await request.body()) > 16 * 1024:
                return _error("validation_error", "The request did not satisfy the API contract.", status=422)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
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

    return app
