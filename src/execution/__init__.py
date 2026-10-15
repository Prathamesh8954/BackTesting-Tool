"""Milestone 3 execution engine package."""

from src.execution.config import EngineConfig, EngineConfigError
from src.execution.engine import RejectionReason, run_backtest
from src.execution.models import (
    BacktestResult,
    EquityPoint,
    Fill,
    FillKind,
    FillSide,
    Rejection,
    Trade,
    UnfilledOrder,
)
from src.execution.sizing import SizingRejection, compute_quantity

__all__ = [
    "BacktestResult",
    "EngineConfig",
    "EngineConfigError",
    "EquityPoint",
    "Fill",
    "FillKind",
    "FillSide",
    "Rejection",
    "RejectionReason",
    "SizingRejection",
    "Trade",
    "UnfilledOrder",
    "compute_quantity",
    "run_backtest",
]
