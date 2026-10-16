"""R-multiple analytics for completed trades (Milestone 13).

Pure, read-only, strategy-agnostic helpers derived from the immutable M3
``Trade`` records. Nothing here reruns a backtest, mutates execution records, or
changes accounting.

Approved contract (M13)
-----------------------
For a completed trade let ``E`` be the actual entry fill price
(``Trade.entry_price``), ``S0`` the **initial** stop captured at entry before any
later protection modification (``Trade.initial_stop``), ``Q`` the trade quantity
(``Trade.quantity``) and ``P`` the net P&L (``Trade.net_pnl``). Then::

    initial_risk = Q * abs(E - S0)
    R            = P / initial_risk

The numerator is **net** P&L, so the existing entry/exit commissions are already
reflected through ``P``; slippage is reflected through the actual fill prices.
Commissions are deliberately **not** added to the denominator. The denominator is
anchored to the initial stop, so it does not change when the working stop is
modified; consequently a trade closed at a modified stop is not guaranteed to be
exactly ``-1R`` (gaps, later modifications and costs can all move the realized
R-multiple away from that value).

Undefined results return ``None`` (never a misleading ``0``), matching the M4
metrics convention.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from src.execution.models import Trade


def _as_finite_float(value: object) -> Optional[float]:
    """Returns ``value`` as a finite ``float``, or ``None`` when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def trade_r_multiple(trade: Trade) -> Optional[float]:
    """Returns the R-multiple of ``trade``, or ``None`` when it is undefined.

    ``R = net_pnl / (quantity * abs(entry_price - initial_stop))``. ``None`` is
    returned when any required input is absent, non-numeric, non-finite or
    otherwise invalid, when the initial risk is not strictly positive (missing
    initial stop, zero entry-to-stop distance, or non-positive quantity), or when
    the resulting R-multiple is itself non-finite. This function never raises an
    arithmetic exception and never returns ``0`` in place of an undefined value.

    The input is read only and never mutated.
    """
    entry_price = _as_finite_float(trade.entry_price)
    initial_stop = _as_finite_float(trade.initial_stop)
    quantity = _as_finite_float(trade.quantity)
    net_pnl = _as_finite_float(trade.net_pnl)

    if entry_price is None or initial_stop is None or quantity is None or net_pnl is None:
        return None

    initial_risk = quantity * abs(entry_price - initial_stop)
    if not initial_risk > 0.0:
        return None

    r_multiple = net_pnl / initial_risk
    if not math.isfinite(r_multiple):
        return None
    return r_multiple


@dataclass(frozen=True)
class RMultipleSummary:
    """Immutable R-multiple coverage summary for a set of completed trades.

    Attributes:
        mean_r: Mean R-multiple across the trades with a defined R-multiple, or
            ``None`` when no trade has a computable R-multiple.
        computable_count: Number of trades whose R-multiple is defined.
        non_computable_count: Number of completed trades whose R-multiple is
            ``None`` (missing/invalid inputs or non-positive initial risk).
    """

    mean_r: Optional[float]
    computable_count: int
    non_computable_count: int


def compute_r_multiple_summary(trades: Sequence[Trade]) -> RMultipleSummary:
    """Summarises the R-multiples of ``trades`` (pure and read-only).

    ``None`` values are excluded from ``mean_r``; when no trade is computable
    ``mean_r`` is ``None``. An empty collection yields ``mean_r=None`` with both
    counts ``0``. The input is never mutated.
    """
    values: list[float] = []
    non_computable_count = 0
    for trade in trades:
        r_multiple = trade_r_multiple(trade)
        if r_multiple is None:
            non_computable_count += 1
        else:
            values.append(r_multiple)

    mean_r = sum(values) / len(values) if values else None
    return RMultipleSummary(
        mean_r=mean_r,
        computable_count=len(values),
        non_computable_count=non_computable_count,
    )
