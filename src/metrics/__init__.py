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
from src.metrics.r_multiple import (
    DEFAULT_R_BIN_EDGES,
    RMultipleBin,
    RMultipleDistribution,
    RMultipleDistributionError,
    RMultipleSummary,
    compute_r_multiple_distribution,
    compute_r_multiple_summary,
    trade_r_multiple,
)

__all__ = [
    "DEFAULT_R_BIN_EDGES",
    "DrawdownPoint",
    "DrawdownResult",
    "DrawdownSeries",
    "MetricsConsistencyError",
    "OpenPositionSummary",
    "PerformanceReport",
    "RMultipleBin",
    "RMultipleDistribution",
    "RMultipleDistributionError",
    "RMultipleSummary",
    "compute_drawdown",
    "compute_drawdown_series",
    "compute_metrics",
    "compute_r_multiple_distribution",
    "compute_r_multiple_summary",
    "trade_r_multiple",
]
