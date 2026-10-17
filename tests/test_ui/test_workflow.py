import pandas as pd
import pytest

from src.execution import EngineConfig, run_backtest
from src.metrics import MetricsConsistencyError
from src.strategy.base import Strategy
from src.strategy.models import OrderAction, StrategyDecision
from src.ui import workflow
from tests.test_execution.helpers import ScriptedStrategy, make_df
from tests.test_metrics.helpers import (
    do_nothing_result,
    make_result,
    make_trade,
    open_long_result,
    three_trade_result,
)


def _write_csv(path, df: pd.DataFrame) -> None:
    df.to_csv(path, index=False)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01 09:30", periods=5, freq="1h"),
            "open": [100.0, 102.0, 101.5, 103.0, 104.0],
            "high": [103.0, 104.5, 103.0, 105.0, 106.0],
            "low": [99.5, 101.0, 100.0, 102.5, 103.5],
            "close": [102.0, 101.5, 103.0, 104.0, 105.5],
            "volume": [1000.0, 1500.0, 1200.0, 1800.0, 2000.0],
        }
    )


def test_list_data_files_filters_supported_extensions(tmp_path):
    _write_csv(tmp_path / "b_symbol.csv", pd.DataFrame({"a": [1]}))
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / ".gitkeep").write_text("")
    df = pd.DataFrame({"a": [1]})
    df.to_parquet(tmp_path / "a_symbol.parquet")

    files = workflow.list_data_files(tmp_path)
    assert [path.name for path in files] == ["a_symbol.parquet", "b_symbol.csv"]


def test_list_data_files_missing_directory_returns_empty(tmp_path):
    assert workflow.list_data_files(tmp_path / "does_not_exist") == []


def test_inspect_dataset_valid(sample_df, tmp_path):
    path = tmp_path / "valid.csv"
    _write_csv(path, sample_df)

    state = workflow.inspect_dataset(path)

    assert state.is_loaded
    assert state.is_valid
    assert state.row_count == 5
    assert "close" in state.columns
    assert state.start_timestamp == sample_df["timestamp"].iloc[0]
    assert state.end_timestamp == sample_df["timestamp"].iloc[-1]


def test_inspect_dataset_reports_invalid_columns(tmp_path):
    path = tmp_path / "missing.csv"
    pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=3), "close": [1.0, 2.0, 3.0]}).to_csv(path, index=False)

    state = workflow.inspect_dataset(path)

    assert state.is_loaded
    assert not state.is_valid
    codes = {issue.code for issue in state.report.errors}
    assert "MISSING_COLUMNS" in codes


def test_inspect_dataset_reports_load_error(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")  # loader raises on empty files

    state = workflow.inspect_dataset(path)

    assert not state.is_loaded
    assert state.load_error is not None
    assert state.load_error_detail


def test_save_uploaded_bytes_roundtrip(sample_df):
    data = sample_df.to_csv(index=False).encode("utf-8")
    path = workflow.save_uploaded_bytes(data, "uploaded.csv")
    try:
        state = workflow.inspect_dataset(path, source_label="uploaded.csv")
        assert state.is_valid
        assert state.source_label == "uploaded.csv"
    finally:
        path.unlink(missing_ok=True)


def test_save_uploaded_bytes_rejects_unsupported_type():
    with pytest.raises(ValueError, match="Unsupported file type"):
        workflow.save_uploaded_bytes(b"data", "values.xlsx")


def test_build_strategy_from_code_class():
    code = (
        "class MyStrategy(Strategy):\n"
        "    def on_bar(self, context):\n"
        "        return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=1.0)]\n"
    )
    instance = workflow.build_strategy_from_code(code)
    assert isinstance(instance, Strategy)


def test_build_strategy_from_code_module_instance():
    code = (
        "class MyStrategy(Strategy):\n"
        "    def on_bar(self, context):\n"
        "        return []\n"
        "strategy = MyStrategy()\n"
    )
    instance = workflow.build_strategy_from_code(code)
    assert isinstance(instance, Strategy)


def test_build_strategy_from_code_class_name_selection():
    code = (
        "class Alpha(Strategy):\n"
        "    def on_bar(self, context):\n"
        "        return []\n"
        "class Beta(Strategy):\n"
        "    def on_bar(self, context):\n"
        "        return []\n"
    )
    assert isinstance(workflow.build_strategy_from_code(code, "Beta"), Strategy)


def test_build_strategy_from_code_multiple_classes_requires_selection():
    code = (
        "class Alpha(Strategy):\n"
        "    def on_bar(self, context):\n"
        "        return []\n"
        "class Beta(Strategy):\n"
        "    def on_bar(self, context):\n"
        "        return []\n"
    )
    with pytest.raises(workflow.StrategyCodeError, match="Multiple Strategy subclasses"):
        workflow.build_strategy_from_code(code)


def test_build_strategy_from_code_errors():
    with pytest.raises(workflow.StrategyCodeError, match="No strategy code"):
        workflow.build_strategy_from_code("   ")
    with pytest.raises(workflow.StrategyCodeError, match="could not be loaded"):
        workflow.build_strategy_from_code("class Broken(Strategy)")  # syntax error
    with pytest.raises(workflow.StrategyCodeError, match="No Strategy subclass"):
        workflow.build_strategy_from_code("x = 1")
    with pytest.raises(workflow.StrategyCodeError, match="named 'Gamma'"):
        workflow.build_strategy_from_code(
            "class Alpha(Strategy):\n    def on_bar(self, context):\n        return []\n",
            "Gamma",
        )


def test_run_result_dataframe_builders():
    df = make_df([
        (100.0, 103.0, 99.0, 102.0),
        (100.0, 104.0, 98.0, 103.0),
        (103.0, 106.0, 102.0, 105.0),
        (103.0, 104.0, 99.0, 100.0),
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=95.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
        2: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=110.0)],  # wrong side at fill
    }
    result = run_backtest(
        ScriptedStrategy(script), df, EngineConfig(initial_capital=100_000.0, risk_absolute=1000.0, quantity_step=1.0)
    )

    fills = workflow.fills_to_dataframe(result)
    assert list(fills.columns) == [
        "bar", "timestamp", "kind", "side", "direction", "quantity",
        "price", "commission", "slippage", "tag",
    ]
    assert len(fills) == 2

    trades = workflow.trades_to_dataframe(result)
    assert list(trades.columns)[0] == "direction"
    assert len(trades) == 1

    rejections = workflow.rejections_to_dataframe(result)
    assert "reason" in rejections.columns

    equity = workflow.equity_to_dataframe(result)
    assert list(equity.columns) == ["equity", "cash"]
    assert len(equity) == len(df)

    summary = dict(workflow.result_summary(result))
    assert "Final equity" in summary
    assert summary["Completed trades"] == "1"


# ------------------------------------------------------------------ Milestone 7
# Display-only tests for the performance panel and the drawdown chart. Every
# expected string below is hand-computed from the fixture's known trades and
# equity path, not copied from the implementation.


def test_accounting_summary_labels_unchanged_by_m7():
    """D1: the M7 panel supplements the accounting summary; it must not alter it."""
    labels = [label for label, _ in workflow.result_summary(three_trade_result())]
    assert labels == [
        "Initial capital",
        "Final equity",
        "Total P&L",
        "Total return",
        "Realized P&L",
        "Unrealized P&L",
        "Completed trades",
        "Winning / losing",
        "Fills",
        "Rejections",
        "Open position",
    ]


def test_performance_summary_formats_report_fields():
    """Hand-computed M4 values, formatted for the M7 panel.

    Fixture: long win +1000, short loss -2000, long loss -1000; equity path
    [100000, 100500, 101000, 101000, 99000, 99500, 98000].
    """
    summary = dict(workflow.performance_summary(three_trade_result()))

    assert summary["Closed trades"] == "3"
    assert summary["Winning trades"] == "1"
    assert summary["Losing trades"] == "2"
    assert summary["Breakeven trades"] == "0"
    assert summary["Win rate"] == "33.33%"
    assert summary["All trades winning"] == "No"
    assert summary["Gross realized P&L"] == "-2,000.00"
    assert summary["Net realized P&L"] == "-2,000.00"
    assert summary["Total P&L"] == "-2,000.00"
    assert summary["Total return"] == "-2.00%"
    assert summary["Average winning trade"] == "1,000.00"
    assert summary["Average losing trade"] == "-1,500.00"
    assert summary["Expectancy per trade"] == "-666.67"
    assert summary["Profit factor"] == "0.33"
    assert summary["Average bars held"] == "1.00"

    # Max drawdown: peak 101000 at bar 3, trough 98000 at bar 6 (3000 / 101000).
    assert summary["Max drawdown"] == "3,000.00"
    assert summary["Max drawdown %"] == "2.97%"
    assert summary["Max drawdown currency peak bar"] == "3"
    assert summary["Max drawdown currency trough bar"] == "6"
    assert summary["Max drawdown % peak bar"] == "3"
    assert summary["Max drawdown % trough bar"] == "6"

    assert summary["Open position"] == "None"
    assert summary["Reconciliation difference"] == "0.00"
    # Flat run: the open-position detail rows are not applicable and are absent.
    assert [label for label in summary if label.startswith("Open ")] == ["Open position"]


def test_performance_summary_renders_undefined_metrics_as_na():
    """D2: undefined (None) metrics render as 'n/a', never as a substituted zero."""
    summary = dict(workflow.performance_summary(do_nothing_result()))

    assert summary["Closed trades"] == "0"
    assert summary["Win rate"] == "n/a"
    assert summary["Expectancy per trade"] == "n/a"
    assert summary["Average winning trade"] == "n/a"
    assert summary["Average losing trade"] == "n/a"
    assert summary["Profit factor"] == "n/a"
    assert summary["Average bars held"] == "n/a"
    assert summary["All trades winning"] == "No"
    # Sanity: the undefined rendering is distinct from any zero-like value.
    assert summary["Win rate"] != "0.00%"
    # Counts remain zero (M4 additive-total policy) rather than "n/a".
    assert summary["Winning trades"] == "0"
    assert summary["Losing trades"] == "0"
    assert summary["Breakeven trades"] == "0"


def test_performance_summary_includes_open_position_details():
    """Open position: LONG x100 filled at bar 1 @ 100.00 with 5.00 commission.

    Final equity 100795 (cash 89995 + 100 x 108), so total P&L is +795 while
    gross unrealized P&L is +800; the F3 difference is the -5.00 entry
    commission. The equity path only rises, so drawdown is zero and the
    peak/trough bar indices are undefined.
    """
    summary = dict(workflow.performance_summary(open_long_result()))

    assert summary["Open position"] == "LONG x100"
    assert summary["Open unrealized P&L (gross)"] == "800.00"
    assert summary["Open entry price"] == "100.00"
    assert summary["Open entry bar"] == "1"
    assert summary["Open entry commission"] == "5.00"
    assert summary["Open mark price"] == "108.00"
    assert summary["Reconciliation difference"] == "-5.00"
    assert summary["Closed trades"] == "0"
    assert summary["Win rate"] == "n/a"
    assert summary["Profit factor"] == "n/a"
    assert summary["Max drawdown"] == "0.00"
    assert summary["Max drawdown %"] == "0.00%"
    assert summary["Max drawdown currency peak bar"] == "n/a"
    assert summary["Max drawdown currency trough bar"] == "n/a"


def test_performance_summary_propagates_metrics_consistency_error():
    """The panel must surface a consistency failure, not swallow it."""
    inconsistent = make_result([make_trade(-100.0)], realized_pnl=-999.0)

    with pytest.raises(MetricsConsistencyError):
        workflow.performance_summary(inconsistent)


def test_drawdown_to_dataframe_matches_m5_series():
    result = three_trade_result()
    frame = workflow.drawdown_to_dataframe(result)

    assert list(frame.columns) == ["decline_pct", "decline_currency"]
    assert frame.index.name == "timestamp"
    assert len(frame) == len(result.equity_curve)

    # Hand-computed from the equity path: peak 101000 (bars 2-3), then
    # declines of 2000 / 1500 / 3000 on bars 4 / 5 / 6.
    assert list(frame["decline_currency"]) == pytest.approx(
        [0.0, 0.0, 0.0, 0.0, 2000.0, 1500.0, 3000.0]
    )
    assert list(frame["decline_pct"]) == pytest.approx(
        [0.0, 0.0, 0.0, 0.0, 1.9801980198019802, 1.4851485148514852, 2.9702970297029703]
    )

    # The chart's worst point must equal the panel's maximum-drawdown figures.
    summary = dict(workflow.performance_summary(result))
    assert summary["Max drawdown"] == f"{frame['decline_currency'].max():,.2f}"
    assert summary["Max drawdown %"] == f"{frame['decline_pct'].max():,.2f}%"


