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


def test_app_renders_r_multiple_panel_and_trades_column(demo_raw_dir):
    """M13 integration: 'Mean R' rows render and the Trades table carries r_multiple."""
    at = _run_demo(streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run())

    assert not at.exception
    assert not at.error

    labels = [metric.label for metric in at.metric]
    for expected in (
        "Mean R",
        "R-multiple computable trades",
        "R-multiple non-computable trades",
    ):
        assert expected in labels, expected

    frames = [frame.value for frame in at.dataframe if isinstance(frame.value, pd.DataFrame)]
    assert any("r_multiple" in frame.columns for frame in frames)


# ------------------------------------------------ results filtering (M34)
# A dedicated two-trade run is used here so a filter can actually be narrowed to
# a single row and so a *combination* of two filters can be made to match
# nothing. Trade 0 is a LONG closed by a market EXIT; trade 1 is a SHORT closed
# by its stop-loss, giving both direction and exit-kind columns two values each.

TWO_TRADE_STRATEGY = '''
class TwoTrades(Strategy):
    def on_bar(self, context):
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]
        if context.current_index == 1:
            return [StrategyDecision(action=OrderAction.EXIT)]
        if context.current_index == 2:
            return [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)]
        return []
'''


@pytest.fixture
def two_trade_raw_dir(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01 09:30", periods=5, freq="1h"),
            "open": [100.0, 100.0, 110.0, 100.0, 105.0],
            "high": [102.0, 108.0, 112.0, 102.0, 115.0],
            "low": [98.0, 95.0, 109.0, 98.0, 104.0],
            "close": [100.0, 105.0, 111.0, 100.0, 110.0],
            "volume": [1000.0, 1500.0, 1200.0, 1800.0, 2000.0],
        }
    )
    df.to_csv(raw_dir / "demo.csv", index=False)
    monkeypatch.setattr(workflow, "DEFAULT_RAW_DIR", raw_dir)
    return raw_dir


def _multiselect(at, label: str):
    matches = [widget for widget in at.multiselect if widget.label == label]
    assert len(matches) == 1, f"expected exactly one {label!r} filter, found {len(matches)}"
    return matches[0]


def _trades_frame(at) -> pd.DataFrame:
    frames = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "entry_bar" in frame.value.columns
    ]
    assert len(frames) == 1, f"expected one trades table, found {len(frames)}"
    return frames[0]


def _run_two_trades():
    at = streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run()
    return _run_demo(at, TWO_TRADE_STRATEGY)


def test_app_renders_filter_widgets_with_data_derived_options(two_trade_raw_dir):
    """M34: filter widgets appear and only offer values present in the table."""
    at = _run_two_trades()

    assert not at.exception
    assert not at.error

    assert _multiselect(at, "Filter trades by direction").options == ["LONG", "SHORT"]
    assert _multiselect(at, "Filter trades by exit kind").options == ["EXIT", "STOP_LOSS"]
    assert _multiselect(at, "Filter fills by kind").options == ["ENTRY", "EXIT", "STOP_LOSS"]
    assert _multiselect(at, "Filter fills by direction").options == ["LONG", "SHORT"]


def test_app_unset_trade_filter_reproduces_the_full_table(two_trade_raw_dir):
    """M34: default (empty) selections leave the trades table unchanged."""
    at = _run_two_trades()

    assert not at.exception
    trades = _trades_frame(at)
    assert len(trades) == 2
    # Both directions are present, and nothing was dropped by a default filter.
    assert sorted(trades["direction"]) == ["LONG", "SHORT"]


def test_app_direction_filter_narrows_the_trade_and_audit_tables(two_trade_raw_dir):
    """M34: a selection narrows the trades table and the shared audit trail."""
    at = _run_two_trades()

    _multiselect(at, "Filter trades by direction").set_value(["SHORT"])
    at.run()

    assert not at.exception
    trades = _trades_frame(at)
    assert len(trades) == 1
    assert list(trades["direction"]) == ["SHORT"]

    # The audit trail shares the trade's direction filter.
    audits = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "exit_fill_kind" in frame.value.columns
    ]
    assert len(audits) == 1
    assert list(audits[0]["direction"]) == ["SHORT"]


