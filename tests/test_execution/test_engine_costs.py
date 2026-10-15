import pytest

from src.execution import EngineConfig, run_backtest
from src.strategy.models import OrderAction, StrategyDecision

from tests.test_execution.helpers import ScriptedStrategy, make_df


def test_commission_and_slippage_accounting_long_round_trip():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (103.0, 106.0, 102.0, 105.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
    }
    config = EngineConfig(
        initial_capital=100_000.0,
        risk_absolute=1000.0,
        quantity_step=1.0,
        commission_per_fill=5.0,
        slippage_fraction=0.01,
    )
    result = run_backtest(ScriptedStrategy(script), df, config)

    entry, exit_ = result.fills
    # entry: (1000 - 2*5) / (101 - 90) = 90
    assert entry.quantity == 90.0
    assert entry.price == pytest.approx(101.0)
    assert entry.commission == 5.0
    assert entry.slippage == pytest.approx(0.01 * 100.0 * 90.0)
    assert exit_.price == pytest.approx(103.0 * 0.99)
    assert exit_.slippage == pytest.approx(0.01 * 103.0 * 90.0)

    # Entry: -90*101 - 5; Exit: +90*101.97 - 5
    assert result.final_cash == pytest.approx(100_077.3)
    assert result.realized_pnl == pytest.approx(77.3)
    assert result.final_equity == pytest.approx(100_077.3)
    assert result.is_flat


def test_commission_only_round_trip():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (103.0, 106.0, 102.0, 105.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
    }
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0, commission_per_fill=5.0)
    result = run_backtest(ScriptedStrategy(script), df, config)

    assert result.fills[0].quantity == 99.0  # (1000 - 10) / 10
    assert result.final_cash == pytest.approx(100_287.0)
    assert result.realized_pnl == pytest.approx(287.0)


def test_short_accounting_and_unrealized_pnl():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 98.0, 101.0),
        (101.0, 104.0, 99.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)]}
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)
    result = run_backtest(ScriptedStrategy(script), df, config)

    entry = result.fills[0]
    assert entry.quantity == 100.0  # 1000 / (110 - 100)
    # Short entry credits proceeds to cash: 100000 + 100*100
    assert result.equity_curve[1].cash == pytest.approx(110_000.0)
    # equity = cash - qty * close = 110000 - 100*101
    assert result.equity_curve[1].equity == pytest.approx(99_900.0)
    # Final close 102 -> unrealized = 100 * (100 - 102), equity = 110000 - 100*102
    assert result.unrealized_pnl == pytest.approx(-200.0)
    assert result.final_equity == pytest.approx(99_800.0)
    assert result.is_flat is False
    assert result.open_direction == "SHORT"


def test_long_unrealized_pnl_and_equity():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]}
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)
    result = run_backtest(ScriptedStrategy(script), df, config)

    assert result.fills[0].quantity == 100.0
    assert result.equity_curve[1].equity == pytest.approx(100_300.0)  # 90000 + 100*103
    assert result.unrealized_pnl == pytest.approx(300.0)
    assert result.realized_pnl == 0.0
    assert result.total_pnl == pytest.approx(300.0)


def test_unaffordable_entry_rejected_without_downsizing():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=99.0)]}
    config = EngineConfig(initial_capital=1_000.0, risk_absolute=100_000.0, quantity_step=1.0)
    result = run_backtest(ScriptedStrategy(script), df, config)

    assert result.fills == ()
    assert result.is_flat
    assert [r.reason for r in result.rejections] == ["INSUFFICIENT_CASH"]


def test_risk_fraction_equals_absolute_on_flat_account():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]}

    absolute = run_backtest(
        ScriptedStrategy(script), df, EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)
    )
    fraction = run_backtest(
        ScriptedStrategy(script), df, EngineConfig(initial_capital=100_000.0, risk_fraction=0.01, quantity_step=1.0)
    )

    assert absolute.fills[0].quantity == fraction.fills[0].quantity == 100.0


def test_missing_quantity_step_rejects_entry():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]}
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0)  # no quantity_step
    result = run_backtest(ScriptedStrategy(script), df, config)

    assert result.fills == ()
    assert [r.reason for r in result.rejections] == ["MISSING_QUANTITY_STEP"]


