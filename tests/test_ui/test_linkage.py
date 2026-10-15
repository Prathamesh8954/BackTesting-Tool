"""Focused M8 tests: validated trade-to-fill linkage (``src.ui.workflow``).

Both hand-constructed records and real engine-generated results are used. Every
test asserts concrete expected values rather than merely checking for non-null.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from src.execution import EngineConfig, run_backtest
from src.execution.models import BacktestResult, Fill, FillKind, FillSide
from src.strategy.base import Strategy
from src.strategy.models import OrderAction, StrategyDecision
from src.ui.workflow import LinkedTrade, TradeFillLinkageError, link_trade_fills
from tests.test_execution.helpers import ScriptedStrategy, make_df
from tests.test_metrics.helpers import (
    do_nothing_result,
    make_result,
    make_trade,
    open_long_result,
    three_trade_result,
)


def _ts(index: int) -> pd.Timestamp:
    """Matches ``tests.test_metrics.helpers`` (``_ts`` / ``make_trade``)."""
    return pd.Timestamp("2026-01-01") + pd.Timedelta(hours=index)


def _bar_ts(index: int) -> pd.Timestamp:
    """Matches ``make_df``'s default clock (09:30, hourly) for engine output."""
    return pd.Timestamp("2026-01-01 09:30") + pd.Timedelta(hours=index)


def _config(**overrides) -> EngineConfig:
    kwargs = {
        "initial_capital": 100_000.0,
        "risk_absolute": 1000.0,
        "quantity_step": 1.0,
    }
    kwargs.update(overrides)
    return EngineConfig(**kwargs)


def _valid_result() -> BacktestResult:
    """Hand-built result: one long trade (qty 1, 100 -> 103) with paired fills.

    ``make_trade`` sets ``gross = net + entry_commission + exit_commission``, so
    with 0.5 commissions a net of 2.0 gives a gross of 3.0, which is exactly
    ``1 * (103 - 100)``. The record therefore satisfies the engine's accounting.
    """
    trade = make_trade(
        2.0,
        quantity=1.0,
        entry_price=100.0,
        exit_price=103.0,
        entry_commission=0.5,
        exit_commission=0.5,
        tag="entry_tag",
    )
    entry_fill = Fill(
        kind=FillKind.ENTRY,
        side=FillSide.BUY,
        direction="LONG",
        quantity=1.0,
        price=100.0,
        commission=0.5,
        slippage=0.0,
        bar_index=0,
        timestamp=_ts(0),
        tag="entry_tag",
    )
    closing_fill = Fill(
        kind=FillKind.EXIT,
        side=FillSide.SELL,
        direction="LONG",
        quantity=1.0,
        price=103.0,
        commission=0.5,
        slippage=0.0,
        bar_index=1,
        timestamp=_ts(1),
        tag="entry_tag",
    )
    return dataclasses.replace(make_result([trade]), fills=(entry_fill, closing_fill))


def _with_fill(result: BacktestResult, which: str, **changes) -> BacktestResult:
    """Returns ``result`` with one of its two fills altered via ``replace``."""
    fills = list(result.fills)
    fills[0 if which == "entry" else 1] = dataclasses.replace(
        fills[0 if which == "entry" else 1], **changes
    )
    return dataclasses.replace(result, fills=tuple(fills))


# ---------------------------------------------------------------------------
# Empty and open-position edge cases
# ---------------------------------------------------------------------------


def test_link_returns_empty_tuple_when_there_are_no_trades_or_fills():
    assert link_trade_fills(do_nothing_result()) == ()
    assert link_trade_fills(make_result()) == ()


def test_link_open_position_with_trailing_entry_yields_no_pairs():
    result = open_long_result()

    # One unmatched ENTRY fill, zero completed trades, position left open.
    assert result.is_flat is False
    assert [fill.kind for fill in result.fills] == [FillKind.ENTRY]
    assert result.trades == ()

    assert link_trade_fills(result) == ()


# ---------------------------------------------------------------------------
# Multiple sequential trades (real engine output)
# ---------------------------------------------------------------------------


def test_link_pairs_three_sequential_trades_in_stream_order():
    result = three_trade_result()
    linked = link_trade_fills(result)

    assert len(linked) == 3
    assert [item.index for item in linked] == [0, 1, 2]
    for item in linked:
        k = item.index
        assert isinstance(item, LinkedTrade)
        assert item.trade is result.trades[k]
        assert item.entry_fill is result.fills[2 * k]
        assert item.exit_fill is result.fills[2 * k + 1]