def test_app_combined_trade_filters_can_match_nothing(two_trade_raw_dir):
    """M34: an intersection with no rows shows the empty notice, not a table."""
    at = _run_two_trades()

    _multiselect(at, "Filter trades by direction").set_value(["SHORT"])
    at.run()
    _multiselect(at, "Filter trades by exit kind").set_value(["EXIT"])
    at.run()

    assert not at.exception
    assert any(
        info.value == "No trades match the selected filters." for info in at.info
    )
    # No trades table is rendered once the filter matches nothing.
    frames = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "entry_bar" in frame.value.columns
    ]
    assert frames == []


def test_app_clearing_trade_filters_restores_the_full_table(two_trade_raw_dir):
    """M34: unsetting a filter returns the table to its full, unfiltered state."""
    at = _run_two_trades()

    _multiselect(at, "Filter trades by direction").set_value(["SHORT"])
    at.run()
    assert len(_trades_frame(at)) == 1

    _multiselect(at, "Filter trades by direction").set_value([])
    at.run()

    assert not at.exception
    assert len(_trades_frame(at)) == 2


def test_app_fill_filter_narrows_the_fills_table(two_trade_raw_dir):
    """M34: fills filter independently by kind without affecting the trades table."""
    at = _run_two_trades()

    _multiselect(at, "Filter fills by kind").set_value(["STOP_LOSS"])
    at.run()

    assert not at.exception
    fills = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "kind" in frame.value.columns
    ]
    assert len(fills) == 1
    assert list(fills[0]["kind"]) == ["STOP_LOSS"]
    # The trades table is unaffected by the fills filter.
    assert len(_trades_frame(at)) == 2


REJECTION_STRATEGY = '''
class Rejected(Strategy):
    def on_bar(self, context):
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.EXIT)]
        return []
'''


def test_app_renders_rejection_filter_widget(demo_raw_dir):
    """M34: the rejections table gains a reason filter when rejections exist."""
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        REJECTION_STRATEGY,
    )

    assert not at.exception
    assert not at.error

    widget = _multiselect(at, "Filter rejections by reason")
    assert widget.options == ["EXIT_WHILE_FLAT"]

    rejections = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "reason" in frame.value.columns
    ]
    assert len(rejections) == 1
    assert list(rejections[0]["reason"]) == ["EXIT_WHILE_FLAT"]


# ------------------------------------------- filtering regression tests (M36)
# M35 S3: the M34 filter tests proved the *direction* filter end-to-end but left
# two paths only indirectly covered. These tests exercise them directly and each
# rejects at least one row, so a no-op filter would fail them.

def test_app_exit_kind_filter_narrows_the_audit_trail_via_mapping(two_trade_raw_dir):
    """M36 (S3): the audit trail narrows through its exit_fill_kind mapping.

    The direction filter is deliberately left unset, so the audit's two rows can
    only be reduced to one by the ``exit_kind`` -> ``exit_fill_kind`` remap; a
    broken mapping would show both rows.
    """
    at = _run_two_trades()

    _multiselect(at, "Filter trades by exit kind").set_value(["STOP_LOSS"])
    at.run()

    assert not at.exception
    assert not at.error

    # Trades: 2 -> 1, excluding the EXIT-closed trade.
    trades = _trades_frame(at)
    assert len(trades) == 1
    assert list(trades["exit_kind"]) == ["STOP_LOSS"]

    audits = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "exit_fill_kind" in frame.value.columns
    ]
    assert len(audits) == 1
    # The audit narrowed to the single SHORT trade through the mapped column.
    assert len(audits[0]) == 1
    assert list(audits[0]["exit_fill_kind"]) == ["STOP_LOSS"]
    assert list(audits[0]["direction"]) == ["SHORT"]


