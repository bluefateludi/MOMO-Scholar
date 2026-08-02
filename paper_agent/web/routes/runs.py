from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import UUID4

from paper_agent.web.api_models import (
    CreateRunRequest, ErrorResponse, EvidenceList, EvidenceView,
    PaperAnalysisResponse, PaperList, ReportResponse, RunDetail, RunList,
    RunSummary,
)
from paper_agent.web.service import RunService


router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
READ_ERRORS = {
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def _service(request: Request) -> RunService:
    return request.app.state.run_service


@router.post("", response_model=RunSummary, status_code=202, responses={403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
def create_run(body: CreateRunRequest, request: Request) -> JSONResponse:
    summary = _service(request).create(body)
    return JSONResponse(
        status_code=202,
        content=summary.model_dump(mode="json"),
        headers={"Location": f"/api/v1/runs/{summary.id}"},
    )


@router.get("", response_model=RunList, responses=READ_ERRORS)
def list_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> RunList:
    return _service(request).list(limit, cursor)


@router.get("/{run_id}", response_model=RunDetail, responses=READ_ERRORS)
def get_run(run_id: UUID4, request: Request) -> JSONResponse:
    detail = _service(request).detail(str(run_id))
    headers = {"Retry-After": "2"} if detail.status in {"queued", "running"} else {}
    return JSONResponse(content=detail.model_dump(mode="json"), headers=headers)


@router.get("/{run_id}/report", response_model=ReportResponse, responses=READ_ERRORS)
def get_report(run_id: UUID4, request: Request) -> ReportResponse:
    return _service(request).report(str(run_id))


@router.get("/{run_id}/papers", response_model=PaperList, responses=READ_ERRORS)
def get_papers(run_id: UUID4, request: Request) -> PaperList:
    return _service(request).papers(str(run_id))


@router.get(
    "/{run_id}/papers/{paper_id:path}/analysis",
    response_model=PaperAnalysisResponse,
    responses=READ_ERRORS,
)
def get_paper_analysis(
    run_id: UUID4, paper_id: str, request: Request,
) -> PaperAnalysisResponse:
    return _service(request).paper_analysis(str(run_id), paper_id)


@router.get("/{run_id}/evidence", response_model=EvidenceList, responses=READ_ERRORS)
def get_evidence(run_id: UUID4, request: Request, paper_id: str | None = Query(default=None)) -> EvidenceList:
    return _service(request).evidence(str(run_id), paper_id)


@router.get("/{run_id}/evidence/{evidence_id:path}", response_model=EvidenceView, responses=READ_ERRORS)
def get_evidence_item(run_id: UUID4, evidence_id: str, request: Request) -> EvidenceView:
    return _service(request).evidence_one(str(run_id), evidence_id)


@router.get("/{run_id}/artifacts/{name}", responses=READ_ERRORS)
def download_artifact(run_id: UUID4, name: str, request: Request) -> FileResponse:
    service = _service(request)
    path = service.artifact(str(run_id), name)
    return FileResponse(
        path,
        media_type=service.artifacts.content_type(name),
        filename=name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )
