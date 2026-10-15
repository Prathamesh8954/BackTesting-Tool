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
