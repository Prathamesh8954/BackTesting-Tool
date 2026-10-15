from typing import Sequence
import pandas as pd
import pytest
from src.strategy.base import Strategy
from src.strategy.context import StrategyContext
from src.strategy.models import OrderAction, StrategyDecision


class CountingStrategy(Strategy):
    """Simple stateful test strategy that counts bars and emits a decision every N bars."""

    def __init__(self, trigger_interval: int = 2):
        self.trigger_interval = trigger_interval
        self.bar_count = 0
        self.history_lengths = []
        self.is_started = False
        self.is_finished = False

    def on_start(self) -> None:
        self.bar_count = 0
        self.history_lengths = []
        self.is_started = True
        self.is_finished = False

    def on_bar(self, context: StrategyContext) -> Sequence[StrategyDecision]:
        self.bar_count += 1
        self.history_lengths.append(len(context.history()))

        # Emit an action every trigger_interval bars, otherwise return empty sequence []
        if self.bar_count % self.trigger_interval == 0:
            return [
                StrategyDecision(
                    action=OrderAction.ENTER_LONG,
                    tag=f"bar_{self.bar_count}",
                )
            ]
        return []

    def on_finish(self) -> None:
        self.is_finished = True


def test_stateful_strategy_retains_state(valid_ohlcv_df: pd.DataFrame):
    """Verifies that a stateful strategy retains state across consecutive on_bar calls."""
    strategy = CountingStrategy(trigger_interval=2)
    strategy.on_start()

    all_decisions = []
    for idx in range(len(valid_ohlcv_df)):
        ctx = StrategyContext(full_df=valid_ohlcv_df, current_idx=idx)
        decisions = strategy.on_bar(ctx)
        all_decisions.extend(decisions)

    assert strategy.bar_count == 5
    assert strategy.history_lengths == [1, 2, 3, 4, 5]
    # At interval=2 with 5 bars: triggers on bar 2 and bar 4
    assert len(all_decisions) == 2
    assert all_decisions[0].tag == "bar_2"
    assert all_decisions[1].tag == "bar_4"


def test_strategy_lifecycle_hooks(valid_ohlcv_df: pd.DataFrame):
    """Verifies that on_start and on_finish properly signal lifecycle transitions and reset state."""
    strategy = CountingStrategy()

    assert strategy.is_started is False
    assert strategy.is_finished is False

    strategy.on_start()
    assert strategy.is_started is True
    assert strategy.bar_count == 0

    for idx in range(len(valid_ohlcv_df)):
        ctx = StrategyContext(full_df=valid_ohlcv_df, current_idx=idx)
        strategy.on_bar(ctx)

    strategy.on_finish()
    assert strategy.is_finished is True
    assert strategy.bar_count == 5

    # Calling on_start again resets internal counters cleanly
    strategy.on_start()
    assert strategy.bar_count == 0
    assert strategy.history_lengths == []
    assert strategy.is_finished is False


def test_deterministic_replay_fresh_and_reset(valid_ohlcv_df: pd.DataFrame):
    """
    Verifies that strategy evaluation is strictly deterministic:
    - Two fresh instances produce identical decision sequences.
    - An instance re-run after on_start produces identical decision sequences.
    """
    def run_strategy(strat: Strategy) -> list[StrategyDecision]:
        strat.on_start()
        decisions_out = []
        for idx in range(len(valid_ohlcv_df)):
            ctx = StrategyContext(full_df=valid_ohlcv_df, current_idx=idx)
            decisions_out.extend(strat.on_bar(ctx))
        strat.on_finish()
        return decisions_out

    # Run 1: fresh instance A
    strat_a = CountingStrategy(trigger_interval=2)
    run_1_decisions = run_strategy(strat_a)

    # Run 2: fresh instance B
    strat_b = CountingStrategy(trigger_interval=2)
    run_2_decisions = run_strategy(strat_b)

    # Run 3: reuse instance A after reset
    run_3_decisions = run_strategy(strat_a)

    assert run_1_decisions == run_2_decisions
    assert run_1_decisions == run_3_decisions


def test_empty_decision_sequence_means_no_op(valid_ohlcv_df: pd.DataFrame):
    """Verifies that returning an empty list represents no action without error."""
    class PassiveStrategy(Strategy):
        def on_bar(self, context: StrategyContext) -> Sequence[StrategyDecision]:
            return []

    strat = PassiveStrategy()
    strat.on_start()

    ctx = StrategyContext(full_df=valid_ohlcv_df, current_idx=0)
    decisions = strat.on_bar(ctx)

    assert isinstance(decisions, Sequence)
    assert len(decisions) == 0
