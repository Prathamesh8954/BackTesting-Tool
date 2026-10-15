"""Milestone 4 performance metrics derived from an M3 :class:`BacktestResult`.

This module is a **pure, read-only** reporting layer. It never reruns a
strategy, mutates the input result, or changes execution behaviour. Every figure
is derived from the immutable M3 records (completed trades, fills, the equity
curve, and the account summaries).

Approved metric policies (M4):

* A win is ``net_pnl > 0``; a loss is ``net_pnl < 0``; a breakeven is
  ``net_pnl == 0``. Breakevens count toward the closed-trade total and
  expectancy but not toward the win or loss counts.
* Win rate is ``wins / all closed trades`` (breakevens are in the denominator).
* Closed-trade statistics use completed trades only.
* Undefined ratios and averages return ``None`` (never a misleading ``0``);
  counts and additive monetary totals return zero.
* Profit factor is ``None`` when there are no losing trades and ``0.0`` when
  there are losses but no wins.
* Account-level ``total_pnl`` / ``total_return_pct`` reuse the existing
  ``BacktestResult`` properties rather than re-deriving them.
* F3 is preserved: open-position unrealized P&L is **gross** and is never
  reconciled against account-level P&L. Any difference is reported as an
  informational ``reconciliation_difference`` only.

Explicitly out of scope for this milestone: R-multiple counts, target
reachability, MFE/MAE, Sharpe/annualization, and exposure analytics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from src.execution.models import BacktestResult, FillKind
from src.metrics.drawdown import DrawdownResult, compute_drawdown

_CONSISTENCY_REL_TOL = 1e-9
_CONSISTENCY_ABS_TOL = 1e-9


class MetricsConsistencyError(ValueError):
    """Raised when a ``BacktestResult`` violates an internal accounting invariant."""


@dataclass(frozen=True)
class OpenPositionSummary:
    """Read-only description of a position still open at the end of the data.

    Kept separate from completed trades; no synthetic exit trade is produced.

    ``unrealized_pnl_gross`` is gross of the open position's entry commission
    (F3). ``entry_*`` fields come from the entry fill that opened the position
    and ``mark_price`` from the final equity-curve point. Both derivations are
    unambiguous for the current one-net-position engine; they are informational
    and never used to adjust accounting.
    """

    direction: str
    quantity: float
    unrealized_pnl_gross: float
    entry_price: Optional[float]
    entry_timestamp: Any
    entry_bar_index: Optional[int]
    entry_commission: Optional[float]
    mark_price: Optional[float]


@dataclass(frozen=True)
class PerformanceReport:
    """Immutable performance summary derived from a :class:`BacktestResult`."""

    closed_trade_count: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: Optional[float]
    gross_realized_pnl: float
    net_realized_pnl: float
    total_pnl: float
    total_return_pct: float
    average_winning_trade: Optional[float]
    average_losing_trade: Optional[float]
    expectancy: Optional[float]
    profit_factor: Optional[float]
    all_trades_winning: bool
    average_bars_held: Optional[float]
    drawdown: DrawdownResult
    open_position: Optional[OpenPositionSummary]
    reconciliation_difference: float

    @property
    def max_drawdown_currency(self) -> float:
        """Maximum drawdown in account currency (see :class:`DrawdownResult`)."""
        return self.drawdown.currency

    @property
    def max_drawdown_pct(self) -> float:
        """Maximum drawdown as a percentage of the peak (see :class:`DrawdownResult`)."""
        return self.drawdown.pct


def compute_metrics(result: BacktestResult) -> PerformanceReport:
    """Computes the approved M4 metrics for ``result``.

    The input is treated as immutable: this function reads it only and returns a
    new immutable :class:`PerformanceReport`. It does not rerun the strategy.
    """
    trades = result.trades
    closed_trade_count = len(trades)

    wins = [trade for trade in trades if trade.net_pnl > 0.0]
    losses = [trade for trade in trades if trade.net_pnl < 0.0]
    breakevens = [trade for trade in trades if trade.net_pnl == 0.0]
    winning_trades = len(wins)
    losing_trades = len(losses)
    breakeven_trades = len(breakevens)

    gross_realized_pnl = float(sum(trade.gross_pnl for trade in trades))
    net_realized_pnl = float(sum(trade.net_pnl for trade in trades))

    if not math.isclose(
        net_realized_pnl,
        result.realized_pnl,
        rel_tol=_CONSISTENCY_REL_TOL,
        abs_tol=_CONSISTENCY_ABS_TOL,
    ):
        raise MetricsConsistencyError(
            "Sum of completed-trade net P&L "
            f"({net_realized_pnl!r}) does not match result.realized_pnl "
            f"({result.realized_pnl!r})."
        )

    if closed_trade_count > 0:
        win_rate: Optional[float] = winning_trades / closed_trade_count
        expectancy: Optional[float] = net_realized_pnl / closed_trade_count
        average_bars_held: Optional[float] = (
            sum(trade.exit_bar_index - trade.entry_bar_index for trade in trades)
            / closed_trade_count
        )
    else:
        win_rate = None
        expectancy = None
        average_bars_held = None

    if winning_trades > 0:
        average_winning_trade: Optional[float] = (
            sum(trade.net_pnl for trade in wins) / winning_trades
        )
    else:
        average_winning_trade = None

    if losing_trades > 0:
        average_losing_trade: Optional[float] = (
            sum(trade.net_pnl for trade in losses) / losing_trades
        )
    else:
        average_losing_trade = None

    if closed_trade_count == 0 or losing_trades == 0:
        # No losses (or no trades): profit factor is undefined. When all trades
        # win, `all_trades_winning` reports that case explicitly.
        profit_factor: Optional[float] = None
    elif winning_trades == 0:
        profit_factor = 0.0
    else:
        gross_profit = sum(trade.net_pnl for trade in wins)
        gross_loss = abs(sum(trade.net_pnl for trade in losses))
        profit_factor = gross_profit / gross_loss

    all_trades_winning = closed_trade_count > 0 and winning_trades == closed_trade_count

    drawdown = compute_drawdown(
        [(point.bar_index, point.equity) for point in result.equity_curve],
        result.initial_capital,
    )

    open_position = _open_position_summary(result)

    # F3: informational only. Equals 0.0 when flat and -open entry commission
    # when a position is open. Never used to adjust any accounting figure.
    reconciliation_difference = result.total_pnl - (
        result.realized_pnl + result.unrealized_pnl
    )

    return PerformanceReport(
        closed_trade_count=closed_trade_count,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        breakeven_trades=breakeven_trades,
        win_rate=win_rate,
        gross_realized_pnl=gross_realized_pnl,
        net_realized_pnl=net_realized_pnl,
        total_pnl=result.total_pnl,
        total_return_pct=result.total_return_pct,
        average_winning_trade=average_winning_trade,
        average_losing_trade=average_losing_trade,
        expectancy=expectancy,
        profit_factor=profit_factor,
        all_trades_winning=all_trades_winning,
        average_bars_held=average_bars_held,
        drawdown=drawdown,
        open_position=open_position,
        reconciliation_difference=reconciliation_difference,
    )


def _open_position_summary(result: BacktestResult) -> Optional[OpenPositionSummary]:
    """Builds the open-position summary, or ``None`` when the run ends flat.

    Derivation (unambiguous for the current one-net-position engine):

    * The open position was opened by the most recent ``ENTRY`` fill; there is
      no closing fill after it (otherwise the run would be flat).
    * ``mark_price`` is recovered from the final equity point, whose
      ``position_value`` is ``+qty * close`` (long) or ``-qty * close`` (short).
    """
    if result.is_flat:
        return None

    direction = result.open_direction
    quantity = result.open_quantity

    entry_price: Optional[float] = None
    entry_timestamp: Any = None
    entry_bar_index: Optional[int] = None
    entry_commission: Optional[float] = None
    for fill in reversed(result.fills):
        if fill.kind == FillKind.ENTRY:
            entry_price = fill.price
            entry_timestamp = fill.timestamp
            entry_bar_index = fill.bar_index
            entry_commission = fill.commission
            break

    mark_price: Optional[float] = None
    if result.equity_curve:
        last_point = result.equity_curve[-1]
        if last_point.quantity:
            if direction == "SHORT":
                mark_price = -last_point.position_value / last_point.quantity
            else:
                mark_price = last_point.position_value / last_point.quantity

    return OpenPositionSummary(
        direction=direction,
        quantity=quantity,
        unrealized_pnl_gross=result.unrealized_pnl,
        entry_price=entry_price,
        entry_timestamp=entry_timestamp,
        entry_bar_index=entry_bar_index,
        entry_commission=entry_commission,
        mark_price=mark_price,
    )
