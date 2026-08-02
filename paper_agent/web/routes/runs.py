from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from paper_agent.web.api_models import (
    CreateRunRequest, ErrorResponse, EvidenceList, EvidenceView, ReportResponse,
    RunDetail, RunSummary,
)
from paper_agent.web.service import RunService


router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def _service(request: Request) -> RunService:
    return request.app.state.run_service


@router.post("", response_model=RunSummary, status_code=202, responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
def create_run(body: CreateRunRequest, request: Request) -> JSONResponse:
    summary = _service(request).create(body)
    return JSONResponse(
        status_code=202,
        content=summary.model_dump(mode="json"),
        headers={"Location": f"/api/v1/runs/{summary.id}"},
    )


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str, request: Request) -> JSONResponse:
    detail = _service(request).detail(run_id)
    headers = {"Retry-After": "2"} if detail.status in {"queued", "running"} else {}
    return JSONResponse(content=detail.model_dump(mode="json"), headers=headers)


@router.get("/{run_id}/report", response_model=ReportResponse)
def get_report(run_id: str, request: Request) -> ReportResponse:
    return _service(request).report(run_id)


@router.get("/{run_id}/evidence", response_model=EvidenceList)
def get_evidence(run_id: str, request: Request, paper_id: str | None = Query(default=None)) -> EvidenceList:
    return _service(request).evidence(run_id, paper_id)


@router.get("/{run_id}/evidence/{evidence_id}", response_model=EvidenceView)
def get_evidence_item(run_id: str, evidence_id: str, request: Request) -> EvidenceView:
    return _service(request).evidence_one(run_id, evidence_id)


@router.get("/{run_id}/artifacts/{name}")
def download_artifact(run_id: str, name: str, request: Request) -> FileResponse:
    service = _service(request)
    path = service.artifact(run_id, name)
    return FileResponse(
        path,
        media_type=service.artifacts.content_type(name),
        filename=name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )
