from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from api.routers import ALL_ROUTERS
    from config import Settings, get_settings
    from core.analysis_service import AnalysisService, run_analysis
    from db.postgres_executor import PsycopgExecutor
    from models.request_models import AnalyzeRequest
    from models.storage_models import PersistEnvelopeResponse
    from repositories.event_store_repository import EventStoreRepository
    from services import CalibrationService, ControlPlaneService, EquityResearchReportService, RegressionService
    from services.redis_signal_publisher import RedisSignalPublisher
    from services.runtime_dispatch_service import dispatch_analysis
except ImportError:  # pragma: no cover
    from .api.routers import ALL_ROUTERS
    from .config import Settings, get_settings
    from .core.analysis_service import AnalysisService, run_analysis
    from .db.postgres_executor import PsycopgExecutor
    from .models.request_models import AnalyzeRequest
    from .models.storage_models import PersistEnvelopeResponse
    from .repositories.event_store_repository import EventStoreRepository
    from .services import CalibrationService, ControlPlaneService, EquityResearchReportService, RegressionService
    from .services.redis_signal_publisher import RedisSignalPublisher
    from .services.runtime_dispatch_service import dispatch_analysis


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
    app = FastAPI(title="EarningWhisperer AI Engine", version=settings.app_version)

    app.config = {
        "GEMINI_FAST_MODEL": settings.gemini_primary_model,
        "GEMINI_PRO_MODEL": settings.gemini_review_model,
        "GEMINI_PRIMARY_MODEL": settings.gemini_primary_model,
        "GEMINI_REVIEW_MODEL": settings.gemini_review_model,
        "ENABLE_REVIEW_PASS": settings.enable_review_pass,
    }

    app.state.settings = settings
    app.state.analysis_service = AnalysisService(settings=settings)
    app.state.event_store_repository = _build_repository(settings)
    app.state.redis_signal_publisher = RedisSignalPublisher(settings=settings)
    app.state.equity_report_service = EquityResearchReportService(
        settings=settings,
        token_budgeter=app.state.analysis_service.token_budgeter,
    )
    app.state.control_plane_service = _get_control_service(app)
    app.state.calibration_service = _get_calibration_service(app)
    app.state.regression_service = _get_regression_service(app)
    app.state.dispatch_analysis = lambda payload, _app=app: _dispatch_analysis(payload, settings, _app)
    app.state.persist_envelope = lambda envelope: _persist_or_raise(app.state.event_store_repository, envelope)

    for router in ALL_ROUTERS:
        app.include_router(router)

    return app


app = create_app()


__all__ = [
    "HealthResponse",
    "_build_repository",
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
