"""Immutable execution records produced by the Milestone 3 engine.

These are *reporting* records: they describe what the engine did (fills, round
trip trades, rejections, expiries) without carrying any strategy intent. They
are intentionally separate from the M2 strategy models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import pandas as pd


class FillKind(str, Enum):
    """Why a fill happened."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


class FillSide(str, Enum):
    """Direction of the cash/trade leg."""

    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Fill:
    """A single executed fill (entry, exit, stop-loss, or take-profit)."""

    kind: FillKind
    side: FillSide
    direction: str  # "LONG" or "SHORT"
    quantity: float
    price: float
    commission: float
    slippage: float  # cash cost of slippage, 0 for limit/SL/TP fills
    bar_index: int
    timestamp: Any
    tag: str = ""


@dataclass(frozen=True)
class Trade:
    """A completed round trip (entry -> exit/SL/TP)."""

    direction: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_bar_index: int
    exit_bar_index: int
    entry_timestamp: Any
    exit_timestamp: Any
    entry_kind: FillKind
    exit_kind: FillKind
    entry_commission: float
    exit_commission: float
    gross_pnl: float
    net_pnl: float
    tag: str = ""
    initial_stop: Optional[float] = None


@dataclass(frozen=True)
class Rejection:
    """A decision (or fill attempt) that was refused; recorded, then ignored."""

    reason: str
    message: str
    bar_index: int
    timestamp: Any
    tag: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UnfilledOrder:
    """A working order that expired because no later eligible candle existed."""

    action: str
    order_type: str
    limit_price: Optional[float]
    queued_bar_index: int
    queued_timestamp: Any
    tag: str = ""


@dataclass(frozen=True)
class EquityPoint:
    """Mark-to-market snapshot captured at the close of a single candle."""

    bar_index: int
    timestamp: Any
    cash: float
    equity: float
    position_value: float
    direction: Optional[str]
    quantity: float


@dataclass(frozen=True)
class BacktestResult:
    """Complete, deterministic output of one backtest run."""

    initial_capital: float
    final_cash: float
    final_equity: float
    realized_pnl: float
    unrealized_pnl: float
    bars_processed: int
    is_flat: bool
    open_direction: Optional[str]
    open_quantity: float
    fills: tuple[Fill, ...]
    trades: tuple[Trade, ...]
    rejections: tuple[Rejection, ...]
    unfilled_orders: tuple[UnfilledOrder, ...]
    equity_curve: tuple[EquityPoint, ...]

    @property
    def total_pnl(self) -> float:
        """Absolue P&L relative to the initial capital."""
        return self.final_equity - self.initial_capital

    @property
    def total_return_pct(self) -> float:
        """Total return as a percentage of the initial capital."""
        if self.initial_capital == 0.0:
            return 0.0
        return (self.final_equity / self.initial_capital - 1.0) * 100.0

    @property
    def winning_trades(self) -> int:
        """Number of completed trades with strictly positive net P&L."""
        return sum(1 for trade in self.trades if trade.net_pnl > 0.0)

    @property
    def losing_trades(self) -> int:
        """Number of completed trades with strictly negative net P&L."""
        return sum(1 for trade in self.trades if trade.net_pnl < 0.0)

    def equity_series(self) -> pd.Series:
        """Equity curve as a timestamp-indexed :class:`pandas.Series`."""
        if not self.equity_curve:
            return pd.Series(dtype="float64")
        index = pd.Index([point.timestamp for point in self.equity_curve], name="timestamp")
        values = [point.equity for point in self.equity_curve]
        return pd.Series(values, index=index, name="equity")
