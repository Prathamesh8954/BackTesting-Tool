import pandas as pd
import pytest

from src.execution import EngineConfig, run_backtest
from src.strategy.base import Strategy
from src.strategy.models import OrderAction, StrategyDecision
from src.ui import workflow
from tests.test_execution.helpers import ScriptedStrategy, make_df


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
