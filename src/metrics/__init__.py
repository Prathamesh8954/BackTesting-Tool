"""Performance metrics package (Milestones 4 and 5).

Pure, read-only reporting derived from an M3 ``BacktestResult``. This layer
never reruns a strategy, mutates execution records, or changes M3 behaviour.
"""

from src.metrics.drawdown import (
    DrawdownPoint,
    DrawdownResult,
    DrawdownSeries,
    compute_drawdown,
    compute_drawdown_series,
)
from src.metrics.metrics import (
    MetricsConsistencyError,
    OpenPositionSummary,
    PerformanceReport,
    compute_metrics,
)

__all__ = [
    "DrawdownPoint",
    "DrawdownResult",
    "DrawdownSeries",
    "MetricsConsistencyError",
    "OpenPositionSummary",
    "PerformanceReport",
    "compute_drawdown",
    "compute_drawdown_series",
    "compute_metrics",
]