TWO_REJECTION_STRATEGY = '''
class TwoRejections(Strategy):
    def on_bar(self, context):
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.EXIT)]
        if context.current_index == 1:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]
        if context.current_index == 2:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]
        return []
'''


TAGGED_REJECTION_STRATEGY = '''
class TaggedRejections(Strategy):
    def on_bar(self, context):
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.EXIT, tag="R1")]
        if context.current_index == 1:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]
        if context.current_index == 2:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, tag="R2")]
        return []
'''


def test_app_rejection_reason_filter_excludes_non_matching_rows(demo_raw_dir):
    """M36 (S3): selecting a reason narrows the Rejections table (2 -> 1).

    The strategy records two distinct reasons (``EXIT_WHILE_FLAT`` then
    ``ENTRY_WHILE_OPEN``), so a selection must exclude at least one row.
    """
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        TWO_REJECTION_STRATEGY,
    )

    assert not at.exception
    assert not at.error

    widget = _multiselect(at, "Filter rejections by reason")
    assert widget.options == ["ENTRY_WHILE_OPEN", "EXIT_WHILE_FLAT"]

    widget.set_value(["EXIT_WHILE_FLAT"])
    at.run()

    assert not at.exception
    assert not at.error

    rejections = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "reason" in frame.value.columns
    ]
    assert len(rejections) == 1
    assert list(rejections[0]["reason"]) == ["EXIT_WHILE_FLAT"]


def test_app_rejection_tag_filter_narrows_rejections_rows(demo_raw_dir):
    """M43: selecting a tag narrows the Rejections table by its tag column.

    Two rejections carry different tags (``R1`` on the EXIT_WHILE_FLAT, ``R2``
    on the ENTRY_WHILE_OPEN), so selecting one must exclude the other row.
    """
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        TAGGED_REJECTION_STRATEGY,
    )

    assert not at.exception
    assert not at.error

    widget = _multiselect(at, "Filter rejections by tag")
    assert widget.options == ["R1", "R2"]

    widget.set_value(["R1"])
    at.run()

    assert not at.exception
    rejections = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "reason" in frame.value.columns
    ]
    assert len(rejections) == 1
    assert list(rejections[0]["tag"]) == ["R1"]
    assert list(rejections[0]["reason"]) == ["EXIT_WHILE_FLAT"]

    # Clearing the tag filter restores both rows (reason filter still unset).
    _multiselect(at, "Filter rejections by tag").set_value([])
    at.run()
    rejections = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "reason" in frame.value.columns
    ]
    assert len(rejections) == 1
    assert sorted(rejections[0]["tag"]) == ["R1", "R2"]


TAG_STRATEGY = '''
class TaggedTrades(Strategy):
    def on_bar(self, context):
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0, tag="A")]
        if context.current_index == 1:
            return [StrategyDecision(action=OrderAction.EXIT, tag="X")]
        if context.current_index == 2:
            return [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0, tag="B")]
        if context.current_index == 3:
            return [StrategyDecision(action=OrderAction.EXIT)]
        return []
'''