def test_result_summary_metrics():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]}
    result = run_backtest(
        ScriptedStrategy(script), df, EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)
    )

    assert result.total_return_pct == pytest.approx(0.2)  # +200 on 100000
    assert result.winning_trades == 0
    assert result.losing_trades == 0
    assert len(result.equity_series()) == len(df)


def test_short_round_trip_realized_pnl_and_commission():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (103.0, 106.0, 102.0, 105.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
    }
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0, commission_per_fill=5.0)
    result = run_backtest(ScriptedStrategy(script), df, config)

    assert result.fills[0].quantity == 99.0   # (1000 - 2*5) / (110 - 100)
    assert result.fills[0].price == 100.0     # bar 1 open
    assert result.fills[1].price == 103.0     # bar 2 open
    # gross = 99 * (100 - 103) = -297; net = -297 - 2*5 = -307
    trade = result.trades[0]
    assert trade.gross_pnl == pytest.approx(-297.0)
    assert trade.net_pnl == pytest.approx(-307.0)
    assert result.realized_pnl == pytest.approx(-307.0)
    assert result.final_cash == pytest.approx(99_693.0)
    assert result.final_equity == pytest.approx(99_693.0)
    assert result.is_flat


def test_long_stop_loss_realized_pnl_with_commission():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (100.0, 103.0, 94.0, 96.0),   # low 94 <= stop 95 -> stop out
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)]}
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0, commission_per_fill=5.0)
    result = run_backtest(ScriptedStrategy(script), df, config)

    assert result.fills[0].quantity == 198.0  # (1000 - 2*5) / (100 - 95)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 95.0
    assert exit_fill.slippage == 0.0
    assert result.realized_pnl == pytest.approx(-1000.0)  # 198*(95-100) - 2*5
    assert result.final_cash == pytest.approx(99_000.0)
    assert result.is_flat


def test_long_take_profit_realized_pnl_with_commission():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (103.0, 112.0, 102.0, 111.0),  # high 112 >= target 110
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, take_profit=110.0)]}
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0, commission_per_fill=5.0)
    result = run_backtest(ScriptedStrategy(script), df, config)

    assert result.fills[0].quantity == 99.0   # (1000 - 2*5) / (100 - 90)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 110.0
    assert exit_fill.slippage == 0.0
    assert result.realized_pnl == pytest.approx(980.0)  # 99*(110-100) - 2*5
    assert result.final_cash == pytest.approx(100_980.0)


def test_short_stop_loss_realized_pnl_with_commission():
    df = make_df([
        (100.0, 101.0, 98.0, 100.0),
        (100.0, 101.0, 96.0, 97.0),
        (105.0, 112.0, 104.0, 110.0),  # high 112 >= stop 110 -> stop out
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)]}
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0, commission_per_fill=5.0)
    result = run_backtest(ScriptedStrategy(script), df, config)

    assert result.fills[0].quantity == 99.0   # (1000 - 2*5) / (110 - 100)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 110.0           # max(open=105, stop=110)
    assert result.realized_pnl == pytest.approx(-1000.0)  # 99*(100-110) - 2*5
    assert result.final_cash == pytest.approx(99_000.0)


def test_stop_and_take_profit_fills_have_no_slippage():
    stop_df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (100.0, 103.0, 94.0, 96.0),
    ])
    stop_script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)]}
    config = EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0, slippage_fraction=0.05)

    stop_result = run_backtest(ScriptedStrategy(stop_script), stop_df, config)
    assert stop_result.fills[0].slippage > 0.0                      # market entry slips
    assert stop_result.fills[-1].kind.value == "STOP_LOSS"
    assert stop_result.fills[-1].slippage == 0.0                    # SL does not

    tp_df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (103.0, 112.0, 102.0, 111.0),
    ])
    tp_script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, take_profit=110.0)]}
    tp_result = run_backtest(ScriptedStrategy(tp_script), tp_df, config)
    assert tp_result.fills[0].slippage > 0.0                        # market entry slips
    assert tp_result.fills[-1].kind.value == "TAKE_PROFIT"
    assert tp_result.fills[-1].slippage == 0.0                      # TP does not
