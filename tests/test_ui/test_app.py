"""End-to-end smoke test of the Streamlit app using Streamlit's AppTest harness."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")

from src.metrics import MetricsConsistencyError  # noqa: E402
from src.ui import workflow  # noqa: E402

APP_PATH = Path(__file__).resolve().parents[2] / "app.py"


DEMO_STRATEGY = '''
class Demo(Strategy):
    def on_bar(self, context):
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]
        if context.current_index == 2:
            return [StrategyDecision(action=OrderAction.EXIT)]
        return []
'''


@pytest.fixture
def demo_raw_dir(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01 09:30", periods=4, freq="1h"),
            "open": [100.0, 100.0, 103.0, 103.0],
            "high": [103.0, 104.0, 106.0, 104.0],
            "low": [99.0, 98.0, 102.0, 99.0],
            "close": [102.0, 103.0, 105.0, 100.0],
            "volume": [1000.0, 1500.0, 1200.0, 1800.0],
        }
    )
    df.to_csv(raw_dir / "demo.csv", index=False)
    monkeypatch.setattr(workflow, "DEFAULT_RAW_DIR", raw_dir)
    return raw_dir


def test_app_renders_without_data(demo_raw_dir):
    at = streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Historical Strategy Backtester"


def test_app_end_to_end_backtest(demo_raw_dir):
    at = streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run()

    at.selectbox[0].select("demo.csv").run()
    assert not at.exception
    assert any("valid and ready" in success.value for success in at.success)

    at.text_area[0].set_value(DEMO_STRATEGY).run()
    at.button[0].click().run()

    assert not at.exception
    assert any(success.value == "Backtest complete." for success in at.success)
    # The engine recorded one completed trade and displayed it.
    trades_tables = [frame.value for frame in at.dataframe]
    assert any(isinstance(frame, pd.DataFrame) and "direction" in frame.columns for frame in trades_tables)


def test_app_renders_performance_panel_and_drawdown(demo_raw_dir):
    """M7: the M4 performance panel and the M5 drawdown chart appear after a run."""
    at = streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run()

    at.selectbox[0].select("demo.csv").run()
    at.text_area[0].set_value(DEMO_STRATEGY).run()
    at.button[0].click().run()

    assert not at.exception
    # A metric-calculation failure would surface here; it must not occur.
    assert not at.error

    labels = [metric.label for metric in at.metric]
    # The M7 performance fields are rendered...
    for expected in (
        "Closed trades",
        "Breakeven trades",
        "Win rate",
        "Expectancy per trade",
        "Profit factor",
        "Average bars held",
        "Max drawdown",
        "Max drawdown %",
        "Reconciliation difference",
    ):
        assert expected in labels, expected
    # ...without displacing the accounting summary (D1).
    for expected in ("Initial capital", "Final equity", "Completed trades", "Fills", "Rejections"):
        assert expected in labels, expected

    headers = [subheader.value for subheader in at.subheader]
    assert "Performance metrics" in headers
    # D3: the drawdown chart sits directly beneath the equity curve.
    assert headers.index("Equity curve") + 1 == headers.index("Drawdown (%)")


def test_app_surfaces_metric_error_instead_of_hiding_panel(demo_raw_dir, monkeypatch):
    """A MetricsConsistencyError must be shown to the user, not silently swallowed."""
    def _raise_consistency_error(result):
        raise MetricsConsistencyError("synthetic P&L mismatch")

    # app.py resolves workflow.performance_summary at call time, so patching the
    # module attribute is enough to simulate the failure.
    monkeypatch.setattr(workflow, "performance_summary", _raise_consistency_error)

    at = streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run()

    at.selectbox[0].select("demo.csv").run()
    at.text_area[0].set_value(DEMO_STRATEGY).run()
    at.button[0].click().run()

    assert not at.exception
    assert any("accounting consistency check" in error.value for error in at.error)
    # The failure is contained: the rest of the results view still renders.
    headers = [subheader.value for subheader in at.subheader]
    assert "Equity curve" in headers
    assert "Drawdown (%)" in headers
    assert "Trades" in headers


OPEN_POSITION_STRATEGY = '''
class Open(Strategy):
    def on_bar(self, context):
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]
        return []
'''


def _run_demo(at, strategy: str = DEMO_STRATEGY):
    at.selectbox[0].select("demo.csv").run()
    at.text_area[0].set_value(strategy).run()
    at.button[0].click().run()
    return at


def test_app_renders_trade_audit_trail_between_trades_and_fills(demo_raw_dir):
    """M9: the audit section sits between Trades and Fills and shows valid rows."""
    at = _run_demo(streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run())

    assert not at.exception
    assert not at.error

    headers = [subheader.value for subheader in at.subheader]
    assert headers.index("Trades") + 1 == headers.index("Trade audit trail")
    assert headers.index("Trade audit trail") + 1 == headers.index("Fills")

    frames = [frame.value for frame in at.dataframe if isinstance(frame.value, pd.DataFrame)]
    # One audit row pairing the demo trade with both of its fills.
    assert any(
        "exit_fill_kind" in frame.columns and "entry_fill_bar" in frame.columns
        for frame in frames
    )
    # The single fills table is annotated in place, not duplicated.
    linked = [frame for frame in frames if "linkage" in frame.columns]
    assert len(linked) == 1
    assert list(linked[0]["linkage"]) == ["Trade 0 entry", "Trade 0 close"]


@pytest.mark.parametrize(
    "failing_helper",
    ["linked_trades_to_dataframe", "linked_fills_to_dataframe"],
)
def test_app_surfaces_linkage_error_and_keeps_other_sections(
    demo_raw_dir, monkeypatch, failing_helper
):
    """A TradeFillLinkageError is shown, and the remaining sections still render."""

    def _raise_linkage_error(result):
        raise workflow.TradeFillLinkageError("synthetic linkage failure")

    # app.py resolves the workflow helpers at call time; patching either one must
    # be contained by the same error handling.
    monkeypatch.setattr(workflow, failing_helper, _raise_linkage_error)

    at = _run_demo(streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run())

    assert not at.exception
    assert any("linkage consistency check" in error.value for error in at.error)

    headers = [subheader.value for subheader in at.subheader]
    for expected in (
        "Equity curve",
        "Drawdown (%)",
        "Trades",
        "Trade audit trail",
        "Fills",
        "Rejections",
    ):
        assert expected in headers, expected

    # The fills table still renders, just without the unavailable annotation.
    frames = [frame.value for frame in at.dataframe if isinstance(frame.value, pd.DataFrame)]
    assert any("kind" in frame.columns and "tag" in frame.columns for frame in frames)
    assert not any("linkage" in frame.columns for frame in frames)
    # No stale/partial audit table is shown either: the audit section reports the
    # error instead of a table, whichever of the two helpers failed.
    assert not any("exit_fill_kind" in frame.columns for frame in frames)


def test_app_does_not_swallow_unrelated_audit_exceptions(demo_raw_dir, monkeypatch):
    """Only TradeFillLinkageError is contained; other exceptions must propagate."""

    def _raise_runtime_error(result):
        raise RuntimeError("synthetic unrelated failure")

    monkeypatch.setattr(workflow, "linked_trades_to_dataframe", _raise_runtime_error)

    at = _run_demo(streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run())

    # The unrelated error escaped the linkage handler rather than being hidden.
    assert at.exception
    assert any("synthetic unrelated failure" in exc.value for exc in at.exception)
    assert not any("linkage consistency check" in error.value for error in at.error)


def test_app_marks_open_position_entry_and_creates_no_trade_row(demo_raw_dir):
    """M9: a position left open is labelled, with no synthetic completed trade."""
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        OPEN_POSITION_STRATEGY,
    )

    assert not at.exception
    # No completed trade exists: the audit section says so rather than inventing one.
    assert any(info.value == "No completed trades to audit." for info in at.info)

    frames = [frame.value for frame in at.dataframe if isinstance(frame.value, pd.DataFrame)]
    linked = [frame for frame in frames if "linkage" in frame.columns]
    assert len(linked) == 1
    assert list(linked[0]["linkage"]) == ["Open-position entry — no completed trade."]
    # No completed-trade row is rendered for the still-open position. Identify
    # each results table by a column it alone owns (the trades table owns
    # `entry_bar`, the audit table owns `exit_fill_kind`) rather than imposing a
    # blanket restriction on every rendered table's column names.
    assert not any("entry_bar" in frame.columns for frame in frames)
    assert not any("exit_fill_kind" in frame.columns for frame in frames)