def test_app_tag_filtering_and_shared_audit_mapping(two_trade_raw_dir):
    """M43: tag filter narrows Trades, audit (via entry_fill_tag), Fills."""
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        TAG_STRATEGY,
    )
    assert not at.exception
    tag_widget = _multiselect(at, "Filter trades by tag")
    assert set(tag_widget.options) >= {"A", "B"}
    tag_widget.set_value(["A"])
    at.run()
    assert not at.exception
    trades = _trades_frame(at)
    assert len(trades) == 1 and list(trades["tag"]) == ["A"]
    audits = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "exit_fill_kind" in frame.value.columns
    ]
    assert len(audits) == 1 and list(audits[0]["entry_fill_tag"]) == ["A"]
    # Fills tag filtering narrows the fills table without touching trades.
    fill_tag = _multiselect(at, "Filter fills by tag")
    assert set(fill_tag.options) >= {"A", "B", "X"}
    fill_tag.set_value(["A"])
    at.run()
    fills_frames = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "linkage" in frame.value.columns
    ]
    assert len(fills_frames) == 1
    assert list(fills_frames[0]["tag"]) == ["A"]
    # Trades keep their own (still active) tag filter: exactly the tag-A trade.
    assert len(_trades_frame(at)) == 1
    _multiselect(at, "Filter fills by tag").set_value([])
    at.run()
    # Re-fetch after run: widget references go stale once the app reruns.
    _multiselect(at, "Filter trades by tag").set_value([])
    at.run()
    trades_all = _trades_frame(at)
    assert len(trades_all) == 2
    assert sorted(trades_all["tag"]) == ["A", "B"]


def test_app_tag_filter_clearing_preserves_other_filters(two_trade_raw_dir):
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        TAG_STRATEGY,
    )
    _multiselect(at, "Filter trades by direction").set_value(["SHORT"])
    _multiselect(at, "Filter trades by tag").set_value(["B"])
    at.run()
    combined = _trades_frame(at)
    assert len(combined) == 1 and list(combined["tag"]) == ["B"]
    _multiselect(at, "Filter trades by tag").set_value([])
    at.run()
    trades = _trades_frame(at)
    assert len(trades) == 1 and list(trades["direction"]) == ["SHORT"]  # tag cleared, direction still active


# --------------------------------------------- bar-range filtering tests (M44)

def _slider(at, label: str):
    matches = [widget for widget in at.slider if widget.label == label]
    assert len(matches) == 1, f"expected exactly one {label!r} slider, found {len(matches)}"
    return matches[0]


def _audit_frame(at) -> pd.DataFrame:
    frames = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "entry_fill_bar" in frame.value.columns
    ]
    assert len(frames) == 1, f"expected one audit table, found {len(frames)}"
    return frames[0]


def _fills_frame(at) -> pd.DataFrame:
    frames = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "linkage" in frame.value.columns
    ]
    assert len(frames) == 1, f"expected one fills table, found {len(frames)}"
    return frames[0]


def _rejections_frame(at) -> pd.DataFrame:
    frames = [
        frame.value
        for frame in at.dataframe
        if isinstance(frame.value, pd.DataFrame) and "reason" in frame.value.columns
    ]
    assert len(frames) == 1, f"expected one rejections table, found {len(frames)}"
    return frames[0]


def test_app_trades_bar_range_narrows_trades_and_audit(two_trade_raw_dir):
    """M44: the Trades entry-bar range narrows Trades and the audit trail together.

    The audit follows through its own ``entry_fill_bar`` column (the entry fill
    sits on the entry bar), so the remapped range must exclude the same trade.
    """
    at = _run_two_trades()

    assert not at.exception
    assert not at.error
    assert len(_trades_frame(at)) == 2
    assert len(_audit_frame(at)) == 2

    # entry_bar domain is (1, 3): the later trade entered on bar 3.
    _slider(at, "Filter trades by entry bar").set_range(3, 3)
    at.run()

    assert not at.exception
    trades = _trades_frame(at)
    assert list(trades["entry_bar"]) == [3]
    audit = _audit_frame(at)
    assert list(audit["entry_fill_bar"]) == [3]
    assert list(audit["direction"]) == ["SHORT"]


def test_app_trades_bar_range_full_selection_is_noop(two_trade_raw_dir):
    """M44: selecting the whole observed domain leaves both views unfiltered."""
    at = _run_two_trades()

    slider = _slider(at, "Filter trades by entry bar")
    assert tuple(slider.value) == (1, 3)  # default minimum-to-maximum

    slider.set_range(1, 3)
    at.run()

    assert not at.exception
    assert len(_trades_frame(at)) == 2
    assert len(_audit_frame(at)) == 2


