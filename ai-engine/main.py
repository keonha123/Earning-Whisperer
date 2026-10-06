from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from api.routers import ALL_ROUTERS
    from config import Settings, get_settings
    from core.analysis_service import AnalysisService, run_analysis
    from core.external_retriever import ExternalRetrieverFacade, QdrantExternalRetriever
    from db.postgres_executor import PsycopgExecutor
    from models.evidence_models import EvidenceBackend
    from models.request_models import AnalyzeRequest
    from models.storage_models import PersistEnvelopeResponse
    from repositories.company_intelligence_repository import CompanyIntelligenceRepository
    from repositories.event_store_repository import EventStoreRepository
    from repositories.evidence_store_repository import EvidenceStoreRepository
    from repositories.live_session_repository import LiveSessionRepository
    from repositories.qdrant_evidence_repository import QdrantEvidenceRepository
    from services import CalibrationService, CompanyIntelligenceService, ControlPlaneService, EarningsIntelligenceService, EquityResearchReportService, EvidenceIngestionScheduler, EvidenceIngestionService, EvidenceRetrievalService, LiveEarningsSessionService, RegressionService, LiveNewsFactCheckService, NewsIngestionService, TranscriptDiffService, TranscriptIngestionService
    from services.redis_signal_publisher import RedisSignalPublisher
    from services.runtime_dispatch_service import dispatch_analysis
    from services.transcript_translation_service import TranscriptTranslationService
    from repositories.transcript_statement_repository import InMemoryTranscriptStatementRepository, QdrantTranscriptStatementRepository
    from services.transcript_statement_extraction_service import TranscriptStatementExtractionService
    from services.transcript_statement_service import TranscriptStatementService
except ImportError:  # pragma: no cover
    from .api.routers import ALL_ROUTERS
    from .config import Settings, get_settings
    from .core.analysis_service import AnalysisService, run_analysis
    from .core.external_retriever import ExternalRetrieverFacade, QdrantExternalRetriever
    from .db.postgres_executor import PsycopgExecutor
    from .models.evidence_models import EvidenceBackend
    from .models.request_models import AnalyzeRequest
    from .models.storage_models import PersistEnvelopeResponse
    from .repositories.company_intelligence_repository import CompanyIntelligenceRepository
    from .repositories.event_store_repository import EventStoreRepository
    from .repositories.evidence_store_repository import EvidenceStoreRepository
    from .repositories.live_session_repository import LiveSessionRepository
    from .repositories.qdrant_evidence_repository import QdrantEvidenceRepository
    from .services import CalibrationService, CompanyIntelligenceService, ControlPlaneService, EarningsIntelligenceService, EquityResearchReportService, EvidenceIngestionScheduler, EvidenceIngestionService, EvidenceRetrievalService, LiveEarningsSessionService, RegressionService, LiveNewsFactCheckService, NewsIngestionService, TranscriptDiffService, TranscriptIngestionService
    from .services.redis_signal_publisher import RedisSignalPublisher
    from .services.runtime_dispatch_service import dispatch_analysis
    from .services.transcript_translation_service import TranscriptTranslationService
    from .repositories.transcript_statement_repository import InMemoryTranscriptStatementRepository, QdrantTranscriptStatementRepository
    from .services.transcript_statement_extraction_service import TranscriptStatementExtractionService
    from .services.transcript_statement_service import TranscriptStatementService


class HealthResponse(BaseModel):
    status: str
    models: dict[str, str]


def risk_score_from_sentiment(sentiment_score: float) -> float:
    return min(1.0, abs(sentiment_score) * 1.5)


async def _dispatch_analysis(
    payload: AnalyzeRequest,
    settings: Settings,
    fastapi_app: FastAPI | None = None,
) -> dict[str, Any]:
    current_app = fastapi_app if fastapi_app is not None else globals().get("app")
    analysis_runner = run_analysis
    if current_app is not None:
        analysis_service = getattr(current_app.state, "analysis_service", None)
        if analysis_service is not None and hasattr(analysis_service, "analyze"):
            analysis_runner = analysis_service.analyze
    return await dispatch_analysis(
        payload=payload,
        settings=settings,
        analysis_runner=analysis_runner,
        control_service=_get_control_service(current_app),
    )


def _schema_path_from_settings(settings: Settings) -> Path:
    configured = Path(settings.db_schema_path)
    if configured.is_absolute():
        return configured
    return Path(__file__).resolve().parent / configured


def _build_repository(settings: Settings) -> EventStoreRepository:
    executor = PsycopgExecutor(
        dsn=settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
        failure_cooldown_seconds=settings.database_failure_cooldown_seconds,
    )
    return EventStoreRepository(executor=executor, schema_path=_schema_path_from_settings(settings))