def test_link_matches_hand_computed_engine_fills_field_by_field():
    result = three_trade_result()

    # Quantity: risk 1000 / 10.0 stop distance = 100 units, zero commission.
    expected_fills = [
        ("ENTRY", "BUY", "LONG", 100.0, 100.0, 1, _bar_ts(1)),
        ("EXIT", "SELL", "LONG", 100.0, 110.0, 2, _bar_ts(2)),
        ("ENTRY", "SELL", "SHORT", 100.0, 100.0, 3, _bar_ts(3)),
        ("EXIT", "BUY", "SHORT", 100.0, 120.0, 4, _bar_ts(4)),
        ("ENTRY", "BUY", "LONG", 100.0, 100.0, 5, _bar_ts(5)),
        ("EXIT", "SELL", "LONG", 100.0, 90.0, 6, _bar_ts(6)),
    ]
    actual_fills = [
        (
            fill.kind.value,
            fill.side.value,
            fill.direction,
            fill.quantity,
            fill.price,
            fill.bar_index,
            fill.timestamp,
        )
        for fill in result.fills
    ]
    assert actual_fills == expected_fills

    assert [
        (trade.entry_bar_index, trade.exit_bar_index) for trade in result.trades
    ] == [(1, 2), (3, 4), (5, 6)]
    assert [trade.gross_pnl for trade in result.trades] == [1000.0, -2000.0, -1000.0]
    assert [trade.net_pnl for trade in result.trades] == [1000.0, -2000.0, -1000.0]
    assert [trade.tag for trade in result.trades] == ["", "", ""]

    # Linkage reproduces exactly those pairs.
    linked = link_trade_fills(result)
    assert [(item.entry_fill.bar_index, item.exit_fill.bar_index) for item in linked] == [
        (1, 2),
        (3, 4),
        (5, 6),
    ]
    assert [item.trade.net_pnl for item in linked] == [1000.0, -2000.0, -1000.0]


# ---------------------------------------------------------------------------
# Same-bar round trips (timestamps collide, so timestamp joins are invalid)
# ---------------------------------------------------------------------------


def test_link_same_bar_round_trip_is_paired_positionally_not_by_timestamp():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),  # bar 0: signal only
        (100.0, 101.0, 90.0, 95.0),   # bar 1: entry @100, low 90 hits stop 98
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=98.0, tag="sl_entry")]
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    # Both fills share bar 1 and its timestamp: timestamps are not unique keys.
    assert [fill.kind for fill in result.fills] == [FillKind.ENTRY, FillKind.STOP_LOSS]
    assert len({fill.timestamp for fill in result.fills}) == 1
    assert result.fills[0].timestamp == result.fills[1].timestamp

    linked = link_trade_fills(result)
    assert len(linked) == 1
    item = linked[0]
    assert item.entry_fill is result.fills[0]
    assert item.exit_fill is result.fills[1]
    assert (item.trade.entry_bar_index, item.trade.exit_bar_index) == (1, 1)
    assert (item.trade.entry_price, item.trade.exit_price) == (100.0, 98.0)
    assert item.trade.quantity == 500.0
    assert item.trade.gross_pnl == -1000.0
    assert item.trade.net_pnl == -1000.0
    # A protection close inherits the position tag, so it must agree.
    assert item.trade.tag == item.entry_fill.tag == item.exit_fill.tag == "sl_entry"


# ---------------------------------------------------------------------------
# Tags are not join keys
# ---------------------------------------------------------------------------


def test_link_does_not_join_on_tags_when_entry_and_exit_tags_differ():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),  # 0: signal
        (100.0, 108.0, 95.0, 105.0),  # 1: entry, tag E1
        (110.0, 112.0, 109.0, 111.0),  # 2: exit, tag X1
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, tag="E1")],
        1: [StrategyDecision(action=OrderAction.EXIT, tag="X1")],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    linked = link_trade_fills(result)
    assert len(linked) == 1
    item = linked[0]

    assert item.entry_fill.tag == "E1"
    assert item.exit_fill.tag == "X1"
    assert item.trade.tag == "E1"
    # A naive tag join would fail here; positional pairing does not.
    assert item.trade.tag != item.exit_fill.tag
    assert [fill.tag for fill in result.fills] != [trade.tag for trade in result.trades]
    assert item.exit_fill is result.fills[1]
    assert (item.trade.entry_price, item.trade.exit_price) == (100.0, 110.0)


