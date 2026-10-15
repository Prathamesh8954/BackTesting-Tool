"""Drawdown calculation for the metrics layer (Milestones 4 and 5).

Pure, deterministic helpers. The drawdown running peak is anchored to the
run's ``initial_capital`` (approved M4 policy), so the account baseline is part
of the peak even though the equity curve does not carry a separate baseline
point.

The equity curve is consumed as a sequence of ``(bar_index, equity)`` pairs so
this module stays decoupled from the execution models. ``equity`` is the
end-of-bar mark-to-market equity recorded by the M3 engine.

Conventions (approved):

* The running peak starts at ``initial_capital``.
* A peak is updated when a bar's equity is greater than **or equal to** the
  running peak; when several bars share the peak value the latest bar index is
  recorded.
* Maximum currency drawdown and maximum percentage drawdown are computed
  independently and may therefore occur at different bars.
* Percentage drawdown is expressed in percentage points (``x 100``), matching
  ``BacktestResult.total_return_pct``.
* Empty, single-point and flat curves have zero drawdown.

:func:`compute_drawdown_series` exposes the same conventions as a per-bar path
(the Milestone 5 drawdown series); the two helpers must stay in agreement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class DrawdownResult:
    """Maximum drawdown figures for one equity path.

    Attributes:
        currency: Largest peak-to-trough decline in account currency.
        pct: Largest peak-to-trough decline as a percentage of the peak, in
            percentage points (``0-100`` style, not a fraction).
        currency_peak_bar_index: Bar index of the peak for the maximum currency
            decline, or ``None`` when the peak is the initial-capital baseline
            no bar has yet matched.
        currency_trough_bar_index: Bar index of the trough for the maximum
            currency decline, or ``None`` when there is no decline.
        pct_peak_bar_index: Bar index of the peak for the maximum percentage
            decline, or ``None`` (see above).
        pct_trough_bar_index: Bar index of the trough for the maximum percentage
            decline, or ``None`` when there is no decline.
    """

    currency: float
    pct: float
    currency_peak_bar_index: Optional[int]
    currency_trough_bar_index: Optional[int]
    pct_peak_bar_index: Optional[int]
    pct_trough_bar_index: Optional[int]


def compute_drawdown(
    equity_points: Sequence[tuple[int, float]], initial_capital: float
) -> DrawdownResult:
    """Computes maximum drawdown over an end-of-bar equity path.

    Args:
        equity_points: Ordered ``(bar_index, equity)`` pairs.
        initial_capital: Starting account equity; anchors the running peak.

    Returns:
        A :class:`DrawdownResult`. Empty, single-point and flat paths yield zero
        currency and percentage drawdown with ``None`` indices.
    """
    peak = float(initial_capital)
    peak_bar_index: Optional[int] = None

    best_currency = 0.0
    currency_peak_bar_index: Optional[int] = None
    currency_trough_bar_index: Optional[int] = None

    best_pct = 0.0
    pct_peak_bar_index: Optional[int] = None
    pct_trough_bar_index: Optional[int] = None

    for bar_index, equity in equity_points:
        equity = float(equity)
        if equity >= peak:
            peak = equity
            peak_bar_index = bar_index

        decline = peak - equity
        if decline > best_currency:
            best_currency = decline
            currency_peak_bar_index = peak_bar_index
            currency_trough_bar_index = bar_index

        if peak > 0.0:
            decline_pct = (peak - equity) / peak
            if decline_pct > best_pct:
                best_pct = decline_pct
                pct_peak_bar_index = peak_bar_index
                pct_trough_bar_index = bar_index

    return DrawdownResult(
        currency=best_currency,
        pct=best_pct * 100.0,
        currency_peak_bar_index=currency_peak_bar_index,
        currency_trough_bar_index=currency_trough_bar_index,
        pct_peak_bar_index=pct_peak_bar_index,
        pct_trough_bar_index=pct_trough_bar_index,
    )


@dataclass(frozen=True)
class DrawdownPoint:
    """One bar on the drawdown path (Milestone 5 drawdown series).

    The fields mirror the :func:`compute_drawdown` conventions so the series and
    the maximum-drawdown summary can never drift apart:

    Attributes:
        bar_index: The bar index carried over unchanged from the input.
        equity: End-of-bar equity for this bar.
        peak: Running peak *after* this bar. The peak is updated when
            ``equity >= peak`` (the latest bar wins ties), starting from
            ``initial_capital``.
        peak_bar_index: Bar index that established ``peak``, or ``None`` while
            the peak is still the ``initial_capital`` baseline that no bar has
            matched.
        decline_currency: ``peak - equity`` (never negative).
        decline_pct: ``decline_currency / peak * 100.0`` when ``peak > 0`` and
            ``0.0`` otherwise, in percentage points (``0-100`` style).
    """

    bar_index: int
    equity: float
    peak: float
    peak_bar_index: Optional[int]
    decline_currency: float
    decline_pct: float


@dataclass(frozen=True)
class DrawdownSeries:
    """Immutable per-bar drawdown path for one equity curve.

    ``points`` is an immutable tuple in input order.
    """

    points: tuple[DrawdownPoint, ...]


def compute_drawdown_series(
    equity_points: Sequence[tuple[int, float]], initial_capital: float
) -> DrawdownSeries:
    """Computes the per-bar drawdown path over an end-of-bar equity curve.

    Uses exactly the :func:`compute_drawdown` conventions: the running peak
    starts at ``initial_capital`` and is updated when ``equity >= peak`` (the
    latest bar wins ties); ``decline_currency = peak - equity``; and
    ``decline_pct`` is ``decline_currency / peak * 100`` when ``peak > 0`` and
    ``0.0`` otherwise. Percentage values are in percentage points (``x 100``).

    Input order and input bar indices are preserved. The input is read only and
    never mutated; an empty input yields an empty series.

    Args:
        equity_points: Ordered ``(bar_index, equity)`` pairs.
        initial_capital: Starting account equity; anchors the running peak.

    Returns:
        A :class:`DrawdownSeries` with one :class:`DrawdownPoint` per input bar.
    """
    peak = float(initial_capital)
    peak_bar_index: Optional[int] = None
    points: list[DrawdownPoint] = []

    for bar_index, equity in equity_points:
        equity = float(equity)
        if equity >= peak:
            peak = equity
            peak_bar_index = bar_index

        decline_currency = peak - equity
        if peak > 0.0:
            decline_pct = decline_currency / peak * 100.0
        else:
            decline_pct = 0.0

        points.append(
            DrawdownPoint(
                bar_index=bar_index,
                equity=equity,
                peak=peak,
                peak_bar_index=peak_bar_index,
                decline_currency=decline_currency,
                decline_pct=decline_pct,
            )
        )

    return DrawdownSeries(points=tuple(points))
