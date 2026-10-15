"""Per-bar drawdown series (Milestone 5): values, edges, parity with M4."""

import dataclasses

import pytest

import src.metrics as metrics
from src.metrics import (
    DrawdownPoint,
    DrawdownSeries,
    compute_drawdown,
    compute_drawdown_series,
)

from tests.test_metrics.helpers import three_trade_result


def _bar_equity(points):
    return [(point.bar_index, point.equity) for point in points]


def _assert_m4_parity(points, initial_capital):
    """Asserts the series agrees with the M4 maximum-drawdown summary.

    M4 updates its running maximum only on a *strictly greater* decline, so it
    keeps the FIRST bar that reaches the maximum. The series is the same path,
    so the first point at the maximum must map to M4's trough/peak indices.
    """
    dd = compute_drawdown(points, initial_capital)
    series = compute_drawdown_series(points, initial_capital)

    max_currency = max((p.decline_currency for p in series.points), default=0.0)
    max_pct = max((p.decline_pct for p in series.points), default=0.0)

    assert max_currency == pytest.approx(dd.currency)
    assert max_pct == pytest.approx(dd.pct)

    if dd.currency > 0.0:
        trough_point = next(
            p for p in series.points if p.decline_currency == max_currency
        )
        assert trough_point.bar_index == dd.currency_trough_bar_index
        assert trough_point.peak_bar_index == dd.currency_peak_bar_index
    else:
        assert all(p.decline_currency == 0.0 for p in series.points)
        assert dd.currency_trough_bar_index is None

    if dd.pct > 0.0:
        pct_point = next(p for p in series.points if p.decline_pct == max_pct)
        assert pct_point.bar_index == dd.pct_trough_bar_index
        assert pct_point.peak_bar_index == dd.pct_peak_bar_index
    else:
        assert all(p.decline_pct == 0.0 for p in series.points)
        assert dd.pct_trough_bar_index is None


# --------------------------------------------------------------------- public API


def test_public_api_is_exported():
    assert metrics.DrawdownPoint is DrawdownPoint
    assert metrics.DrawdownSeries is DrawdownSeries
    assert metrics.compute_drawdown_series is compute_drawdown_series
    assert "DrawdownPoint" in metrics.__all__
    assert "DrawdownSeries" in metrics.__all__
    assert "compute_drawdown_series" in metrics.__all__


def test_returns_frozen_series_of_frozen_points():
    series = compute_drawdown_series([(0, 1000.0), (1, 900.0)], 1000.0)

    assert isinstance(series, DrawdownSeries)
    assert isinstance(series.points, tuple)
    assert all(isinstance(point, DrawdownPoint) for point in series.points)

    with pytest.raises(dataclasses.FrozenInstanceError):
        series.points = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        series.points[0].peak = 0.0  # type: ignore[misc]


# --------------------------------------------------------------------- values


def test_hand_calculated_per_bar_values():
    points = [(0, 100.0), (1, 1100.0), (2, 900.0), (3, 950.0)]
    series = compute_drawdown_series(points, 1000.0)

    assert len(series.points) == 4

    # bar 0: below the initial-capital baseline -> peak is the baseline.
    assert series.points[0] == DrawdownPoint(
        bar_index=0,
        equity=100.0,
        peak=1000.0,
        peak_bar_index=None,
        decline_currency=900.0,
        decline_pct=90.0,
    )
    # bar 1: new peak; no decline.
    assert series.points[1] == DrawdownPoint(
        bar_index=1,
        equity=1100.0,
        peak=1100.0,
        peak_bar_index=1,
        decline_currency=0.0,
        decline_pct=0.0,
    )
    # bar 2: 200 below the peak; pct in percentage points.
    assert series.points[2].peak == pytest.approx(1100.0)
    assert series.points[2].peak_bar_index == 1
    assert series.points[2].decline_currency == pytest.approx(200.0)
    assert series.points[2].decline_pct == pytest.approx(200.0 / 1100.0 * 100.0)
    # bar 3: shallower decline below the same peak.
    assert series.points[3].decline_currency == pytest.approx(150.0)
    assert series.points[3].decline_pct == pytest.approx(150.0 / 1100.0 * 100.0)


def test_initial_capital_baseline_before_any_bar_matches_it():
    series = compute_drawdown_series([(0, 500.0)], 1000.0)

    point = series.points[0]
    assert point.peak == pytest.approx(1000.0)
    assert point.peak_bar_index is None
    assert point.decline_currency == pytest.approx(500.0)
    assert point.decline_pct == pytest.approx(50.0)


def test_input_order_and_bar_indices_are_preserved():
    points = [(10, 1000.0), (20, 900.0), (30, 1100.0)]
    series = compute_drawdown_series(points, 1000.0)

    assert [p.bar_index for p in series.points] == [10, 20, 30]
    assert [p.equity for p in series.points] == [1000.0, 900.0, 1100.0]
    assert series.points[1].peak_bar_index == 10
    assert series.points[1].decline_currency == pytest.approx(100.0)
    assert series.points[1].decline_pct == pytest.approx(10.0)


def test_latest_peak_wins_ties():
    series = compute_drawdown_series(
        [(0, 1000.0), (1, 1000.0), (2, 1000.0)], 1000.0
    )

    # Each equal-to-peak bar becomes the recorded peak bar (>= update rule).
    assert [p.peak_bar_index for p in series.points] == [0, 1, 2]
    assert all(p.decline_currency == 0.0 for p in series.points)
    assert all(p.decline_pct == 0.0 for p in series.points)