# ---------------------------------------------------------------------------
# Rejections and reversal attempts
# ---------------------------------------------------------------------------


def test_link_rejected_entry_between_trades_does_not_shift_pairing():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),   # 0: signal
        (100.0, 108.0, 95.0, 105.0),   # 1: trade A entry @100
        (110.0, 112.0, 109.0, 111.0),  # 2: trade A exit @110
        (100.0, 105.0, 95.0, 100.0),   # 3: entry attempt, stop 110 is wrong-side
        (100.0, 108.0, 95.0, 105.0),   # 4: trade B entry @100
        (110.0, 112.0, 109.0, 111.0),  # 5: trade B exit @110
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
        2: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=110.0)],
        3: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        4: [StrategyDecision(action=OrderAction.EXIT)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    # A rejected entry produces no fill, so the stream stays even-length.
    assert result.is_flat is True
    assert len(result.fills) == 4
    assert len(result.trades) == 2
    assert [(rej.reason, rej.bar_index) for rej in result.rejections] == [
        ("WRONG_SIDE_STOP_LOSS_ENTRY", 3)
    ]

    linked = link_trade_fills(result)
    assert [(item.trade.entry_bar_index, item.trade.exit_bar_index) for item in linked] == [
        (1, 2),
        (4, 5),
    ]
    assert [item.entry_fill.bar_index for item in linked] == [1, 4]
    assert [item.exit_fill.bar_index for item in linked] == [2, 5]
    # The rejection inserted no fill: trade B still pairs with stream slots 2/3.
    assert linked[1].entry_fill is result.fills[2]
    assert linked[1].exit_fill is result.fills[3]
    assert [item.trade.net_pnl for item in linked] == [1000.0, 1000.0]


def test_link_reversal_attempt_adds_no_pairs_and_no_fills():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),
        (100.0, 108.0, 95.0, 105.0),   # bar 1: long entry @100
        (105.0, 107.0, 103.0, 106.0),  # bar 2: ENTER_SHORT while long
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        2: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=120.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    assert [(rej.reason, rej.bar_index) for rej in result.rejections] == [
        ("ENTRY_WHILE_OPEN", 2)
    ]
    assert [fill.kind for fill in result.fills] == [FillKind.ENTRY]
    assert result.trades == ()
    assert result.is_flat is False
    assert link_trade_fills(result) == ()


def test_link_engine_open_position_after_completed_trade_satisfies_2n_plus_1():
    """One completed trade + a reopened position left open: fills = 2*1 + 1.

    The helper must return exactly the completed association, validate the
    trailing ENTRY fill, and fabricate no trade for the open position.
    """
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),   # 0: signal
        (100.0, 108.0, 95.0, 105.0),   # 1: trade A entry @100
        (110.0, 112.0, 109.0, 111.0),  # 2: trade A exit @110, then re-entry signal
        (100.0, 108.0, 95.0, 105.0),   # 3: trade B entry @100, held open to the end
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
        2: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    # 2N + 1 with N = 1: three fills, one trade, position still open.
    assert [fill.kind for fill in result.fills] == [
        FillKind.ENTRY,
        FillKind.EXIT,
        FillKind.ENTRY,
    ]
    assert len(result.trades) == 1
    assert result.is_flat is False
    assert (result.open_direction, result.open_quantity) == ("LONG", 100.0)

    linked = link_trade_fills(result)
    assert len(linked) == 1
    item = linked[0]
    assert item.index == 0
    assert item.trade is result.trades[0]
    assert item.entry_fill is result.fills[0]
    assert item.exit_fill is result.fills[1]

    # The completed association reproduces the hand-computed engine record.
    assert (item.trade.entry_bar_index, item.trade.exit_bar_index) == (1, 2)
    assert (item.trade.entry_price, item.trade.exit_price) == (100.0, 110.0)
    assert item.trade.quantity == 100.0
    assert item.trade.gross_pnl == 1000.0
    assert item.trade.net_pnl == 1000.0

    # The trailing ENTRY (bar 3) was validated as the unmatched open-position
    # entry and is not associated with any trade: no association is fabricated.
    trailing = result.fills[2]
    assert trailing.bar_index == 3
    assert trailing is not item.entry_fill
    assert trailing is not item.exit_fill
    assert trailing.bar_index not in (
        item.trade.entry_bar_index,
        item.trade.exit_bar_index,
    )


# ---------------------------------------------------------------------------
# Synthetic records without fills
# ---------------------------------------------------------------------------


