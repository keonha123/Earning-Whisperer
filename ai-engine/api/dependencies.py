"""Shared FastAPI dependency helpers for the AI engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI

try:
    from config import Settings
    from core.analysis_service import AnalysisService
    from models.request_models import AnalyzeRequest
    from models.storage_models import PersistEnvelopeResponse
    from repositories.event_store_repository import EventStoreRepository
    from services import CalibrationService, ControlPlaneService, RegressionService
    from services.equity_report_service import EquityResearchReportService
    from services.redis_signal_publisher import RedisSignalPublisher
except ImportError:  # pragma: no cover
    from ..config import Settings
    from ..core.analysis_service import AnalysisService
    from ..models.request_models import AnalyzeRequest
    from ..models.storage_models import PersistEnvelopeResponse
    from ..repositories.event_store_repository import EventStoreRepository
    from ..services import CalibrationService, ControlPlaneService, RegressionService
    from ..services.equity_report_service import EquityResearchReportService
    from ..services.redis_signal_publisher import RedisSignalPublisher


DispatchAnalysisFn = Callable[[AnalyzeRequest], Awaitable[dict[str, Any]]]
PersistEnvelopeFn = Callable[[dict[str, Any]], PersistEnvelopeResponse]


def get_settings(app: FastAPI) -> Settings:
    return app.state.settings


def get_analysis_service(app: FastAPI) -> AnalysisService:
    return app.state.analysis_service


def get_repository(app: FastAPI) -> EventStoreRepository:
    return app.state.event_store_repository


def get_dispatch_analysis(app: FastAPI) -> DispatchAnalysisFn:
    return app.state.dispatch_analysis


def get_persist_envelope(app: FastAPI) -> PersistEnvelopeFn:
    return app.state.persist_envelope


def get_redis_signal_publisher(app: FastAPI) -> RedisSignalPublisher:
    return app.state.redis_signal_publisher


def get_equity_report_service(app: FastAPI) -> EquityResearchReportService:
    return app.state.equity_report_service


def get_control_service(app: FastAPI) -> ControlPlaneService:
    return ControlPlaneService(get_repository(app))


def get_calibration_service(app: FastAPI) -> CalibrationService:
    return CalibrationService(get_repository(app))


def get_regression_service(app: FastAPI) -> RegressionService:
    return RegressionService(get_repository(app))


__all__ = [
    "DispatchAnalysisFn",
    "PersistEnvelopeFn",
    "get_analysis_service",
    "get_calibration_service",
    "get_control_service",
    "get_dispatch_analysis",
    "get_equity_report_service",
    "get_persist_envelope",
    "get_redis_signal_publisher",
    "get_regression_service",
    "get_repository",
    "get_settings",
]
