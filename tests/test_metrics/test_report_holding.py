"""Holding-period interpretation from bar indices."""

import pytest

from src.metrics import compute_metrics

from tests.test_metrics.helpers import (
    do_nothing_result,
    make_result,
    make_trade,
    three_trade_result,
)


def test_average_bars_held_for_three_trade_scenario():
    # Entry bar 1 -> exit bar 2, 3 -> 4, 5 -> 6, each spans one bar.
    report = compute_metrics(three_trade_result())

    assert report.average_bars_held == pytest.approx(1.0)


def test_average_bars_held_is_mean_of_bar_index_differences():
    trades = [
        make_trade(10.0, entry_bar_index=0, exit_bar_index=2),  # 2
        make_trade(-10.0, entry_bar_index=3, exit_bar_index=4),  # 1
    ]
    report = compute_metrics(make_result(trades))

    assert report.average_bars_held == pytest.approx(1.5)


def test_same_bar_entry_and_exit_is_zero_bars_held():
    # A limit entry and a same-bar stop-out (F1 convention) has zero index gap.
    trade = make_trade(5.0, entry_bar_index=5, exit_bar_index=5)
    report = compute_metrics(make_result([trade]))

    assert report.average_bars_held == pytest.approx(0.0)


def test_no_trades_has_no_holding_period():
    report = compute_metrics(do_nothing_result())
    assert report.average_bars_held is None
