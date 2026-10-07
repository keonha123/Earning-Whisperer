"""Evidence ingestion for filings, news, IR pages, and transcript PDFs."""

from __future__ import annotations

import asyncio
import base64
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import hashlib
import json
import logging
import re
import time
from typing import Any, Iterable

try:
    from config import Settings
    from core.external_retriever import ExternalDocument, ExternalRetrieverFacade
    from models.evidence_models import EvidenceDocument, EvidenceSourceType
    from models.intelligence_models import (
        EvidenceIngestionResponse,
        EvidenceSyncRequest,
        EvidenceSyncResponse,
        TranscriptIngestRequest,
        TranscriptIngestResponse,
    )
    from services.company_intelligence_service import CompanyIntelligenceService
    from services.evidence_retrieval_service import EvidenceRetrievalService
except ImportError:  # pragma: no cover
    from ..config import Settings
    from ..core.external_retriever import ExternalDocument, ExternalRetrieverFacade
    from ..models.evidence_models import EvidenceDocument, EvidenceSourceType
    from ..models.intelligence_models import (
        EvidenceIngestionResponse,
        EvidenceSyncRequest,
        EvidenceSyncResponse,
        TranscriptIngestRequest,
        TranscriptIngestResponse,
    )
    from .company_intelligence_service import CompanyIntelligenceService
    from .evidence_retrieval_service import EvidenceRetrievalService


logger = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._parts)).strip()