def test_link_reports_linkage_unavailable_for_trades_without_fills():
    result = make_result([make_trade(100.0)])
    assert result.fills == ()
    assert len(result.trades) == 1

    with pytest.raises(TradeFillLinkageError, match="Linkage unavailable"):
        link_trade_fills(result)


# ---------------------------------------------------------------------------
# Field-by-field validation
# ---------------------------------------------------------------------------

_TRADE_MUTATIONS = [
    pytest.param("direction", "SHORT", "direction", id="trade_direction"),
    pytest.param("quantity", 2.0, "quantity", id="trade_quantity"),
    pytest.param("entry_price", 99.0, "entry price", id="trade_entry_price"),
    pytest.param("exit_price", 104.0, "exit price", id="trade_exit_price"),
    pytest.param("entry_bar_index", 1, "entry bar index", id="trade_entry_bar"),
    pytest.param("exit_bar_index", 0, "exit bar index", id="trade_exit_bar"),
    pytest.param("entry_timestamp", _ts(5), "entry timestamp", id="trade_entry_ts"),
    pytest.param("exit_timestamp", _ts(5), "exit timestamp", id="trade_exit_ts"),
    pytest.param("entry_kind", FillKind.EXIT, "entry kind", id="trade_entry_kind"),
    pytest.param(
        "exit_kind", FillKind.TAKE_PROFIT, "exit kind", id="trade_exit_kind"
    ),
    pytest.param(
        "entry_commission", 9.0, "entry commission", id="trade_entry_commission"
    ),
    pytest.param(
        "exit_commission", 9.0, "exit commission", id="trade_exit_commission"
    ),
    pytest.param("tag", "other_tag", "tag", id="trade_tag"),
    pytest.param("gross_pnl", 999.0, "gross P&L", id="trade_gross_pnl"),
    pytest.param("net_pnl", 999.0, "net P&L", id="trade_net_pnl"),
]

_FILL_MUTATIONS = [
    pytest.param("entry", {"price": 99.5}, "entry price", id="fill_entry_price"),
    pytest.param("exit", {"price": 102.5}, "exit price", id="fill_exit_price"),
    pytest.param(
        "entry", {"bar_index": 4}, "entry bar index", id="fill_entry_bar"
    ),
    pytest.param(
        "exit", {"bar_index": 7}, "exit bar index", id="fill_exit_bar"
    ),
    pytest.param(
        "entry", {"timestamp": _ts(9)}, "entry timestamp", id="fill_entry_ts"
    ),
    pytest.param(
        "exit", {"timestamp": _ts(9)}, "exit timestamp", id="fill_exit_ts"
    ),
    pytest.param(
        "entry", {"quantity": 3.0}, "entry quantity", id="fill_entry_quantity"
    ),
    pytest.param(
        "exit", {"quantity": 3.0}, "exit quantity", id="fill_exit_quantity"
    ),
    pytest.param(
        "entry", {"commission": 7.0}, "entry commission", id="fill_entry_commission"
    ),
    pytest.param(
        "exit", {"commission": 7.0}, "exit commission", id="fill_exit_commission"
    ),
    pytest.param(
        "entry", {"direction": "SHORT"}, "entry direction", id="fill_entry_direction"
    ),
    pytest.param("entry", {"tag": "other"}, "entry tag", id="fill_entry_tag"),
]


@pytest.mark.parametrize(("field", "value", "expected"), _TRADE_MUTATIONS)
def test_link_validates_each_trade_field(field, value, expected):
    result = _valid_result()
    assert link_trade_fills(result)  # precondition: the baseline links cleanly

    mutated = dataclasses.replace(
        result, trades=(dataclasses.replace(result.trades[0], **{field: value}),)
    )
    with pytest.raises(TradeFillLinkageError, match=expected):
        link_trade_fills(mutated)


@pytest.mark.parametrize(("which", "changes", "expected"), _FILL_MUTATIONS)
def test_link_validates_each_fill_field(which, changes, expected):
    result = _valid_result()
    assert link_trade_fills(result)

    with pytest.raises(TradeFillLinkageError, match=expected):
        link_trade_fills(_with_fill(result, which, **changes))


def test_link_validates_exit_kind_of_a_protection_close():
    """A stop-loss close must pair with a trade recorded as STOP_LOSS."""
    result = _valid_result()
    closing = dataclasses.replace(result.fills[1], kind=FillKind.STOP_LOSS)
    # The trade still says EXIT, so the pair no longer agrees.
    with pytest.raises(TradeFillLinkageError, match="exit kind"):
        link_trade_fills(dataclasses.replace(result, fills=(result.fills[0], closing)))