def test_drawdown_to_dataframe_empty_equity_curve():
    empty = make_result([], equity_prices=())

    frame = workflow.drawdown_to_dataframe(empty)
    assert frame.empty

    summary = dict(workflow.performance_summary(empty))
    assert summary["Closed trades"] == "0"
    assert summary["Max drawdown"] == "0.00"


# ---------------------------------------------------------------------------
# Milestone 9: trade-to-fill audit trail (pure DataFrame helpers)
# ---------------------------------------------------------------------------


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


def test_linked_trades_to_dataframe_pairs_each_trade_with_its_validated_fills():
    result = three_trade_result()
    frame = workflow.linked_trades_to_dataframe(result)

    assert list(frame.columns) == [
        "trade",
        "direction",
        "quantity",
        "entry_fill_bar",
        "entry_fill_timestamp",
        "entry_fill_price",
        "entry_fill_commission",
        "entry_fill_tag",
        "exit_fill_kind",
        "exit_fill_bar",
        "exit_fill_timestamp",
        "exit_fill_price",
        "exit_fill_commission",
        "exit_fill_tag",
        "gross_pnl",
        "net_pnl",
    ]
    assert len(frame) == 3

    # Every cell must match the paired source records exactly (M8's positional
    # linkage), not a re-derived value.
    for k in range(3):
        row = frame.iloc[k]
        trade = result.trades[k]
        entry = result.fills[2 * k]
        closing = result.fills[2 * k + 1]
        assert row["trade"] == k
        assert row["direction"] == trade.direction == entry.direction
        assert row["quantity"] == trade.quantity
        assert row["entry_fill_bar"] == entry.bar_index == trade.entry_bar_index
        assert row["entry_fill_timestamp"] == entry.timestamp == trade.entry_timestamp
        assert row["entry_fill_price"] == entry.price == trade.entry_price
        assert row["entry_fill_commission"] == entry.commission == trade.entry_commission
        assert row["entry_fill_tag"] == entry.tag == trade.tag
        assert row["exit_fill_kind"] == closing.kind.value == trade.exit_kind.value
        assert row["exit_fill_bar"] == closing.bar_index == trade.exit_bar_index
        assert row["exit_fill_timestamp"] == closing.timestamp == trade.exit_timestamp
        assert row["exit_fill_price"] == closing.price == trade.exit_price
        assert row["exit_fill_commission"] == closing.commission == trade.exit_commission
        assert row["exit_fill_tag"] == closing.tag
        assert row["gross_pnl"] == trade.gross_pnl
        assert row["net_pnl"] == trade.net_pnl


def test_linked_trades_to_dataframe_hand_computed_engine_rows():
    """Hand-computed from the three_trade_result fixture's known fills."""
    frame = workflow.linked_trades_to_dataframe(three_trade_result())

    assert list(frame["trade"]) == [0, 1, 2]
    assert list(frame["direction"]) == ["LONG", "SHORT", "LONG"]
    assert list(frame["quantity"]) == [100.0, 100.0, 100.0]
    assert list(frame["entry_fill_bar"]) == [1, 3, 5]
    assert list(frame["exit_fill_bar"]) == [2, 4, 6]
    assert list(frame["entry_fill_timestamp"]) == [_bar_ts(1), _bar_ts(3), _bar_ts(5)]
    assert list(frame["exit_fill_timestamp"]) == [_bar_ts(2), _bar_ts(4), _bar_ts(6)]
    assert list(frame["entry_fill_price"]) == [100.0, 100.0, 100.0]
    assert list(frame["exit_fill_price"]) == [110.0, 120.0, 90.0]
    assert list(frame["entry_fill_commission"]) == [0.0, 0.0, 0.0]
    assert list(frame["exit_fill_commission"]) == [0.0, 0.0, 0.0]
    assert list(frame["entry_fill_tag"]) == ["", "", ""]
    assert list(frame["exit_fill_kind"]) == ["EXIT", "EXIT", "EXIT"]
    assert list(frame["gross_pnl"]) == [1000.0, -2000.0, -1000.0]
    assert list(frame["net_pnl"]) == [1000.0, -2000.0, -1000.0]


