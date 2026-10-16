"""Milestone 13: R-multiple analytics for completed trades.

Formula under test (approved M13 contract)::

    R = net_pnl / (quantity * abs(entry_price - initial_stop))

The denominator is anchored to the *initial* stop, so a trade closed at a later
modified stop is not forced to ``-1R``.
"""

import dataclasses
import math

from src.execution import EngineConfig, run_backtest
from src.metrics import (
    RMultipleSummary,
    compute_r_multiple_summary,
    trade_r_multiple,
)
from src.strategy.models import OrderAction, StrategyDecision
from src.ui import workflow

from tests.test_execution.helpers import ScriptedStrategy, make_df
from tests.test_metrics.helpers import make_trade, three_trade_result


def _config() -> EngineConfig:
    return EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)


# --------------------------------------------------------------- initial stop use


def test_r_multiple_uses_initial_stop_not_the_modified_stop():
    # Enter long at 100 with stop 90, then trail the working stop up to 102 and
    # stop out at 101. Quantity is 100 (risk budget 1000 / distance 10).
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 96.0, 103.0),   # long entry 100; close 103 is the mark
        (101.0, 104.0, 100.0, 103.0),  # modified stop 102 -> stop out at 101
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=102.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())
    trade = result.trades[0]

    assert trade.initial_stop == 90.0
    # net = 100 * (101 - 100) = 100; initial risk = 100 * |100 - 90| = 1000.
    assert trade_r_multiple(trade) == 0.1
    # Had the modified stop (102) been used, the denominator would be 200 -> 0.5.


# ------------------------------------------------------------- long / short signs


def test_three_trade_result_r_multiples():
    # Long win, short loss, long loss (quantity 100, 10.0 stops, zero costs).
    r_multiples = [trade_r_multiple(trade) for trade in three_trade_result().trades]
    assert r_multiples == [1.0, -2.0, -1.0]


def test_short_winning_trade_r_multiple():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),
        (100.0, 104.0, 96.0, 98.0),    # short entry fills at 100
        (90.0, 92.0, 88.0, 89.0),      # market exit fills at 90
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    # net = 100 * (100 - 90) = 1000; initial risk = 100 * |100 - 110| = 1000 -> +1R.
    assert trade_r_multiple(result.trades[0]) == 1.0


def test_exact_long_and_short_values_from_hand_built_trades():
    long_trade = make_trade(
        250.0, direction="LONG", entry_price=100.0, exit_price=105.0,
        quantity=50.0, initial_stop=90.0,
    )
    short_trade = make_trade(
        250.0, direction="SHORT", entry_price=100.0, exit_price=95.0,
        quantity=50.0, initial_stop=110.0,
    )
    # initial risk = 50 * 10 = 500 on both sides.
    assert trade_r_multiple(long_trade) == 0.5
    assert trade_r_multiple(short_trade) == 0.5


# --------------------------------------------------------------- commissions


def test_commissions_affect_numerator_but_not_denominator():
    trade = make_trade(
        990.0, gross_pnl=1000.0, entry_commission=5.0, exit_commission=5.0,
        quantity=100.0, entry_price=100.0, exit_price=110.0, initial_stop=90.0,
    )
    # net (990) over price risk only (100 * 10 = 1000); commissions are NOT added
    # to the denominator (which would give 990 / 1010).
    assert math.isclose(trade_r_multiple(trade), 0.99, rel_tol=0.0, abs_tol=1e-12)


# ------------------------------------------------------------- undefined cases


def test_missing_initial_stop_returns_none():
    assert make_trade(100.0).initial_stop is None
    assert trade_r_multiple(make_trade(100.0)) is None


def test_zero_entry_to_stop_distance_returns_none():
    trade = make_trade(100.0, entry_price=100.0, initial_stop=100.0)
    assert trade_r_multiple(trade) is None


def test_non_positive_quantity_returns_none():
    assert trade_r_multiple(make_trade(100.0, quantity=0.0, initial_stop=90.0)) is None
    assert trade_r_multiple(make_trade(100.0, quantity=-10.0, initial_stop=90.0)) is None


def test_non_finite_inputs_return_none():
    assert trade_r_multiple(make_trade(100.0, initial_stop=float("inf"))) is None
    assert trade_r_multiple(make_trade(100.0, initial_stop=float("nan"))) is None
    assert trade_r_multiple(make_trade(100.0, entry_price=float("nan"), initial_stop=90.0)) is None
    assert trade_r_multiple(make_trade(float("inf"), initial_stop=90.0)) is None


def test_non_finite_output_returns_none():
    # Finite inputs whose ratio overflows to +inf must not leak through.
    trade = make_trade(1e308, quantity=1e-300, entry_price=100.0, initial_stop=90.0)
    assert trade_r_multiple(trade) is None


def test_non_numeric_input_returns_none():
    base = make_trade(100.0, quantity=50.0, entry_price=100.0, initial_stop=90.0)
    assert trade_r_multiple(dataclasses.replace(base, entry_price="100.0")) is None
    assert trade_r_multiple(dataclasses.replace(base, initial_stop="90.0")) is None


# --------------------------------------------------------------- aggregation


def test_summary_excludes_non_computable_trades_from_the_mean():
    trades = [
        make_trade(500.0, quantity=50.0, entry_price=100.0, initial_stop=90.0),   # +1.0
        make_trade(-250.0, quantity=50.0, entry_price=100.0, initial_stop=90.0),  # -0.5
        make_trade(100.0),                                                        # no stop -> None
    ]
    summary = compute_r_multiple_summary(trades)

    assert isinstance(summary, RMultipleSummary)
    assert summary.mean_r == 0.25  # (1.0 + -0.5) / 2
    assert summary.computable_count == 2
    assert summary.non_computable_count == 1


def test_summary_of_empty_input():
    summary = compute_r_multiple_summary([])
    assert summary.mean_r is None
    assert summary.computable_count == 0
    assert summary.non_computable_count == 0


def test_summary_all_non_computable():
    trades = [make_trade(1.0), make_trade(2.0)]  # neither has an initial stop
    summary = compute_r_multiple_summary(trades)
    assert summary.mean_r is None
    assert summary.computable_count == 0
    assert summary.non_computable_count == 2


# --------------------------------------------------------- purity / determinism


def test_summary_is_deterministic_and_does_not_mutate_input():
    trades = [
        make_trade(500.0, quantity=50.0, entry_price=100.0, initial_stop=90.0),
        make_trade(-250.0, quantity=50.0, entry_price=100.0, initial_stop=90.0),
    ]
    before = [dataclasses.asdict(trade) for trade in trades]

    first = compute_r_multiple_summary(trades)
    second = compute_r_multiple_summary(trades)

    assert first == second
    assert [dataclasses.asdict(trade) for trade in trades] == before


# --------------------------------------------------- M8 / M9 compatibility


def test_m8_linkage_and_m9_columns_unchanged_with_initial_stop_present():
    result = three_trade_result()

    linked = workflow.link_trade_fills(result)
    assert len(linked) == 3
    assert all(item.trade.initial_stop is not None for item in linked)

    # The new descriptive field must not leak into the M9 audit/UI columns.
    assert "initial_stop" not in list(workflow.linked_trades_to_dataframe(result).columns)
    assert "initial_stop" not in list(workflow.trades_to_dataframe(result).columns)