def test_link_documents_unvalidated_fill_fields_without_a_trade_counterpart():
    """``side`` and ``slippage`` exist on Fill only; they do not affect pairing."""
    mutated = _with_fill(_valid_result(), "entry", side=FillSide.SELL, slippage=123.45)
    linked = link_trade_fills(mutated)

    assert len(linked) == 1
    assert linked[0].entry_fill.slippage == 123.45
    assert linked[0].entry_fill.side is FillSide.SELL


# ---------------------------------------------------------------------------
# Malformed fill streams
# ---------------------------------------------------------------------------


def test_link_rejects_missing_or_extra_fills():
    base = _valid_result()

    # Missing the closing fill of the only trade.
    with pytest.raises(TradeFillLinkageError, match="Malformed fill stream"):
        link_trade_fills(dataclasses.replace(base, fills=base.fills[:1]))

    # One trailing ENTRY too many while the result claims to be flat.
    with pytest.raises(TradeFillLinkageError, match="Malformed fill stream"):
        link_trade_fills(dataclasses.replace(base, fills=base.fills + base.fills[:1]))

    # Fills recorded against a result with no trades at all.
    empty = make_result()
    with pytest.raises(TradeFillLinkageError, match="Malformed fill stream"):
        link_trade_fills(dataclasses.replace(empty, fills=base.fills))


def test_link_rejects_out_of_order_fill_streams():
    base = _valid_result()
    entry, closing = base.fills

    # Closing fill first.
    with pytest.raises(TradeFillLinkageError, match="Out-of-order fill stream"):
        link_trade_fills(dataclasses.replace(base, fills=(closing, entry)))

    # Two entry fills in a row: the second is not a closing fill.
    with pytest.raises(TradeFillLinkageError, match="Out-of-order fill stream"):
        link_trade_fills(dataclasses.replace(base, fills=(entry, entry)))


def test_link_open_position_requires_exactly_one_trailing_entry():
    base = _valid_result()

    # Declared open but the trailing ENTRY fill is absent.
    with pytest.raises(TradeFillLinkageError, match="Malformed fill stream"):
        link_trade_fills(dataclasses.replace(base, is_flat=False))

    # Declared open with a trailing *closing* fill instead of an ENTRY.
    with pytest.raises(TradeFillLinkageError, match="trailing"):
        link_trade_fills(
            dataclasses.replace(base, is_flat=False, fills=base.fills + (base.fills[1],))
        )

    # Correct shape for an open position: two paired fills plus one trailing ENTRY.
    linked = link_trade_fills(
        dataclasses.replace(base, is_flat=False, fills=base.fills + (base.fills[0],))
    )
    assert len(linked) == 1


# ---------------------------------------------------------------------------
# Purity: no mutation, no rerun, deterministic
# ---------------------------------------------------------------------------


class _CountingStrategy(Strategy):
    """Scripted strategy that records how often the engine invoked it."""

    def __init__(self, script):
        self._script = script
        self.calls = 0

    def on_bar(self, context):
        self.calls += 1
        return list(self._script.get(context.current_index, []))


def test_link_is_deterministic_non_mutating_and_never_reruns_the_run():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),
        (100.0, 108.0, 95.0, 105.0),
        (110.0, 112.0, 109.0, 111.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
    }
    strategy = _CountingStrategy(script)
    result = run_backtest(strategy, df, _config())
    calls_after_run = strategy.calls

    fills_before = result.fills
    trades_before = result.trades
    fills_snapshot = tuple(result.fills)
    trades_snapshot = tuple(result.trades)

    first = link_trade_fills(result)
    second = link_trade_fills(result)

    # The helper never invoked the strategy again (once per bar, 3 bars).
    assert strategy.calls == calls_after_run
    assert calls_after_run == 3

    # Inputs are untouched: same tuple objects, same contents.
    assert result.fills is fills_before
    assert result.trades is trades_before
    assert result.fills == fills_snapshot
    assert result.trades == trades_snapshot

    # Deterministic: equal output on repeated calls, sharing the same records.
    assert isinstance(first, tuple)
    assert first == second
    assert all(isinstance(item, LinkedTrade) for item in first)
    assert len(first) == 1
    assert first[0].entry_fill is result.fills[0]
    assert first[0].exit_fill is result.fills[1]
    assert first[0].trade is result.trades[0]
