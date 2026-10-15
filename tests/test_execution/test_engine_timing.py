import pandas as pd
import pytest

from src.execution import EngineConfig, run_backtest
from src.strategy.models import OrderAction, OrderType, StrategyDecision

from tests.test_execution.helpers import ScriptedStrategy, make_df


def _config(**overrides):
    base = dict(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)
    base.update(overrides)
    return EngineConfig(**base)


def test_market_entry_does_not_fill_on_signal_candle():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (102.0, 104.0, 101.0, 103.0),
        (103.0, 105.0, 102.0, 104.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0, tag="e")]}
    strategy = ScriptedStrategy(script)

    result = run_backtest(strategy, df, _config())

    assert strategy.seen_indices == [0, 1, 2]
    assert len(result.fills) == 1
    entry = result.fills[0]
    assert entry.kind.value == "ENTRY"
    assert entry.bar_index == 1
    assert entry.price == 102.0  # next eligible candle open
    # quantity = 1000 / (102 - 95) = 142.857 -> 142
    assert entry.quantity == 142.0


def test_limit_entry_fills_at_limit_when_not_gapped():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (102.0, 104.0, 99.5, 101.0),  # open above limit, low touches limit
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=90.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert len(result.fills) == 1
    assert result.fills[0].price == 100.0
    assert result.fills[0].bar_index == 1


def test_limit_entry_fills_at_open_when_gapped_through():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (98.0, 101.0, 97.0, 100.0),  # open already through the buy limit
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=90.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills[0].price == 98.0
    assert result.fills[0].price < 100.0


def test_limit_entry_stays_working_until_touched():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (105.0, 106.0, 103.0, 104.0),  # no touch (low 103 > 100)
        (104.0, 105.0, 99.0, 102.0),   # low 99 <= 100 -> fills at limit
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=90.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert len(result.fills) == 1
    assert result.fills[0].bar_index == 2
    assert result.fills[0].price == 100.0


def test_market_exit_fills_on_next_candle_open():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (102.0, 104.0, 101.0, 103.0),
        (103.0, 105.0, 100.0, 101.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0, tag="e")],
        1: [StrategyDecision(action=OrderAction.EXIT, tag="x")],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert [f.kind.value for f in result.fills] == ["ENTRY", "EXIT"]
    exit_fill = result.fills[1]
    assert exit_fill.bar_index == 2
    assert exit_fill.price == 103.0  # candle 2 open


def test_unfilled_limit_entry_expires_at_end_of_data():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (101.0, 104.0, 100.5, 103.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=50.0, stop_loss=40.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert len(result.unfilled_orders) == 1
    assert result.unfilled_orders[0].action == "ENTER_LONG"
    assert result.unfilled_orders[0].limit_price == 50.0


def test_market_slippage_applied_against_trader():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (103.0, 106.0, 102.0, 105.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config(slippage_fraction=0.01))

    entry, exit_ = result.fills
    assert entry.price == pytest.approx(100.0 * 1.01)  # buy pays up
    assert exit_.price == pytest.approx(103.0 * 0.99)  # sell receives less
    assert entry.slippage > 0.0
    assert exit_.slippage > 0.0


def test_limit_fills_have_no_slippage():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (102.0, 104.0, 99.5, 101.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=90.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config(slippage_fraction=0.05))

    assert result.fills[0].price == 100.0
    assert result.fills[0].slippage == 0.0


def test_equity_curve_has_one_point_per_bar():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (102.0, 104.0, 101.0, 103.0),
        (103.0, 105.0, 102.0, 104.0),
    ])
    result = run_backtest(ScriptedStrategy({}), df, _config())
    assert len(result.equity_curve) == len(df) == result.bars_processed
    assert all(point.equity == 100_000.0 for point in result.equity_curve)


def test_market_entry_on_final_candle_expires_unfilled():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (101.0, 104.0, 100.0, 102.0),
    ])
    # Queued on the final candle: no later eligible candle exists, so it expires
    # unfilled (rule 13).
    script = {1: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert result.is_flat
    assert len(result.unfilled_orders) == 1
    expired = result.unfilled_orders[0]
    assert expired.action == "ENTER_LONG"
    assert expired.order_type == "MARKET"
    assert expired.limit_price is None
    assert expired.queued_bar_index == 1


def test_working_limit_exit_expires_while_position_remains_open():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT, order_type=OrderType.LIMIT, limit_price=200.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    # The entry fills, the limit exit is never touched and no later candle exists,
    # so the exit expires while the position stays open (rule 13).
    assert [f.kind.value for f in result.fills] == ["ENTRY"]
    assert result.trades == ()
    assert result.is_flat is False
    assert len(result.unfilled_orders) == 1
    expired = result.unfilled_orders[0]
    assert expired.action == "EXIT"
    assert expired.order_type == "LIMIT"
    assert expired.limit_price == 200.0
    assert expired.queued_bar_index == 1