def _resolve_ai_engine_path(configured: str) -> Path:
    path = Path(configured)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def _build_company_repository(settings: Settings, executor) -> CompanyIntelligenceRepository:
    return CompanyIntelligenceRepository(
        store_path=_resolve_ai_engine_path(settings.company_intelligence_store_path),
        executor=executor,
        schema_path=_resolve_ai_engine_path(settings.evidence_schema_path),
        seed_path=Path(__file__).resolve().parent / "data" / "company_intelligence_seed.json",
    )


def _build_evidence_repository(settings: Settings, event_repository: EventStoreRepository):
    if str(settings.vector_store_backend).lower().strip() == "qdrant":
        return QdrantEvidenceRepository.from_settings(
            settings=settings,
            store_name="external",
            embedding_scope="external",
        )
    return EvidenceStoreRepository()


def _build_transcript_repository(settings: Settings, *, client: Any | None = None):
    if str(settings.vector_store_backend).lower().strip() == "qdrant":
        return QdrantEvidenceRepository.from_settings(
            settings=settings,
            collection_name=settings.qdrant_transcript_collection_name,
            store_name="transcript",
            embedding_scope="transcript",
            client=client,
        )
    return EvidenceStoreRepository()


def _build_transcript_statement_repository(transcript_repository):
    if isinstance(transcript_repository, QdrantEvidenceRepository):
        return QdrantTranscriptStatementRepository.sharing(transcript_repository)
    return InMemoryTranscriptStatementRepository()


def _get_control_service(fastapi_app: FastAPI | None) -> ControlPlaneService | None:
    if fastapi_app is None or not hasattr(fastapi_app.state, "event_store_repository"):
        return None
    return ControlPlaneService(fastapi_app.state.event_store_repository)


def _get_calibration_service(fastapi_app: FastAPI) -> CalibrationService:
    return CalibrationService(fastapi_app.state.event_store_repository)


def _get_regression_service(fastapi_app: FastAPI) -> RegressionService:
    return RegressionService(fastapi_app.state.event_store_repository)


