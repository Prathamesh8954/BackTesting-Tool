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

Milestone 45 adds a pure binned distribution of the same R-multiples (see
``compute_r_multiple_distribution``). It is additive: it does not change the M13
formula, the M4 report schema, the execution engine or the trade model.
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


# Recognisable, symmetric R-multiple bucket boundaries (in R units). The value
# ``0.0`` separates losing from winning trades; the outer edges gather the bulk
# of realistic outcomes, while more extreme results are reported separately as
# below/above-range counts (see ``RMultipleDistribution``).
DEFAULT_R_BIN_EDGES: tuple[float, ...] = (
    -3.0,
    -2.0,
    -1.0,
    -0.5,
    0.0,
    0.5,
    1.0,
    2.0,
    3.0,
)


class RMultipleDistributionError(ValueError):
    """Raised when R-multiple distribution bin edges are invalid.

    Invalid edges are rejected rather than repaired: fewer than two edges, any
    non-numeric or non-finite edge, or edges that are not strictly increasing.
    Callers must pass explicit, strictly increasing finite edges; the helper
    never sorts or coerces them.
    """


@dataclass(frozen=True)
class RMultipleBin:
    """Immutable half-open histogram bin for R-multiples.

    Attributes:
        lower: Inclusive lower edge.
        upper: Upper edge, exclusive for every bin except the final one, which
            includes ``upper`` as well (i.e. ``[lower, upper]``).
        count: Number of computable R-multiples that fall in this bin.
    """

    lower: float
    upper: float
    count: int


@dataclass(frozen=True)
class RMultipleDistribution:
    """Immutable binned distribution of the computable R-multiples.

    Attributes:
        bins: Histogram bins in ascending edge order. Every bin but the last is
            ``[lower, upper)``; the final bin is ``[lower, upper]``.
        computable_count: Number of trades whose R-multiple is defined.
        non_computable_count: Number of trades whose R-multiple is ``None``
            (missing/invalid inputs or non-positive initial risk).
        below_range_count: Computable R-multiples strictly below the first edge
            (reported, never clamped into the first bin).
        above_range_count: Computable R-multiples strictly above the last edge
            (reported, never clamped into the last bin).

    Invariant::

        computable_count == sum(bin.count for bin in bins)
                            + below_range_count + above_range_count
    """

    bins: tuple[RMultipleBin, ...]
    computable_count: int
    non_computable_count: int
    below_range_count: int
    above_range_count: int


def _resolved_edges(edges: Sequence[float]) -> tuple[float, ...]:
    """Validates and returns ``edges`` as a tuple of finite, increasing floats.

    Raises:
        RMultipleDistributionError: If there are fewer than two edges, if any
            edge is a bool, non-numeric or non-finite, or if the edges are not
            strictly increasing. The input is never sorted or coerced.
    """
    resolved: list[float] = []
    for edge in edges:
        if isinstance(edge, bool) or not isinstance(edge, (int, float)):
            raise RMultipleDistributionError(
                f"bin edges must be finite numbers; got {edge!r}"
            )
        number = float(edge)
        if not math.isfinite(number):
            raise RMultipleDistributionError(
                f"bin edges must be finite numbers; got {edge!r}"
            )
        resolved.append(number)

    if len(resolved) < 2:
        raise RMultipleDistributionError(
            "at least two bin edges are required; "
            f"got {len(resolved)}"
        )

    for lower, upper in zip(resolved, resolved[1:]):
        if not lower < upper:
            raise RMultipleDistributionError(
                "bin edges must be strictly increasing; "
                f"got {lower!r} followed by {upper!r}"
            )

    return tuple(resolved)


def compute_r_multiple_distribution(
    trades: Sequence[Trade],
    edges: Sequence[float] = DEFAULT_R_BIN_EDGES,
) -> RMultipleDistribution:
    """Bins the R-multiples of ``trades`` (pure and read-only).

    Each computable R-multiple (defined by :func:`trade_r_multiple`, the single
    source of R-multiple semantics) is counted into exactly one bin. Bins are
    half-open ``[lower, upper)`` except the final bin, which includes its upper
    edge (``[lower, upper]``), so a value exactly equal to an interior edge falls
    in the bin whose *lower* edge it equals and a value equal to the last edge
    falls in the final bin. Values strictly outside the edge range are counted
    separately in ``below_range_count``/``above_range_count`` and are never
    clamped or discarded; undefined R-multiples are counted in
    ``non_computable_count`` and never binned.

    An empty collection yields a full set of zero-count bins with all counts
    ``0``; an all-undefined collection yields zero-count bins with
    ``non_computable_count`` set. Invalid ``edges`` raise
    :class:`RMultipleDistributionError`. The input is never mutated and the
    result is deterministic for equal inputs.
    """
    resolved = _resolved_edges(edges)
    bin_count = len(resolved) - 1
    counts = [0] * bin_count
    computable_count = 0
    non_computable_count = 0
    below_range_count = 0
    above_range_count = 0

    for trade in trades:
        r_multiple = trade_r_multiple(trade)
        if r_multiple is None:
            non_computable_count += 1
            continue

        computable_count += 1
        if r_multiple < resolved[0]:
            below_range_count += 1
            continue
        if r_multiple > resolved[-1]:
            above_range_count += 1
            continue

        for index in range(bin_count):
            lower = resolved[index]
            upper = resolved[index + 1]
            if index == bin_count - 1:
                if lower <= r_multiple <= upper:
                    counts[index] += 1
                    break
            elif lower <= r_multiple < upper:
                counts[index] += 1
                break

    bins = tuple(
        RMultipleBin(
            lower=resolved[index],
            upper=resolved[index + 1],
            count=counts[index],
        )
        for index in range(bin_count)
    )
    return RMultipleDistribution(
        bins=bins,
        computable_count=computable_count,
        non_computable_count=non_computable_count,
        below_range_count=below_range_count,
        above_range_count=above_range_count,
    )
