"""Drawdown: initial-capital baseline, degenerate curves, independence."""

import pytest

from src.metrics import compute_drawdown, compute_metrics

from tests.test_metrics.helpers import three_trade_result


def test_empty_curve_has_zero_drawdown():
    dd = compute_drawdown([], 1000.0)

    assert dd.currency == pytest.approx(0.0)
    assert dd.pct == pytest.approx(0.0)
    assert dd.currency_peak_bar_index is None
    assert dd.currency_trough_bar_index is None
    assert dd.pct_peak_bar_index is None
    assert dd.pct_trough_bar_index is None


def test_single_point_has_zero_drawdown():
    dd = compute_drawdown([(0, 1000.0)], 1000.0)

    assert dd.currency == pytest.approx(0.0)
    assert dd.pct == pytest.approx(0.0)
    assert dd.currency_trough_bar_index is None


def test_flat_curve_has_zero_drawdown():
    dd = compute_drawdown([(0, 1000.0), (1, 1000.0), (2, 1000.0)], 1000.0)

    assert dd.currency == pytest.approx(0.0)
    assert dd.pct == pytest.approx(0.0)
    assert dd.currency_trough_bar_index is None


def test_monotonic_increasing_curve_has_zero_drawdown():
    dd = compute_drawdown([(0, 1000.0), (1, 1100.0), (2, 1200.0)], 1000.0)

    assert dd.currency == pytest.approx(0.0)
    assert dd.pct == pytest.approx(0.0)


def test_peak_followed_by_trough_hand_calculated():
    # Peak 1200 at bar 2, trough 900 at bar 3 -> 300 currency, 25%.
    dd = compute_drawdown([(0, 1000.0), (1, 1100.0), (2, 1200.0), (3, 900.0)], 1000.0)

    assert dd.currency == pytest.approx(300.0)
    assert dd.pct == pytest.approx(25.0)
    assert dd.currency_peak_bar_index == 2
    assert dd.currency_trough_bar_index == 3
    assert dd.pct_peak_bar_index == 2
    assert dd.pct_trough_bar_index == 3


def test_currency_and_percentage_drawdowns_are_independent():
    # Earlier 90% drop from a small peak (90 currency), later a 20% drop from a
    # much larger peak (200 currency). Max currency and max percentage therefore
    # occur at different bars.
    dd = compute_drawdown(
        [(0, 100.0), (1, 10.0), (2, 1000.0), (3, 800.0)], 100.0
    )

    assert dd.currency == pytest.approx(200.0)
    assert dd.currency_peak_bar_index == 2
    assert dd.currency_trough_bar_index == 3

    assert dd.pct == pytest.approx(90.0)
    assert dd.pct_peak_bar_index == 0
    assert dd.pct_trough_bar_index == 1


def test_initial_capital_baseline_is_included_in_peak():
    # Both equity points are below the initial capital: the baseline must still
    # anchor the running peak, so the worst decline is measured from 1000 to the
    # lowest point (400 at bar 1), not point-to-point within the curve.
    dd = compute_drawdown([(0, 500.0), (1, 400.0)], 1000.0)

    assert dd.currency == pytest.approx(600.0)
    assert dd.pct == pytest.approx(60.0)
    assert dd.currency_peak_bar_index is None  # peak is the initial baseline
    assert dd.currency_trough_bar_index == 1


def test_metrics_drawdown_matches_hand_calculated_equity_path():
    # Equity path: 100000, 100500, 101000, 101000, 99000, 99500, 98000.
    # Peak 101000 -> worst trough 98000 = 3000 currency, 3000/101000 = 2.9702...%.
    result = three_trade_result()
    report = compute_metrics(result)

    assert [point.equity for point in result.equity_curve] == pytest.approx(
        [100000.0, 100500.0, 101000.0, 101000.0, 99000.0, 99500.0, 98000.0]
    )

    assert report.max_drawdown_currency == pytest.approx(3000.0)
    assert report.max_drawdown_pct == pytest.approx(3000.0 / 101000.0 * 100.0)
    assert report.drawdown.currency_trough_bar_index == 6
    assert report.drawdown.pct_trough_bar_index == 6
