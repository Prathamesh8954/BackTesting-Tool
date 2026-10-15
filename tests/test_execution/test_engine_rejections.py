import pytest

from src.execution import EngineConfig, run_backtest
from src.strategy.models import OrderAction, OrderType, StrategyDecision
from src.strategy.validation import StrategyValidationError

from tests.test_execution.helpers import ScriptedStrategy, make_df


def _config(**overrides):
    base = dict(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)
    base.update(overrides)
    return EngineConfig(**base)


def _reasons(result):
    return [rejection.reason for rejection in result.rejections]


def test_entry_rejected_while_position_is_open():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
        (102.0, 105.0, 101.0, 104.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)],
        1: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "ENTRY_WHILE_OPEN" in _reasons(result)


def test_entry_rejected_while_entry_is_working():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 101.0, 102.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=50.0, stop_loss=40.0)],
        1: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "ENTRY_WHILE_WORKING" in _reasons(result)
    assert result.fills == ()


def test_duplicate_entry_decisions_in_one_bar():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {
        0: [
            StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0, tag="first"),
            StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0, tag="second"),
        ]
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert _reasons(result) == ["ENTRY_WHILE_WORKING"]
    assert result.rejections[0].tag == "second"
    assert len(result.fills) == 1


def test_exit_rejected_while_flat():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.EXIT)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert _reasons(result) == ["EXIT_WHILE_FLAT"]


def test_duplicate_exit_decisions_in_one_bar():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
        (102.0, 105.0, 101.0, 104.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)],
        1: [
            StrategyDecision(action=OrderAction.EXIT, tag="first"),
            StrategyDecision(action=OrderAction.EXIT, tag="second"),
        ],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "EXTRA_WORKING_EXIT" in _reasons(result)


def test_missing_stop_loss_rejected_at_signal():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert _reasons(result) == ["MISSING_STOP_LOSS"]
    assert result.fills == ()


def test_structural_validation_failure_aborts_the_run():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    # MARKET order must not carry a limit_price.
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, limit_price=100.0, stop_loss=95.0)]}
    with pytest.raises(StrategyValidationError):
        run_backtest(ScriptedStrategy(script), df, _config())


def test_missing_columns_aborts_the_run():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ]).drop(columns=["volume"])
    with pytest.raises(ValueError, match="missing required column"):
        run_backtest(ScriptedStrategy({}), df, _config())
