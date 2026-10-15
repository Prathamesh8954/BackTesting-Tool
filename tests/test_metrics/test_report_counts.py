"""Counts, win/loss/breakeven classification and win-rate denominator."""

import pytest

from src.metrics import compute_metrics

from tests.test_metrics.helpers import (
    do_nothing_result,
    make_result,
    make_trade,
    three_trade_result,
)


def test_three_trade_counts_include_long_and_short():
    result = three_trade_result()
    report = compute_metrics(result)

    # Long win (+1000), short loss (-2000), long loss (-1000).
    assert [trade.direction for trade in result.trades] == ["LONG", "SHORT", "LONG"]
    assert report.closed_trade_count == 3
    assert report.winning_trades == 1
    assert report.losing_trades == 2
    assert report.breakeven_trades == 0
    assert report.win_rate == pytest.approx(1.0 / 3.0)
    assert report.all_trades_winning is False


def test_breakeven_is_neither_win_nor_loss_but_counts_in_denominator():
    trades = [make_trade(100.0), make_trade(0.0), make_trade(0.0)]
    report = compute_metrics(make_result(trades))

    assert report.closed_trade_count == 3
    assert report.winning_trades == 1
    assert report.losing_trades == 0
    assert report.breakeven_trades == 2
    # Breakevens are in the win-rate denominator: 1 / 3.
    assert report.win_rate == pytest.approx(1.0 / 3.0)
    assert report.all_trades_winning is False


def test_zero_closed_trades():
    report = compute_metrics(do_nothing_result())

    assert report.closed_trade_count == 0
    assert report.winning_trades == 0
    assert report.losing_trades == 0
    assert report.breakeven_trades == 0
    assert report.win_rate is None
    assert report.all_trades_winning is False


def test_all_winning_trades():
    trades = [make_trade(100.0), make_trade(250.0)]
    report = compute_metrics(make_result(trades))

    assert report.closed_trade_count == 2
    assert report.winning_trades == 2
    assert report.losing_trades == 0
    assert report.breakeven_trades == 0
    assert report.win_rate == pytest.approx(1.0)
    assert report.all_trades_winning is True


def test_all_losing_trades():
    trades = [make_trade(-100.0), make_trade(-250.0)]
    report = compute_metrics(make_result(trades))

    assert report.closed_trade_count == 2
    assert report.winning_trades == 0
    assert report.losing_trades == 2
    assert report.win_rate == pytest.approx(0.0)
    assert report.all_trades_winning is False
