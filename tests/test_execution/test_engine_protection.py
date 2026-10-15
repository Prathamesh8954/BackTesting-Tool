from src.execution import EngineConfig, run_backtest
from src.strategy.models import OrderAction, OrderType, StrategyDecision

from tests.test_execution.helpers import ScriptedStrategy, make_df


def _config(**overrides):
    base = dict(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)
    base.update(overrides)
    return EngineConfig(**base)


def _reasons(result):
    return [rejection.reason for rejection in result.rejections]


def test_long_stop_loss_touch_and_fill():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 95.0, 102.0),  # low 95 <= stop 95
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills[0].kind.value == "ENTRY"
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 95.0


def test_long_stop_loss_gap_fills_at_worse_open():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 96.0, 102.0),  # entry at 100, stop 95, no touch
        (90.0, 92.0, 88.0, 91.0),     # gap down through the stop
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 90.0  # min(open=90, stop=95)


def test_short_stop_loss_touch_uses_high():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 98.0, 100.0),  # entry short at 100, stop 110, high 105 < 110
        (108.0, 112.0, 107.0, 110.0), # high 112 >= 110 -> stop
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 110.0  # max(open=108, stop=110) = 110


def test_short_stop_loss_gap_fills_at_worse_open():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 98.0, 100.0),
        (120.0, 125.0, 119.0, 124.0),  # gap up through stop 110
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills[-1].price == 120.0  # max(open=120, stop=110)


def test_long_take_profit_fill_at_target_and_gap():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),   # entry 100, tp 110 not touched
        (102.0, 112.0, 101.0, 111.0),  # high 112 >= 110 -> target
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, take_profit=110.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 110.0


def test_long_take_profit_gap_fills_at_better_open():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
        (115.0, 118.0, 114.0, 116.0),  # open already through tp 110
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, take_profit=110.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills[-1].price == 115.0  # open better than target


def test_short_take_profit_touch_and_gap():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 100.0),   # entry short 100, tp 90
        (95.0, 96.0, 85.0, 88.0),      # low 85 <= 90 -> target 90
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0, take_profit=90.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 90.0


def test_stop_loss_processed_before_take_profit_when_both_touched():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),   # entry 100, stop 95, tp 110
        (102.0, 115.0, 90.0, 100.0),   # both touched in same candle
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0, take_profit=110.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 95.0


def test_protection_is_active_on_the_entry_candle():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 101.0, 90.0, 95.0),  # entry at open 100, low 90 hits stop 95 same candle
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert [f.kind.value for f in result.fills] == ["ENTRY", "STOP_LOSS"]
    assert result.fills[-1].bar_index == 1


def test_wrong_side_entry_stop_loss_rejected_at_fill():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=110.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["WRONG_SIDE_STOP_LOSS_ENTRY"]
    assert result.is_flat


def test_wrong_side_entry_take_profit_rejected_at_fill():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, take_profit=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["WRONG_SIDE_TAKE_PROFIT_ENTRY"]


def test_take_profit_equal_to_fill_rejected():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, take_profit=100.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["TAKE_PROFIT_EQUALS_FILL"]


def test_rejected_limit_entry_is_cancelled_permanently():
    df = make_df([
        (102.0, 103.0, 99.0, 102.0),
        (102.0, 103.0, 99.0, 101.0),  # touches limit 100, fill 100, wrong-side stop -> reject+cancel
        (101.0, 103.0, 98.0, 100.0),  # would touch again, but order is gone
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=110.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert len(result.rejections) == 1
    assert result.rejections[0].reason == "WRONG_SIDE_STOP_LOSS_ENTRY"
    assert result.rejections[0].bar_index == 1
    assert result.unfilled_orders == ()


def test_modification_applies_on_next_candle_using_request_close_mark():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 96.0, 103.0),   # entry 100, close 103 (the mark)
        (102.0, 103.0, 100.0, 101.0),  # modified stop 102 active -> touched
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=102.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.bar_index == 2
    assert exit_fill.price == 102.0


def test_rejected_modification_preserves_prior_stop():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 96.0, 103.0),   # entry 100, stop 90, close 103
        (100.0, 101.0, 85.0, 90.0),    # prior stop 90 retained -> touched
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=110.0)],  # wrong side vs mark 103
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "WRONG_SIDE_STOP_LOSS_MODIFICATION" in _reasons(result)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 90.0  # prior stop retained