def test_linked_fills_to_dataframe_appends_roles_in_stream_order():
    result = three_trade_result()
    frame = workflow.linked_fills_to_dataframe(result)

    # The existing fills columns are preserved in order; linkage is appended.
    assert list(frame.columns) == [
        "bar",
        "timestamp",
        "kind",
        "side",
        "direction",
        "quantity",
        "price",
        "commission",
        "slippage",
        "tag",
        "linkage",
    ]
    # The annotated view is the original fills table plus one column.
    plain = workflow.fills_to_dataframe(result)
    pd.testing.assert_frame_equal(frame[plain.columns], plain)

    assert list(frame["linkage"]) == [
        "Trade 0 entry",
        "Trade 0 close",
        "Trade 1 entry",
        "Trade 1 close",
        "Trade 2 entry",
        "Trade 2 close",
    ]


def test_audit_same_bar_round_trip_links_when_timestamps_collide():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),  # bar 0: signal only
        (100.0, 101.0, 90.0, 95.0),   # bar 1: entry @100, low 90 hits stop 98
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=98.0, tag="sl_entry")]
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())
    assert result.fills[0].timestamp == result.fills[1].timestamp

    audit = workflow.linked_trades_to_dataframe(result)
    assert len(audit) == 1
    row = audit.iloc[0]
    # Entry and stop fill share bar 1 and its timestamp, so the pairing shown is
    # positional, never a timestamp join.
    assert row["entry_fill_bar"] == row["exit_fill_bar"] == 1
    assert row["entry_fill_timestamp"] == row["exit_fill_timestamp"] == _bar_ts(1)
    assert row["exit_fill_kind"] == "STOP_LOSS"
    assert row["entry_fill_price"] == 100.0
    assert row["exit_fill_price"] == 98.0
    assert row["quantity"] == 500.0
    assert row["net_pnl"] == -1000.0
    assert row["entry_fill_tag"] == row["exit_fill_tag"] == "sl_entry"

    fills = workflow.linked_fills_to_dataframe(result)
    assert list(fills["linkage"]) == ["Trade 0 entry", "Trade 0 close"]


def test_audit_open_position_trailing_entry_has_no_completed_trade_row():
    """Engine's 2N+1 shape: one completed trade plus a trailing open entry."""
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),   # 0: signal
        (100.0, 108.0, 95.0, 105.0),   # 1: trade A entry @100
        (110.0, 112.0, 109.0, 111.0),  # 2: trade A exit @110, then re-entry signal
        (100.0, 108.0, 95.0, 105.0),   # 3: trade B entry @100, held open
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
        2: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())
    assert len(result.fills) == 3
    assert len(result.trades) == 1
    assert result.is_flat is False

    audit = workflow.linked_trades_to_dataframe(result)
    # Only the completed trade is audited: no synthetic row for the open position.
    assert list(audit["trade"]) == [0]
    assert list(audit["exit_fill_bar"]) == [2]

    fills = workflow.linked_fills_to_dataframe(result)
    assert list(fills["linkage"]) == [
        "Trade 0 entry",
        "Trade 0 close",
        workflow.OPEN_POSITION_ENTRY_LINKAGE,
    ]
    # Exact required wording, attached to the trailing bar-3 ENTRY fill.
    assert fills["linkage"].iloc[2] == "Open-position entry — no completed trade."
    assert fills["bar"].iloc[2] == 3
    assert fills["kind"].iloc[2] == "ENTRY"


def test_audit_open_position_without_completed_trades():
    result = open_long_result()
    assert result.trades == ()
    assert result.is_flat is False

    audit = workflow.linked_trades_to_dataframe(result)
    assert audit.empty

    fills = workflow.linked_fills_to_dataframe(result)
    assert list(fills["linkage"]) == ["Open-position entry — no completed trade."]


