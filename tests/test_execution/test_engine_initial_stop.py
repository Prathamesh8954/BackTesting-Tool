"""Milestone 13: initial-stop capture on the completed ``Trade`` record.

These tests pin Phase 1 of the R-multiple contract: the initial stop is captured
once at entry, is distinct from the mutable working stop, and survives later
protection modifications unchanged.
"""

from src.execution import EngineConfig, run_backtest
from src.strategy.models import OrderAction, StrategyDecision

from tests.test_execution.helpers import ScriptedStrategy, make_df


def _config() -> EngineConfig:
    return EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)


def test_long_entry_records_initial_stop():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),
        (100.0, 108.0, 95.0, 105.0),   # long entry fills at 100
        (110.0, 112.0, 109.0, 111.0),  # market exit fills at 110
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert len(result.trades) == 1
    assert result.trades[0].initial_stop == 90.0


def test_short_entry_records_initial_stop():
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

    assert len(result.trades) == 1
    assert result.trades[0].initial_stop == 110.0


def test_protection_modification_changes_working_stop_not_initial_stop():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 96.0, 103.0),   # long entry 100; close 103 is the mark
        (101.0, 104.0, 100.0, 103.0),  # modified stop 102 active -> low 100 <= 102
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=102.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())
    trade = result.trades[0]

    # The recorded initial stop is unchanged by the modification...
    assert trade.initial_stop == 90.0
    # ...but the working stop moved: the position closes at min(open=101, 102).
    assert trade.exit_kind.value == "STOP_LOSS"
    assert trade.exit_price == 101.0