def test_modification_is_per_field_stop_rejected_take_profit_applied():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),   # entry 100, stop 90, tp 130, close 103
        (100.0, 115.0, 99.0, 112.0),   # tp 110 applied -> hit
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, take_profit=130.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=105.0, take_profit=110.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "WRONG_SIDE_STOP_LOSS_MODIFICATION" in _reasons(result)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 110.0


def test_protection_modification_while_flat_is_rejected():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    script = {0: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert _reasons(result) == ["MODIFY_WHILE_FLAT"]
    assert result.fills == ()


def test_long_take_profit_modification_valid_against_entry_even_below_mark():
    # Entry 100 on bar 1; the mark (bar 1 close) is 103. A TP of 102 is below the
    # mark but above the entry fill, so the amended rule 4 accepts it.
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 96.0, 103.0),   # entry long at open 100, close 103 (mark)
        (102.0, 104.0, 101.0, 103.0),  # amended TP 102 active -> high 104 >= 102
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, take_profit=102.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "WRONG_SIDE_TAKE_PROFIT_MODIFICATION" not in _reasons(result)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 102.0


def test_long_take_profit_modification_wrong_side_of_entry_rejected():
    # Entry 100; a TP of 95 is below the entry fill, so rule 4 rejects it and the
    # prior take-profit (130) is retained.
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 105.0, 96.0, 103.0),   # entry long 100, tp 130, close 103
        (102.0, 131.0, 101.0, 130.0),  # prior tp 130 retained -> high 131 >= 130
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, take_profit=130.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, take_profit=95.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "WRONG_SIDE_TAKE_PROFIT_MODIFICATION" in _reasons(result)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 130.0  # prior TP retained


def test_short_take_profit_modification_valid_against_entry_even_above_mark():
    # Short entry 100 on bar 1; the mark (bar 1 close) is 97. A TP of 99 is above
    # the mark but below the entry fill, so the amended rule 4 accepts it.
    df = make_df([
        (100.0, 101.0, 98.0, 100.0),
        (100.0, 101.0, 96.0, 97.0),    # entry short at open 100, close 97 (mark)
        (98.0, 99.0, 95.0, 96.0),      # amended TP 99 active -> low 95 <= 99
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, take_profit=99.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "WRONG_SIDE_TAKE_PROFIT_MODIFICATION" not in _reasons(result)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 98.0  # open=98 is better than the 99 target


def test_short_take_profit_modification_wrong_side_of_entry_rejected():
    # Short entry 100; a TP of 105 is above the entry fill, so rule 4 rejects it
    # and the prior take-profit (90) is retained.
    df = make_df([
        (100.0, 101.0, 98.0, 100.0),
        (100.0, 101.0, 96.0, 97.0),    # entry short 100, tp 90, close 97
        (92.0, 93.0, 89.0, 90.0),      # prior tp 90 retained -> low 89 <= 90
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0, take_profit=90.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, take_profit=105.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "WRONG_SIDE_TAKE_PROFIT_MODIFICATION" in _reasons(result)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 90.0  # prior TP retained


# --- Symmetric (short) orientation coverage: rules 1, 3, 5, 6 ---------------


def test_short_wrong_side_entry_stop_loss_rejected_at_fill():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    # Short fills at 100; a stop at 90 sits on the wrong side (rule 1).
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=90.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["WRONG_SIDE_STOP_LOSS_ENTRY"]
    assert result.is_flat


def test_short_wrong_side_entry_take_profit_rejected_at_fill():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    # Short fills at 100; stop 120 is correct, but take-profit 110 is above the
    # fill -> wrong side (rule 3).
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=120.0, take_profit=110.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["WRONG_SIDE_TAKE_PROFIT_ENTRY"]


def test_short_take_profit_equal_to_fill_rejected():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 102.0),
    ])
    # Short fills at 100 with a take-profit exactly equal to the fill: neither a
    # strictly correct side nor a wrong side, so rule 5 rejects it.
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=120.0, take_profit=100.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["TAKE_PROFIT_EQUALS_FILL"]


def test_limit_entry_with_wrong_side_take_profit_rejected_then_cancelled():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (102.0, 104.0, 99.5, 101.0),  # open above the limit, low touches it -> fill at 100
    ])
    # Buy limit 100 fills, but take-profit 95 is below that fill (rule 3): the
    # entry is rejected at fill and the working order is cancelled (rule 6).
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=90.0, take_profit=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["WRONG_SIDE_TAKE_PROFIT_ENTRY"]
    assert result.rejections[0].bar_index == 1
    assert result.unfilled_orders == ()