def test_audit_empty_result_yields_empty_frames():
    result = do_nothing_result()

    audit = workflow.linked_trades_to_dataframe(result)
    fills = workflow.linked_fills_to_dataframe(result)

    assert audit.empty
    assert fills.empty
    # The annotation column exists even with no rows, so the view stays stable.
    assert "linkage" in fills.columns


def test_audit_shows_entry_and_exit_tags_verbatim_without_a_tag_join():
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),
        (100.0, 108.0, 95.0, 105.0),   # 1: entry, tag E1
        (110.0, 112.0, 109.0, 111.0),  # 2: exit, tag X1
    ])
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, tag="E1")],
        1: [StrategyDecision(action=OrderAction.EXIT, tag="X1")],
    }
    result = run_backtest(ScriptedStrategy(script), df, _config())

    row = workflow.linked_trades_to_dataframe(result).iloc[0]
    assert row["entry_fill_tag"] == "E1"
    assert row["exit_fill_tag"] == "X1"


def test_audit_helpers_propagate_linkage_failures():
    # Trades recorded without any fills: the linkage is unavailable.
    synthetic = make_result([make_trade(100.0)])
    assert synthetic.fills == ()

    with pytest.raises(workflow.TradeFillLinkageError, match="Linkage unavailable"):
        workflow.linked_trades_to_dataframe(synthetic)
    with pytest.raises(workflow.TradeFillLinkageError, match="Linkage unavailable"):
        workflow.linked_fills_to_dataframe(synthetic)


class _CountingStrategy(Strategy):
    """Scripted strategy that records how often the engine invoked it."""

    def __init__(self, script):
        self._script = script
        self.calls = 0

    def on_bar(self, context):
        self.calls += 1
        return list(self._script.get(context.current_index, []))


def test_audit_helpers_are_read_only_deterministic_and_never_rerun():
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

    audit_first = workflow.linked_trades_to_dataframe(result)
    fills_first = workflow.linked_fills_to_dataframe(result)
    audit_second = workflow.linked_trades_to_dataframe(result)
    fills_second = workflow.linked_fills_to_dataframe(result)

    # The helpers never invoked the strategy again (once per bar, 3 bars).
    assert strategy.calls == calls_after_run == 3

    # The result is untouched: same tuple objects, same contents.
    assert result.fills is fills_before
    assert result.trades is trades_before
    assert result.fills == fills_snapshot
    assert result.trades == trades_snapshot

    # Deterministic: equal output on repeated calls.
    pd.testing.assert_frame_equal(audit_first, audit_second)
    pd.testing.assert_frame_equal(fills_first, fills_second)


# -------------------------------------------- R-multiple display (M13 integration)
# The per-trade R-multiple and the panel's Mean R / counts come straight from the
# pure M13 helper in ``src.metrics.r_multiple``; these tests assert the wiring and
# that undefined values render as n/a / None rather than a substituted zero.


def test_trades_to_dataframe_includes_r_multiple_column():
    """Each completed trade row exposes its M13 R-multiple.

    ``three_trade_result`` has R-multiples [1.0, -2.0, -1.0] (see
    ``tests/test_metrics/test_r_multiple.py``).
    """
    trades = workflow.trades_to_dataframe(three_trade_result())

    assert "r_multiple" in trades.columns
    assert list(trades["r_multiple"]) == [1.0, -2.0, -1.0]


def test_trades_to_dataframe_r_multiple_is_undefined_without_initial_stop():
    """A trade with no recorded initial stop yields an undefined R, never 0."""
    result = make_result([make_trade(100.0)])  # make_trade's default initial_stop is None

    trades = workflow.trades_to_dataframe(result)

    assert "r_multiple" in trades.columns
    assert trades["r_multiple"].isna().all()


def test_performance_summary_includes_r_multiple_rows():
    """Mean R and the computable/non-computable counts come from the M13 helper."""
    summary = dict(workflow.performance_summary(three_trade_result()))

    # (1.0 + -2.0 + -1.0) / 3, formatted to two decimals by _format_ratio.
    assert summary["Mean R"] == "-0.67"
    assert summary["R-multiple computable trades"] == "3"
    assert summary["R-multiple non-computable trades"] == "0"