def test_latest_peak_wins_ties_above_baseline():
    series = compute_drawdown_series([(0, 1200.0), (1, 1200.0)], 1000.0)

    assert [p.peak_bar_index for p in series.points] == [0, 1]
    assert all(p.decline_currency == 0.0 for p in series.points)


# --------------------------------------------------------------------- edge cases


def test_empty_input_yields_empty_series():
    series = compute_drawdown_series([], 1000.0)

    assert series.points == ()
    assert series == DrawdownSeries(points=())


def test_single_point():
    series = compute_drawdown_series([(5, 1000.0)], 1000.0)

    assert len(series.points) == 1
    assert series.points[0].peak_bar_index == 5
    assert series.points[0].decline_currency == 0.0
    assert series.points[0].decline_pct == 0.0


def test_flat_curve_has_zero_decline():
    series = compute_drawdown_series(
        [(0, 1000.0), (1, 1000.0), (2, 1000.0)], 1000.0
    )

    assert all(p.decline_currency == 0.0 for p in series.points)
    assert all(p.decline_pct == 0.0 for p in series.points)


def test_monotonically_rising_curve_has_zero_decline():
    series = compute_drawdown_series(
        [(0, 1000.0), (1, 1100.0), (2, 1200.0)], 1000.0
    )

    assert all(p.decline_currency == 0.0 for p in series.points)
    assert all(p.decline_pct == 0.0 for p in series.points)
    assert [p.peak_bar_index for p in series.points] == [0, 1, 2]


def test_non_positive_peak_yields_zero_percentage():
    # Baseline zero: a negative equity declines below a non-positive peak, so
    # currency drawdown accrues but the percentage is defined as 0.0.
    series = compute_drawdown_series([(0, -5.0), (1, 10.0)], 0.0)

    first = series.points[0]
    assert first.peak == 0.0
    assert first.peak_bar_index is None
    assert first.decline_currency == pytest.approx(5.0)
    assert first.decline_pct == 0.0
    # New peak above zero restores normal percentage behaviour.
    assert series.points[1].peak == 10.0
    assert series.points[1].decline_pct == 0.0


def test_entirely_non_positive_curve_keeps_zero_percentage():
    series = compute_drawdown_series([(0, -50.0), (1, -80.0)], -100.0)

    assert series.points[0].decline_currency == 0.0
    assert series.points[1].decline_currency == pytest.approx(30.0)
    assert all(p.decline_pct == 0.0 for p in series.points)


# --------------------------------------------------------------------- purity


def test_repeated_calls_are_deterministic():
    points = [(0, 1000.0), (1, 1100.0), (2, 900.0), (3, 950.0)]

    first = compute_drawdown_series(points, 1000.0)
    second = compute_drawdown_series(points, 1000.0)

    assert first == second
    assert dataclasses.asdict(first) == dataclasses.asdict(second)


def test_input_is_not_mutated():
    points = [(0, 1000.0), (1, 900.0), (2, 1100.0)]
    before = list(points)

    compute_drawdown_series(points, 1000.0)

    assert points == before


# --------------------------------------------------------------------- M4 parity


def test_parity_with_m4_on_engine_fixture():
    result = three_trade_result()

    _assert_m4_parity(_bar_equity(result.equity_curve), result.initial_capital)


def test_parity_with_m4_on_hand_built_curves():
    _assert_m4_parity([(0, 100.0), (1, 1100.0), (2, 900.0), (3, 950.0)], 1000.0)
    _assert_m4_parity([(0, 500.0), (1, 400.0)], 1000.0)
    _assert_m4_parity([(0, 1000.0), (1, 1100.0), (2, 1200.0), (3, 900.0)], 1000.0)


def test_parity_with_m4_on_empty_and_flat_curves():
    _assert_m4_parity([], 1000.0)
    _assert_m4_parity([(0, 1000.0), (1, 1000.0), (2, 1000.0)], 1000.0)


def test_duplicate_maximum_drawdown_uses_first_occurrence():
    # The same maximum currency decline (200) and maximum percentage decline
    # occur at bar 2 and again at bar 4.
    points = [(0, 1000.0), (1, 1100.0), (2, 900.0), (3, 1100.0), (4, 900.0)]
    series = compute_drawdown_series(points, 1000.0)
    dd = compute_drawdown(points, 1000.0)

    assert series.points[2].decline_currency == pytest.approx(200.0)
    assert series.points[4].decline_currency == pytest.approx(200.0)
    assert series.points[2].decline_pct == pytest.approx(200.0 / 1100.0 * 100.0)
    assert series.points[4].decline_pct == pytest.approx(200.0 / 1100.0 * 100.0)

    # M4 keeps the first bar at the maximum (strictly-greater update rule); the
    # series must therefore map the first maximum point to M4's indices.
    assert dd.currency_trough_bar_index == 2
    assert dd.pct_trough_bar_index == 2
    first_currency = next(
        p for p in series.points if p.decline_currency == 200.0
    )
    assert first_currency.bar_index == dd.currency_trough_bar_index
    assert first_currency.peak_bar_index == dd.currency_peak_bar_index

    _assert_m4_parity(points, 1000.0)