def test_limit_entry_with_take_profit_equal_to_fill_rejected_then_cancelled():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (102.0, 104.0, 99.5, 101.0),
    ])
    # Buy limit 100 fills with take-profit exactly 100 -> rule 5 rejects it and
    # rule 6 cancels the order permanently.
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=90.0, take_profit=100.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["TAKE_PROFIT_EQUALS_FILL"]
    assert result.unfilled_orders == ()


def test_limit_entry_gapped_through_stop_rejected_then_cancelled():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (90.0, 92.0, 88.0, 91.0),  # opens below both the buy limit and the stop
    ])
    # A buy limit at 100 is gapped through and fills at the 90 open; the requested
    # stop 95 is now above that fill, so rule 1 rejects and rule 6 cancels it.
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert result.fills == ()
    assert _reasons(result) == ["WRONG_SIDE_STOP_LOSS_ENTRY"]
    assert result.unfilled_orders == ()


# --- Short protection modifications: rule 2 ----------------------------------


def test_short_stop_loss_modification_above_mark_applies_next_candle():
    df = make_df([
        (100.0, 101.0, 98.0, 100.0),
        (100.0, 101.0, 96.0, 97.0),   # short entry 100, close 97 (the mark)
        (98.0, 99.0, 95.0, 96.0),     # modified stop 98 (>= mark) active -> touched
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=98.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "WRONG_SIDE_STOP_LOSS_MODIFICATION" not in _reasons(result)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.bar_index == 2
    assert exit_fill.price == 98.0


def test_short_stop_loss_modification_below_mark_rejected_prior_stop_retained():
    df = make_df([
        (100.0, 101.0, 98.0, 100.0),
        (100.0, 101.0, 96.0, 97.0),    # short entry 100, close 97 (the mark)
        (98.0, 112.0, 95.0, 110.0),    # prior stop 110 retained -> high 112 >= 110
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)],
        1: [StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=96.0)],  # 96 < mark 97
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert "WRONG_SIDE_STOP_LOSS_MODIFICATION" in _reasons(result)
    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 110.0


# --- Entry-candle protection and short intrabar coverage: rules 7, 9, 10 -----


def test_limit_entry_protection_uses_full_entry_candle_range():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (101.0, 102.0, 94.0, 96.0),  # buy limit 100 fills mid-candle; low 94 also <= stop 95
    ])
    # Convention F1 (approved): entry-candle protection is evaluated against the
    # FULL candle high/low. OHLC data cannot reveal whether the 94 low occurred
    # before or after the limit fill at 100, so the whole candle is applied.
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=100.0, stop_loss=95.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert [f.kind.value for f in result.fills] == ["ENTRY", "STOP_LOSS"]
    assert result.fills[0].price == 100.0   # filled at the limit, not the open
    assert result.fills[-1].price == 95.0
    assert result.fills[0].bar_index == result.fills[-1].bar_index == 1


def test_short_stop_loss_processed_before_take_profit_when_both_touched():
    df = make_df([
        (100.0, 101.0, 98.0, 100.0),
        (100.0, 101.0, 96.0, 97.0),   # short entry 100, stop 110, tp 90
        (100.0, 115.0, 85.0, 100.0),  # both levels touched in the same candle
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0, take_profit=90.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "STOP_LOSS"
    assert exit_fill.price == 110.0  # max(open=100, stop=110)


def test_short_take_profit_gap_fills_at_better_open():
    df = make_df([
        (100.0, 101.0, 98.0, 100.0),
        (100.0, 101.0, 96.0, 97.0),   # short entry 100, tp 90
        (85.0, 88.0, 80.0, 86.0),     # open already below the 90 target
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0, take_profit=90.0)]}
    result = run_backtest(ScriptedStrategy(script), df, _config())

    exit_fill = result.fills[-1]
    assert exit_fill.kind.value == "TAKE_PROFIT"
    assert exit_fill.price == 85.0  # open is better than the target

