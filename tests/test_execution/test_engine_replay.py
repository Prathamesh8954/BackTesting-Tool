from typing import Sequence

import pytest

from src.execution import EngineConfig, run_backtest
from src.strategy.base import Strategy
from src.strategy.context import StrategyContext
from src.strategy.models import OrderAction, StrategyDecision

from tests.test_execution.helpers import ScriptedStrategy, make_df


def _config():
    return EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)


def _comparable(result):
    return {
        "fills": [(f.kind.value, f.side.value, f.bar_index, f.price, f.quantity) for f in result.fills],
        "trades": [(t.direction, t.entry_price, t.exit_price, t.net_pnl) for t in result.trades],
        "rejections": [(r.reason, r.bar_index) for r in result.rejections],
        "equity": [p.equity for p in result.equity_curve],
        "final_equity": result.final_equity,
    }


def test_replay_is_deterministic_for_fresh_and_reused_strategies():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (103.0, 106.0, 101.0, 102.0),
        (102.0, 104.0, 100.0, 101.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)],
        2: [StrategyDecision(action=OrderAction.EXIT)],
    }

    fresh_a = run_backtest(ScriptedStrategy(script), df, _config())
    fresh_b = run_backtest(ScriptedStrategy(script), df, _config())

    reused = ScriptedStrategy(script)
    first = run_backtest(reused, df, _config())
    second = run_backtest(reused, df, _config())

    assert _comparable(fresh_a) == _comparable(fresh_b)
    assert _comparable(first) == _comparable(second)


class _Recorder(Strategy):
    def __init__(self) -> None:
        self.snapshots: list[tuple] = []

    def on_start(self) -> None:
        self.snapshots = []

    def on_bar(self, context: StrategyContext) -> Sequence[StrategyDecision]:
        self.snapshots.append(
            (
                context.current_index,
                context.position.is_open,
                context.position.direction,
                context.position.current_stop_loss,
                context.position.current_take_profit,
                context.position.bars_held,
                context.account.cash,
                context.account.equity,
            )
        )
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0, take_profit=120.0)]
        return []


def test_context_snapshots_reflect_engine_state():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (102.0, 104.0, 101.0, 103.0),
        (103.0, 105.0, 102.0, 104.0),
    ])
    strategy = _Recorder()
    result = run_backtest(strategy, df, _config())

    # Bar 0: flat when the strategy runs.
    assert strategy.snapshots[0][1] is False
    assert strategy.snapshots[0][7] == pytest.approx(100_000.0)

    # Bar 1: position opened at this candle's open; snapshot shows entry candle state.
    bar1 = strategy.snapshots[1]
    assert bar1[1] is True
    assert bar1[2] == "LONG"
    assert bar1[3] == 95.0
    assert bar1[4] == 120.0
    assert bar1[5] == 0  # bars_held on the entry candle
    assert bar1[6] == pytest.approx(100_000.0 - 142.0 * 102.0)
    assert result.is_flat is False
