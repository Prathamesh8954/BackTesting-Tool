"""End-to-end smoke test of the Streamlit app using Streamlit's AppTest harness."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")

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
