"""Realized P&L, account P&L, expectancy, averages and profit factor."""

import math

import pytest

from src.metrics import compute_metrics

from tests.test_metrics.helpers import (
    do_nothing_result,
    make_result,
    make_trade,
    three_trade_result,
)


def test_three_trade_pnl_expectancy_and_averages():
    report = compute_metrics(three_trade_result())

    # +1000, -2000, -1000.
    assert report.gross_realized_pnl == pytest.approx(-2000.0)
    assert report.net_realized_pnl == pytest.approx(-2000.0)
    assert report.total_pnl == pytest.approx(-2000.0)
    assert report.total_return_pct == pytest.approx(-2.0)

    assert report.average_winning_trade == pytest.approx(1000.0)
    # Signed and negative (approved policy).
    assert report.average_losing_trade == pytest.approx(-1500.0)
    assert report.expectancy == pytest.approx(-2000.0 / 3.0)


def test_profit_factor_mixed_wins_and_losses():
    trades = [make_trade(300.0), make_trade(-100.0)]
    report = compute_metrics(make_result(trades))

    assert report.profit_factor == pytest.approx(3.0)


def test_profit_factor_none_without_losing_trades():
    report = compute_metrics(make_result([make_trade(100.0), make_trade(200.0)]))
    assert report.profit_factor is None
    assert report.all_trades_winning is True


def test_profit_factor_zero_with_losses_but_no_wins():
    report = compute_metrics(make_result([make_trade(-100.0), make_trade(-50.0)]))
    assert report.profit_factor == pytest.approx(0.0)


def test_profit_factor_none_with_no_trades():
    report = compute_metrics(do_nothing_result())
    assert report.profit_factor is None


def test_undefined_averages_return_none():
    only_losses = compute_metrics(make_result([make_trade(-10.0)]))
    assert only_losses.average_winning_trade is None
    assert only_losses.average_losing_trade == pytest.approx(-10.0)

    only_wins = compute_metrics(make_result([make_trade(10.0)]))
    assert only_wins.average_losing_trade is None
    assert only_wins.average_winning_trade == pytest.approx(10.0)

    no_trades = compute_metrics(do_nothing_result())
    assert no_trades.average_winning_trade is None
    assert no_trades.average_losing_trade is None
    assert no_trades.expectancy is None


def test_gross_and_net_realized_pnl_differ_by_commissions():
    # net = gross - (entry + exit) commissions.
    trade = make_trade(90.0, gross_pnl=100.0, entry_commission=5.0, exit_commission=5.0)
    report = compute_metrics(make_result([trade]))

    assert report.gross_realized_pnl == pytest.approx(100.0)
    assert report.net_realized_pnl == pytest.approx(90.0)
    assert report.expectancy == pytest.approx(90.0)


def test_account_pnl_reuses_backtest_result_properties():
    result = three_trade_result()
    report = compute_metrics(result)

    assert report.total_pnl == result.total_pnl
    assert report.total_return_pct == result.total_return_pct


def test_net_realized_matches_result_realized_invariant():
    result = three_trade_result()
    report = compute_metrics(result)

    assert math.isclose(report.net_realized_pnl, result.realized_pnl, rel_tol=1e-12)
