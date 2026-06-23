"""Evidence ingestion and transcript upload endpoints."""

from __future__ import annotations

import base64
from datetime import datetime

from fastapi import APIRouter, File, Form, Request, UploadFile

try:
    from api.dependencies import get_evidence_ingestion_service
    from models.intelligence_models import (
        EvidenceIngestionRequest,
        EvidenceIngestionResponse,
        EvidenceSyncRequest,
        EvidenceSyncResponse,
        TranscriptIngestRequest,
        TranscriptIngestResponse,
    )
except ImportError:  # pragma: no cover
    from ..dependencies import get_evidence_ingestion_service
    from ...models.intelligence_models import (
        EvidenceIngestionRequest,
        EvidenceIngestionResponse,
        EvidenceSyncRequest,
        EvidenceSyncResponse,
        TranscriptIngestRequest,
        TranscriptIngestResponse,
    )


router = APIRouter(tags=["evidence-ingestion"])


@router.post("/v1/engine/evidence/ingest", response_model=EvidenceIngestionResponse)
def ingest_evidence(payload: EvidenceIngestionRequest, request: Request) -> EvidenceIngestionResponse:
    return get_evidence_ingestion_service(request.app).ingest_documents(payload.documents, persist=payload.persist)


@router.post("/v1/engine/evidence/sync", response_model=EvidenceSyncResponse)
def sync_evidence(payload: EvidenceSyncRequest, request: Request) -> EvidenceSyncResponse:
    return get_evidence_ingestion_service(request.app).sync_ticker(payload)


@router.post("/v1/engine/transcripts/ingest", response_model=TranscriptIngestResponse)
def ingest_transcript(payload: TranscriptIngestRequest, request: Request) -> TranscriptIngestResponse:
    return get_evidence_ingestion_service(request.app).ingest_transcript(payload)


@router.post("/v1/engine/transcripts/upload", response_model=TranscriptIngestResponse)
async def upload_transcript(
    request: Request,
    file: UploadFile = File(...),
    ticker: str = Form(...),
    title: str = Form("Earnings call transcript"),
    published_at: str | None = Form(None),
    source_url: str | None = Form(None),
) -> TranscriptIngestResponse:
    raw = await file.read()
    parsed_date = datetime.fromisoformat(published_at) if published_at else None
    payload = TranscriptIngestRequest(
        ticker=ticker,
        title=title or file.filename or "Earnings call transcript",
        pdf_base64=base64.b64encode(raw).decode("ascii"),
        published_at=parsed_date,
        source_url=source_url,
        metadata={"filename": file.filename, "content_type": file.content_type},
    )
    return get_evidence_ingestion_service(request.app).ingest_transcript(payload)


@router.get("/v1/engine/evidence/ingestion/status")
def ingestion_status(request: Request) -> dict:
    return get_evidence_ingestion_service(request.app).status()


@router.post("/v1/engine/evidence/bootstrap-schema")
def bootstrap_evidence_schema(request: Request) -> dict:
    evidence_applied = request.app.state.evidence_repository.bootstrap_schema()
    request.app.state.company_intelligence_repository.bootstrap_schema()
    return {"status": "ok", "evidence_schema_applied": evidence_applied}


__all__ = ["router"]