def _persist_or_raise(repository: EventStoreRepository, envelope: dict[str, Any]) -> PersistEnvelopeResponse:
    try:
        result = repository.save_event_envelope(envelope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        raise HTTPException(status_code=500, detail=f"Failed to persist engine envelope: {exc}") from exc
    return PersistEnvelopeResponse(
        status="ok",
        persisted=result.persisted,
        event_id=result.event_id,
        run_id=result.run_id,
        row_counts=result.row_counts,
    )


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            if settings.phase1_warmup_on_startup:
                await asyncio.to_thread(app.state.analysis_service.phase1_scorer.warmup)
            await app.state.evidence_ingestion_scheduler.start()
            yield
        finally:
            await app.state.evidence_ingestion_scheduler.stop()
            client = getattr(app.state.evidence_repository, "client", None)
            if client is not None:
                client.close()

    app = FastAPI(title="EarningWhisperer AI Engine", version=settings.app_version, lifespan=lifespan)

    app.config = {
        "GEMINI_FAST_MODEL": settings.gemini_primary_model,
        "GEMINI_PRO_MODEL": settings.gemini_review_model,
        "GEMINI_PRIMARY_MODEL": settings.gemini_primary_model,
        "GEMINI_REVIEW_MODEL": settings.gemini_review_model,
        "ENABLE_REVIEW_PASS": settings.enable_review_pass,
    }

    app.state.settings = settings
    app.state.event_store_repository = _build_repository(settings)
    app.state.evidence_repository = _build_evidence_repository(settings, app.state.event_store_repository)
    shared_client = getattr(app.state.evidence_repository, "client", None)
    app.state.transcript_repository = _build_transcript_repository(settings, client=shared_client)
    persistence_executor = None
    if settings.evidence_postgres_enabled:
        persistence_executor = PsycopgExecutor(
            dsn=settings.database_url,
            connect_timeout_seconds=settings.database_connect_timeout_seconds,
            failure_cooldown_seconds=settings.database_failure_cooldown_seconds,
        )
    if isinstance(app.state.evidence_repository, EvidenceStoreRepository):
        app.state.evidence_repository.executor = persistence_executor
        app.state.evidence_repository.schema_path = _resolve_ai_engine_path(settings.evidence_schema_path)
    app.state.company_intelligence_repository = _build_company_repository(settings, persistence_executor)
    app.state.evidence_service = EvidenceRetrievalService(
        repository=app.state.evidence_repository,
        company_repository=app.state.company_intelligence_repository,
    )
    app.state.transcript_translation_service = TranscriptTranslationService(
        settings=settings, timeout_seconds=settings.transcript_translation_timeout_seconds,
    )
    app.state.transcript_statement_service = TranscriptStatementService(
        extractor=TranscriptStatementExtractionService(settings=settings),
        repository=_build_transcript_statement_repository(app.state.transcript_repository),
    )
    app.state.transcript_diff_service = TranscriptDiffService(
        app.state.transcript_repository, statement_service=app.state.transcript_statement_service,
    )
    app.state.transcript_ingestion_service = TranscriptIngestionService(app.state.transcript_repository)
    app.state.external_retriever = (
        QdrantExternalRetriever(
            client=shared_client,
            collection_name=app.state.evidence_repository.collection_name,
            embedding_provider=app.state.evidence_repository.embedding_provider,
            embedding_version=app.state.evidence_repository.embedding_version,
        ) if shared_client is not None else ExternalRetrieverFacade()
    )
    app.state.analysis_service = AnalysisService(
        settings=settings,
        evidence_service=app.state.evidence_service,
        external_retriever_service=app.state.external_retriever,
    )
    app.state.company_intelligence_service = CompanyIntelligenceService(app.state.company_intelligence_repository)
    app.state.evidence_ingestion_service = EvidenceIngestionService(
        settings=settings,
        evidence_service=app.state.evidence_service,
        external_retriever=app.state.analysis_service.external_retriever,
        company_service=app.state.company_intelligence_service,
    )
    app.state.evidence_ingestion_scheduler = EvidenceIngestionScheduler(
        service=app.state.evidence_ingestion_service,
        settings=settings,
    )
    app.state.news_ingestion_service = NewsIngestionService(app.state.analysis_service.external_retriever)
    if shared_client is None:
        # Memory news lives in the application retriever. Give generic evidence
        # search/QA the same reader instead of a disconnected empty repository.
        app.state.evidence_service.external_retriever = app.state.analysis_service.external_retriever
    app.state.live_news_fact_check_service = LiveNewsFactCheckService(
        retriever=app.state.analysis_service.external_retriever,
        settings=settings,
    )
    app.state.redis_signal_publisher = RedisSignalPublisher(settings=settings)
    app.state.equity_report_service = EquityResearchReportService(
        settings=settings,
        token_budgeter=app.state.analysis_service.token_budgeter,
    )
    app.state.earnings_intelligence_service = EarningsIntelligenceService(
        retriever=app.state.analysis_service.external_retriever,
        company_repository=app.state.company_intelligence_repository,
    )
    app.state.control_plane_service = _get_control_service(app)
    app.state.calibration_service = _get_calibration_service(app)
    app.state.regression_service = _get_regression_service(app)
    app.state.dispatch_analysis = lambda payload, _app=app: _dispatch_analysis(payload, settings, _app)
    app.state.live_session_repository = LiveSessionRepository(
        store_path=_resolve_ai_engine_path(settings.live_session_store_path),
        executor=persistence_executor,
        retention_hours=settings.live_session_retention_hours,
        max_sessions=settings.live_session_max_sessions,
    )
    app.state.live_session_service = LiveEarningsSessionService(
        repository=app.state.live_session_repository,
        dispatcher=app.state.dispatch_analysis,
        evidence_service=app.state.evidence_service,
        company_service=app.state.company_intelligence_service,
        redis_publisher=app.state.redis_signal_publisher,
        settings=settings,
    )
    app.state.persist_envelope = lambda envelope: _persist_or_raise(app.state.event_store_repository, envelope)

    app.state.evidence_bootstrap_status = "disabled"
    app.state.evidence_bootstrap_error = None
    if settings.evidence_auto_bootstrap:
        try:
            bootstrap = getattr(app.state.evidence_repository, "bootstrap_schema", None)
            evidence_bootstrapped = bootstrap() if callable(bootstrap) else False
            app.state.company_intelligence_repository.bootstrap_schema()
            app.state.evidence_bootstrap_status = "ready" if evidence_bootstrapped else "skipped"
        except Exception as exc:
            app.state.evidence_bootstrap_status = "error"
            app.state.evidence_bootstrap_error = f"{type(exc).__name__}: {exc}"

    for router in ALL_ROUTERS:
        app.include_router(router)

    return app


app = create_app()


__all__ = [
    "HealthResponse",
    "_build_repository",
    "_build_evidence_repository",
    "_build_transcript_repository",
    "_dispatch_analysis",
    "_get_calibration_service",
    "_get_control_service",
    "_get_regression_service",
    "_persist_or_raise",
    "_schema_path_from_settings",
    "app",
    "create_app",
    "get_settings",
    "risk_score_from_sentiment",
    "run_analysis",
]
