"""Grounded QA and legacy glossary; translation has its own authoritative router."""
from fastapi import APIRouter, Request

try:
    from models.transcript_assistant_models import (
        GlossaryResponse, TranscriptAskRequest, TranscriptAskResponse,
    )
    from services.transcript_assistant_service import TranscriptAssistantService
    from services.transcript_glossary import get_glossary
except ImportError:  # pragma: no cover
    from ...models.transcript_assistant_models import (
        GlossaryResponse, TranscriptAskRequest, TranscriptAskResponse,
    )
    from ...services.transcript_assistant_service import TranscriptAssistantService
    from ...services.transcript_glossary import get_glossary


router = APIRouter(tags=["transcript-assistant"])


def _service(request: Request) -> TranscriptAssistantService:
    injected = getattr(request.app.state, "transcript_assistant_service", None)
    return injected if injected is not None else TranscriptAssistantService(
        request.app.state.settings, getattr(request.app.state, "evidence_service", None),
        getattr(request.app.state, "transcript_repository", None),
    )


@router.get("/v1/engine/glossary", response_model=GlossaryResponse)
@router.get("/v1/engine/transcript/glossary", response_model=GlossaryResponse, include_in_schema=False)
async def glossary():
    return get_glossary()


@router.post("/v1/engine/transcript/ask", response_model=TranscriptAskResponse)
async def ask(payload: TranscriptAskRequest, request: Request):
    return await _service(request).ask(payload)
