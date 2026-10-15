"""Milestone 4 performance metrics package.

Pure, read-only reporting derived from an M3 ``BacktestResult``. This layer
never reruns a strategy, mutates execution records, or changes M3 behaviour.
"""

from src.metrics.drawdown import DrawdownResult, compute_drawdown
from src.metrics.metrics import (
    MetricsConsistencyError,
    OpenPositionSummary,
    PerformanceReport,
    compute_metrics,
)

__all__ = [
    "DrawdownResult",
    "MetricsConsistencyError",
    "OpenPositionSummary",
    "PerformanceReport",
    "compute_drawdown",
    "compute_metrics",
]
