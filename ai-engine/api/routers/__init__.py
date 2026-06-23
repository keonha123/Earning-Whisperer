"""Router registry for the AI engine API surface."""

from .analysis import router as analysis_router
from .calibration import router as calibration_router
from .company_intelligence import router as company_intelligence_router
from .control import router as control_router
from .earnings_intelligence import router as earnings_intelligence_router
from .evidence import router as evidence_router
from .equity_research import router as equity_research_router
from .health import router as health_router
from .ingestion import router as ingestion_router
from .legacy_analysis import router as legacy_analysis_router
from .live_sessions import router as live_sessions_router
from .operations import router as operations_router
from .query import router as query_router
from .regression import router as regression_router

ALL_ROUTERS = [
    health_router,
    ingestion_router,
    company_intelligence_router,
    legacy_analysis_router,
    live_sessions_router,
    operations_router,
    equity_research_router,
    earnings_intelligence_router,
    evidence_router,
    analysis_router,
    query_router,
    control_router,
    calibration_router,
    regression_router,
]

__all__ = [
    "ALL_ROUTERS",
    "analysis_router",
    "calibration_router",
    "company_intelligence_router",
    "control_router",
    "earnings_intelligence_router",
    "evidence_router",
    "equity_research_router",
    "health_router",
    "ingestion_router",
    "legacy_analysis_router",
    "live_sessions_router",
    "operations_router",
    "query_router",
    "regression_router",
]
