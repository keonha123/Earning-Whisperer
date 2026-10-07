"""Company relationship, executive, and transcript speaker intelligence service."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Iterable

try:
    from models.intelligence_models import CompanyIntelligenceResponse, CompanyIntelligenceUpsertRequest, ExecutiveProfile, SpeakerMetadata
    from repositories.company_intelligence_repository import CompanyIntelligenceRepository
except ImportError:  # pragma: no cover
    from ..models.intelligence_models import CompanyIntelligenceResponse, CompanyIntelligenceUpsertRequest, ExecutiveProfile, SpeakerMetadata
    from ..repositories.company_intelligence_repository import CompanyIntelligenceRepository


_SPEAKER_ROLE_RE = re.compile(
    r"^(?P<name>[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,4})\s*(?:--|—|-|:)\s*(?P<role>[^\n]{2,100})$",
    re.MULTILINE,
)
_EXECUTIVE_TERMS = {
    "chief executive officer", "chief financial officer", "chief operating officer",
    "president", "ceo", "cfo", "coo", "chairman", "vice president",
}


class CompanyIntelligenceService:
    def __init__(self, repository: CompanyIntelligenceRepository) -> None:
        self.repository = repository

    def get(self, ticker: str) -> CompanyIntelligenceResponse:
        normalized = ticker.upper()
        return CompanyIntelligenceResponse(
            ticker=normalized,
            relationships=self.repository.get_relationships(normalized),
            executives=self.repository.get_executives(normalized),
            speakers=self.repository.get_speakers(normalized),
            persistence_backend=self.repository.backend_name,
        )

    def upsert(self, payload: CompanyIntelligenceUpsertRequest) -> CompanyIntelligenceResponse:
        ticker = payload.ticker.upper()
        relationships = [item.model_copy(update={"source_ticker": ticker}) for item in payload.relationships]
        executives = [item.model_copy(update={"ticker": ticker}) for item in payload.executives]
        speakers = [item.model_copy(update={"ticker": ticker}) for item in payload.speakers]
        self.repository.upsert_relationships(relationships)
        self.repository.upsert_executives(executives)
        self.repository.upsert_speakers(speakers)
        return self.get(ticker)

    def register_transcript_speakers(
        self,
        *,
        ticker: str,
        text: str,
        document_ids: Iterable[str],
        observed_at: datetime | date | None = None,
    ) -> list[SpeakerMetadata]:
        normalized = ticker.upper()
        document_ids_list = list(dict.fromkeys(str(item) for item in document_ids if item))
        speakers: list[SpeakerMetadata] = []
        for match in _SPEAKER_ROLE_RE.finditer(text or ""):
            name = " ".join(match.group("name").split())
            role = " ".join(match.group("role").split()).strip(" .")
            role_lower = role.lower()
            speaker_id = hashlib.sha1(f"{normalized}|{name.lower()}".encode("utf-8")).hexdigest()[:20]
            speakers.append(
                SpeakerMetadata(
                    speaker_id=speaker_id,
                    ticker=normalized,
                    name=name,
                    role=role,
                    is_executive=any(term in role_lower for term in _EXECUTIVE_TERMS),
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                    source_document_ids=document_ids_list,
                )
            )
        result = list({item.speaker_id: item for item in speakers}.values())
        self.repository.upsert_speakers(result)
        self._promote_executives(result)
        return result

    def _promote_executives(self, speakers: list[SpeakerMetadata]) -> None:
        profiles: list[ExecutiveProfile] = []
        for speaker in speakers:
            if not speaker.is_executive:
                continue
            role_lower = speaker.role.lower()
            profiles.append(
                ExecutiveProfile(
                    executive_id=speaker.speaker_id,
                    ticker=speaker.ticker,
                    name=speaker.name,
                    current_role=speaker.role,
                    is_ceo="chief executive officer" in role_lower or re.search(r"\bceo\b", role_lower) is not None,
                    source_document_ids=speaker.source_document_ids,
                    confidence=0.72,
                    metadata={"derived_from": "transcript_speaker_header"},
                )
            )
        self.repository.upsert_executives(profiles)


__all__ = ["CompanyIntelligenceService"]
