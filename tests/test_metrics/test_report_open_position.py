"""Open position at end of data: gross unrealized P&L, F3, no synthetic exit."""

import pytest

from src.metrics import compute_metrics

from tests.test_metrics.helpers import (
    do_nothing_result,
    open_long_result,
    open_short_result,
)


def test_open_long_position_summary_and_reconciliation():
    result = open_long_result()
    report = compute_metrics(result)

    assert result.is_flat is False
    assert report.closed_trade_count == 0
    assert report.open_position is not None

    summary = report.open_position
    assert summary.direction == "LONG"
    assert summary.quantity == pytest.approx(100.0)
    assert summary.entry_price == pytest.approx(100.0)
    assert summary.entry_bar_index == 1
    assert summary.entry_commission == pytest.approx(5.0)
    assert summary.mark_price == pytest.approx(108.0)

    # F3: unrealized P&L is gross of the entry commission (100 * (108 - 100)).
    assert summary.unrealized_pnl_gross == pytest.approx(800.0)

    # Account P&L reflects the commission actually charged; the difference is
    # exactly the open trade's entry commission and is informational only.
    assert report.total_pnl == pytest.approx(795.0)
    assert report.reconciliation_difference == pytest.approx(-5.0)
    assert report.reconciliation_difference == pytest.approx(-summary.entry_commission)


def test_open_short_position_mark_and_unrealized():
    result = open_short_result()
    report = compute_metrics(result)

    assert result.is_flat is False
    assert report.open_position is not None

    summary = report.open_position
    assert summary.direction == "SHORT"
    assert summary.quantity == pytest.approx(100.0)
    assert summary.entry_price == pytest.approx(100.0)
    assert summary.entry_bar_index == 1
    # mark recovered from position_value (-qty * close): -( -9700 ) / 100 = 97.
    assert summary.mark_price == pytest.approx(97.0)
    assert summary.unrealized_pnl_gross == pytest.approx(300.0)

    assert report.total_pnl == pytest.approx(295.0)
    assert report.reconciliation_difference == pytest.approx(-5.0)


def test_open_position_does_not_create_a_synthetic_exit_trade():
    for result in (open_long_result(), open_short_result()):
        report = compute_metrics(result)
        assert result.trades == ()
        assert result.fills[-1].kind.value == "ENTRY"
        assert report.closed_trade_count == 0
        assert report.net_realized_pnl == pytest.approx(0.0)


def test_flat_result_has_no_open_position_summary():
    report = compute_metrics(do_nothing_result())
    assert report.open_position is None
    # Flat runs reconcile exactly.
    assert report.reconciliation_difference == pytest.approx(0.0)