def test_performance_summary_renders_undefined_mean_r_as_na():
    """With no computable trade the mean R is 'n/a', never '0.00'."""
    summary = dict(workflow.performance_summary(do_nothing_result()))

    assert summary["Mean R"] == "n/a"
    assert summary["Mean R"] != "0.00"
    assert summary["R-multiple computable trades"] == "0"
    assert summary["R-multiple non-computable trades"] == "0"


# ------------------------------------------------------ results filtering (M34)
# ``filter_rows`` is the pure helper behind the results-table filter widgets. It
# must reproduce the input when unset, intersect criteria, tolerate unknown
# columns, never mutate its input, and stay deterministic.


def _filter_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "direction": ["LONG", "SHORT", "LONG"],
            "exit_kind": ["EXIT", "STOP_LOSS", "STOP_LOSS"],
            "value": [1, 2, 3],
        }
    )


def test_filter_rows_without_criteria_returns_equal_copy():
    frame = _filter_frame()

    result = workflow.filter_rows(frame, None)

    pd.testing.assert_frame_equal(result, frame)
    assert result is not frame


def test_filter_rows_empty_criteria_mapping_returns_all_rows():
    frame = _filter_frame()

    result = workflow.filter_rows(frame, {})

    pd.testing.assert_frame_equal(result, frame)


def test_filter_rows_single_criterion_matches_selected_values():
    frame = _filter_frame()

    result = workflow.filter_rows(frame, {"direction": ["LONG"]})

    assert list(result["value"]) == [1, 3]


def test_filter_rows_combines_criteria_as_an_intersection():
    frame = _filter_frame()

    result = workflow.filter_rows(
        frame, {"direction": ["LONG"], "exit_kind": ["STOP_LOSS"]}
    )

    assert list(result["value"]) == [3]


def test_filter_rows_empty_selection_imposes_no_restriction():
    frame = _filter_frame()

    result = workflow.filter_rows(frame, {"direction": []})

    pd.testing.assert_frame_equal(result, frame)


def test_filter_rows_none_selection_imposes_no_restriction():
    frame = _filter_frame()

    result = workflow.filter_rows(frame, {"direction": None})

    pd.testing.assert_frame_equal(result, frame)


def test_filter_rows_unknown_column_imposes_no_restriction():
    frame = _filter_frame()

    result = workflow.filter_rows(frame, {"not_a_column": ["anything"]})

    pd.testing.assert_frame_equal(result, frame)


def test_filter_rows_no_match_returns_empty_frame_with_columns():
    frame = _filter_frame()

    result = workflow.filter_rows(
        frame, {"direction": ["SHORT"], "exit_kind": ["EXIT"]}
    )

    assert result.empty
    assert list(result.columns) == list(frame.columns)


def test_filter_rows_does_not_mutate_input_and_preserves_row_order():
    frame = _filter_frame()
    before = frame.copy()

    result = workflow.filter_rows(frame, {"direction": ["LONG"]})

    pd.testing.assert_frame_equal(frame, before)
    assert list(result.index) == [0, 2]


def test_filter_rows_is_deterministic():
    frame = _filter_frame()

    first = workflow.filter_rows(frame, {"exit_kind": ["STOP_LOSS"]})
    second = workflow.filter_rows(frame, {"exit_kind": ["STOP_LOSS"]})

    pd.testing.assert_frame_equal(first, second)


def test_filter_rows_on_empty_frame_is_safe():
    frame = _filter_frame().iloc[0:0]

    result = workflow.filter_rows(frame, {"direction": ["LONG"]})

    assert result.empty
    assert list(result.columns) == list(frame.columns)


def test_trades_to_dataframe_includes_tag_column():
    result = three_trade_result()
    trades = workflow.trades_to_dataframe(result)
    assert "tag" in trades.columns
    assert list(trades["tag"]) == ["" for _ in range(len(trades))]


def test_filter_rows_unknown_column_continues_to_be_safe():
    frame = _filter_frame()
    result = workflow.filter_rows(frame, {"direction": ["LONG"], "nonexistent_col": ["X"]})
    assert list(result["value"]) == [1, 3]
    pd.testing.assert_frame_equal(frame, _filter_frame())  # input not mutated