class EvidenceIngestionService:
    def __init__(
        self,
        *,
        settings: Settings,
        evidence_service: EvidenceRetrievalService,
        external_retriever: ExternalRetrieverFacade,
        company_service: CompanyIntelligenceService,
    ) -> None:
        self.settings = settings
        self.evidence_service = evidence_service
        self.external_retriever = external_retriever
        self.company_service = company_service
        self._sec_ticker_map: dict[str, str] | None = None
        self._last_sync: dict[str, Any] = {}

    def ingest_documents(self, documents: Iterable[EvidenceDocument], *, persist: bool = True) -> EvidenceIngestionResponse:
        normalized = [self._normalize_document(item) for item in documents if item.content.strip()]
        if not normalized:
            return EvidenceIngestionResponse(warnings=["no_nonempty_documents"])
        warnings: list[str] = []
        persisted = self.evidence_service.repository.add_documents(normalized) if persist else 0
        external = [self._to_external_document(item) for item in normalized]
        vector_upserted = 0
        try:
            self.external_retriever.upsert_documents(external)
            vector_upserted = len(external)
        except Exception as exc:
            warnings.append(f"vector_upsert_failed:{type(exc).__name__}")
        return EvidenceIngestionResponse(
            accepted=len(normalized),
            persisted=persisted,
            vector_upserted=vector_upserted,
            document_ids=[item.document_id for item in normalized],
            warnings=warnings,
        )

    def sync_ticker(self, payload: EvidenceSyncRequest) -> EvidenceSyncResponse:
        ticker = payload.ticker.upper().strip()
        documents: list[EvidenceDocument] = []
        attempted: list[str] = []
        errors: dict[str, str] = {}
        if payload.include_sec_filings:
            attempted.append("sec_filings")
            try:
                documents.extend(self._load_sec_filings(ticker, payload.filing_forms, payload.max_filings))
            except Exception as exc:
                errors["sec_filings"] = str(exc)[:300]
        if payload.include_news:
            attempted.append("news")
            try:
                documents.extend(self._load_yfinance_news(ticker, payload.max_news))
            except Exception as exc:
                errors["news"] = str(exc)[:300]
        if payload.ir_urls:
            attempted.append("ir_urls")
            for url in payload.ir_urls:
                try:
                    documents.append(self._load_url_document(ticker=ticker, url=url, source_type=EvidenceSourceType.PRESENTATION))
                except Exception as exc:
                    errors[f"ir:{url}"] = str(exc)[:300]
        result = self.ingest_documents(documents)
        response = EvidenceSyncResponse(
            ticker=ticker,
            **result.model_dump(),
            sources_attempted=attempted,
            source_errors=errors,
        )
        self._last_sync[ticker] = response.model_dump(mode="json")
        return response

    def ingest_transcript(self, payload: TranscriptIngestRequest) -> TranscriptIngestResponse:
        text = payload.text or ""
        page_count = 0
        if payload.pdf_base64:
            pdf_bytes = base64.b64decode(payload.pdf_base64, validate=True)
            text, page_count = self.extract_pdf_text(pdf_bytes)
        if not text.strip():
            raise ValueError("Transcript text or pdf_base64 is required")
        ticker = payload.ticker.upper()
        chunks = self._chunk_text(text)
        root_id = hashlib.sha1(f"{ticker}|{payload.title}|{payload.published_at}|{text[:500]}".encode("utf-8")).hexdigest()[:20]
        documents = [
            EvidenceDocument(
                document_id=f"{root_id}#chunk-{index}",
                ticker=ticker,
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source=payload.title,
                title=payload.title,
                published_at=payload.published_at,
                source_url=payload.source_url,
                content=chunk,
                reliability_score=payload.reliability_score,
                metadata={
                    **payload.metadata,
                    "root_document_id": root_id,
                    "chunk_index": index,
                    "page_count": page_count,
                    "ingestion_type": "transcript",
                },
            )
            for index, chunk in enumerate(chunks)
        ]
        result = self.ingest_documents(documents)
        speakers = self.company_service.register_transcript_speakers(
            ticker=ticker,
            text=text,
            document_ids=result.document_ids,
            observed_at=payload.published_at,
        )
        return TranscriptIngestResponse(
            ticker=ticker,
            title=payload.title,
            page_count=page_count,
            character_count=len(text),
            chunk_count=len(documents),
            speakers=speakers,
            **result.model_dump(),
        )

    @staticmethod
    def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pypdf is required for transcript PDF ingestion") from exc
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join(item for item in pages if item), len(reader.pages)

    def status(self) -> dict[str, Any]:
        return {
            "last_sync": dict(self._last_sync),
            "vector_store": self.external_retriever.get_stats(),
            "persistence_backend": self.company_service.repository.backend_name,
        }

    def _load_sec_filings(self, ticker: str, forms: list[str], limit: int) -> list[EvidenceDocument]:
        if limit <= 0:
            return []
        user_agent = self.settings.evidence_sec_user_agent.strip()
        if not user_agent:
            raise RuntimeError("EVIDENCE_SEC_USER_AGENT must identify an application and contact email")
        headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Host": "www.sec.gov"}
        company_headers = dict(headers)
        company_headers["Host"] = "data.sec.gov"
        httpx = self._httpx()
        if self._sec_ticker_map is None:
            response = httpx.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=self.settings.evidence_http_timeout_seconds)
            response.raise_for_status()
            raw = response.json()
            self._sec_ticker_map = {
                str(item.get("ticker", "")).upper(): str(item.get("cik_str", "")).zfill(10)
                for item in raw.values()
            }
        cik = self._sec_ticker_map.get(ticker)
        if not cik:
            raise RuntimeError(f"SEC CIK not found for {ticker}")
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        submissions = httpx.get(submissions_url, headers=company_headers, timeout=self.settings.evidence_http_timeout_seconds)
        submissions.raise_for_status()
        recent = submissions.json().get("filings", {}).get("recent", {})
        allowed = {item.upper() for item in forms}
        documents: list[EvidenceDocument] = []
        for form, accession, primary, filing_date in zip(
            recent.get("form", []),
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
            recent.get("filingDate", []),
        ):
            if str(form).upper() not in allowed:
                continue
            accession_compact = str(accession).replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_compact}/{primary}"
            filing = httpx.get(filing_url, headers=headers, timeout=self.settings.evidence_http_timeout_seconds)
            filing.raise_for_status()
            content = self._html_to_text(filing.text)
            documents.append(
                EvidenceDocument(
                    ticker=ticker,
                    source_type=EvidenceSourceType.FILING,
                    source=f"SEC {form}",
                    title=f"{ticker} {form} filed {filing_date}",
                    published_at=filing_date,
                    source_url=filing_url,
                    content=content,
                    reliability_score=0.96,
                    metadata={"form_type": form, "accession_number": accession},
                )
            )
            if len(documents) >= limit:
                break
        return documents

    def _load_yfinance_news(self, ticker: str, limit: int) -> list[EvidenceDocument]:
        if limit <= 0:
            return []
        import yfinance as yf
        items = list(yf.Ticker(ticker).news or [])[:limit]
        documents: list[EvidenceDocument] = []
        for item in items:
            content = item.get("content") if isinstance(item.get("content"), dict) else item
            title = str(content.get("title") or item.get("title") or "").strip()
            summary = str(content.get("summary") or content.get("description") or item.get("summary") or "").strip()
            canonical = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else {}
            url = str(canonical.get("url") or content.get("link") or item.get("link") or "")
            provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
            source = str(provider.get("displayName") or item.get("publisher") or "yfinance news")
            published = content.get("pubDate") or item.get("providerPublishTime")
            published_at: datetime | str | None = None
            if isinstance(published, (int, float)):
                published_at = datetime.fromtimestamp(published, tz=timezone.utc)
            elif isinstance(published, str):
                published_at = published
            text = "\n".join(part for part in [title, summary] if part)
            if not text:
                continue
            documents.append(
                EvidenceDocument(
                    ticker=ticker,
                    source_type=EvidenceSourceType.NEWS,
                    source=source,
                    title=title or None,
                    published_at=published_at,
                    source_url=url or None,
                    content=text,
                    reliability_score=0.68,
                    metadata={"provider": "yfinance"},
                )
            )
        return documents

    def _load_url_document(self, *, ticker: str, url: str, source_type: EvidenceSourceType) -> EvidenceDocument:
        response = self._httpx().get(
            url,
            headers={"User-Agent": self.settings.evidence_http_user_agent},
            timeout=self.settings.evidence_http_timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        page_count = 0
        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            text, page_count = self.extract_pdf_text(response.content)
        else:
            text = self._html_to_text(response.text)
        return EvidenceDocument(
            ticker=ticker,
            source_type=source_type,
            source="company IR",
            title=url.rsplit("/", 1)[-1] or f"{ticker} IR document",
            source_url=url,
            content=text,
            reliability_score=0.86,
            metadata={"page_count": page_count, "ingested_from_url": True},
        )

    def _normalize_document(self, document: EvidenceDocument) -> EvidenceDocument:
        if document.document_id:
            return document
        seed = "|".join([
            str(document.ticker or ""), document.source_type.value, document.source,
            str(document.title or ""), str(document.published_at or ""), document.content[:500],
        ])
        return document.model_copy(update={"document_id": hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]})

    @staticmethod
    def _to_external_document(document: EvidenceDocument) -> ExternalDocument:
        published_at = document.published_at
        if isinstance(published_at, datetime):
            timestamp = int(published_at.timestamp())
        elif isinstance(published_at, date):
            timestamp = int(datetime(published_at.year, published_at.month, published_at.day, tzinfo=timezone.utc).timestamp())
        else:
            timestamp = 0
        return ExternalDocument(
            doc_id=document.document_id,
            ticker=(document.ticker or "UNKNOWN").upper(),
            text=document.content,
            title=document.title or "",
            published_at=timestamp,
            source_type=document.source_type.value.lower(),
            url=document.source_url or "",
            form_type=str(document.metadata.get("form_type") or ""),
            importance=document.reliability_score,
            metadata={**document.metadata, "source": document.source},
        )

    def _chunk_text(self, text: str) -> list[str]:
        max_chars = max(600, self.settings.external_chunk_size_chars)
        overlap = max(0, min(self.settings.external_chunk_overlap_chars, max_chars - 1))
        normalized = re.sub(r"[ \t]+", " ", text).strip()
        if len(normalized) <= max_chars:
            return [normalized]
        chunks: list[str] = []
        start = 0
        step = max(1, max_chars - overlap)
        while start < len(normalized):
            end = min(len(normalized), start + max_chars)
            if end < len(normalized):
                boundary = normalized.rfind("\n", start + max_chars // 2, end)
                if boundary > start:
                    end = boundary
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(start + 1, end - overlap)
        return chunks

    @staticmethod
    def _html_to_text(html: str) -> str:
        parser = _HTMLTextExtractor()
        parser.feed(html)
        return parser.text()

    @staticmethod
    def _httpx():
        import httpx
        return httpx


class EvidenceIngestionScheduler:
    def __init__(self, *, service: EvidenceIngestionService, settings: Settings) -> None:
        self.service = service
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not self.settings.evidence_sync_enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="evidence-ingestion-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self) -> list[EvidenceSyncResponse]:
        responses = []
        for ticker in self.settings.evidence_sync_tickers_list:
            response = await asyncio.to_thread(self.service.sync_ticker, EvidenceSyncRequest(ticker=ticker))
            responses.append(response)
        return responses

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception as exc:  # pragma: no cover
                logger.warning("Scheduled evidence sync failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(300, self.settings.evidence_sync_interval_seconds))
            except asyncio.TimeoutError:
                continue


__all__ = ["EvidenceIngestionScheduler", "EvidenceIngestionService"]