def test_app_trades_bar_range_intersects_with_categorical_filter(two_trade_raw_dir):
    """M44: the range intersects the direction filter instead of bypassing it."""
    at = _run_two_trades()

    _multiselect(at, "Filter trades by direction").set_value(["SHORT"])
    _slider(at, "Filter trades by entry bar").set_range(1, 1)
    at.run()

    assert not at.exception
    # SHORT enters on bar 3, so the bar<=1 range excludes it: no rows survive.
    assert not any(
        isinstance(frame.value, pd.DataFrame) and "entry_bar" in frame.value.columns
        for frame in at.dataframe
    )
    notices = [info.value for info in at.info]
    assert "No trades match the selected filters." in notices


def test_app_fills_bar_range_is_independent_of_trades(two_trade_raw_dir):
    """M44: the fills range filters fills only; Trades and audit stay whole."""
    at = _run_two_trades()

    # fills bar domain is (1, 4): keep the two fills of the first trade.
    _slider(at, "Filter fills by bar").set_range(1, 2)
    at.run()

    assert not at.exception
    fills = _fills_frame(at)
    assert list(fills["bar"]) == [1, 2]
    assert len(_trades_frame(at)) == 2
    assert len(_audit_frame(at)) == 2


def test_app_rejections_bar_range_is_independent(demo_raw_dir):
    """M44: the Rejections range filters on the rejection's own ``bar`` column."""
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        TWO_REJECTION_STRATEGY,
    )

    assert not at.exception
    assert list(_rejections_frame(at)["bar"]) == [0, 2]

    _slider(at, "Filter rejections by bar").set_range(2, 2)
    at.run()

    assert not at.exception
    rejections = _rejections_frame(at)
    assert list(rejections["bar"]) == [2]
    assert list(rejections["reason"]) == ["ENTRY_WHILE_OPEN"]


def test_app_single_bar_domain_renders_no_range_slider(demo_raw_dir):
    """M44: a one-value bar column yields a valid no-op, never a zero-width slider."""
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        OPEN_POSITION_STRATEGY,
    )

    assert not at.exception
    # The only fill sits on one bar, so no fills range slider is offered...
    assert not [widget for widget in at.slider if widget.label == "Filter fills by bar"]
    # ...and the open-position entry still renders, with no completed trades.
    assert list(_fills_frame(at)["bar"]) == [1]
    assert any(info.value == "No completed trades." for info in at.info)


OPEN_AFTER_TRADE_STRATEGY = '''
class OpenAfterTrade(Strategy):
    def on_bar(self, context):
        if context.current_index == 0:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]
        if context.current_index == 1:
            return [StrategyDecision(action=OrderAction.EXIT)]
        if context.current_index == 2:
            return [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]
        return []
'''


def test_app_open_position_fill_survives_bar_range(demo_raw_dir):
    """M44: the range applies to Fills only; an open position is unchanged.

    The trailing ENTRY fill of the position left open at the end of the data is a
    fill like any other, so it is range-filterable while the lifecycle rule (no
    completed-trade or audit row for it) is preserved.
    """
    at = _run_demo(
        streamlit_testing.AppTest.from_file(APP_PATH, default_timeout=30).run(),
        OPEN_AFTER_TRADE_STRATEGY,
    )

    assert not at.exception
    assert list(_fills_frame(at)["bar"]) == [1, 2, 3]
    assert len(_trades_frame(at)) == 1
    assert len(_audit_frame(at)) == 1

    _slider(at, "Filter fills by bar").set_range(3, 3)
    at.run()

    assert not at.exception
    narrowed = _fills_frame(at)
    assert list(narrowed["bar"]) == [3]
    assert list(narrowed["linkage"]) == [workflow.OPEN_POSITION_ENTRY_LINKAGE]
    # Lifecycle unchanged: still exactly one completed trade and one audit row.
    assert len(_trades_frame(at)) == 1
    assert len(_audit_frame(at)) == 1
