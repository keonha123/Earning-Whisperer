"""Router registry for the AI engine API surface."""

from .analysis import router as analysis_router
from .calibration import router as calibration_router
from .control import router as control_router
from .equity_research import router as equity_research_router
from .health import router as health_router
from .legacy_analysis import router as legacy_analysis_router
from .query import router as query_router
from .regression import router as regression_router

ALL_ROUTERS = [
    health_router,
    legacy_analysis_router,
    equity_research_router,
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
    "control_router",
    "equity_research_router",
    "health_router",
    "legacy_analysis_router",
    "query_router",
    "regression_router",
]
