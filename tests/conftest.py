import pandas as pd
import pytest


@pytest.fixture
def valid_ohlcv_df() -> pd.DataFrame:
    """Minimal, deterministic 5-bar valid OHLCV DataFrame."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01 09:30", periods=5, freq="1h"),
        "open": [100.0, 102.0, 101.5, 103.0, 104.0],
        "high": [103.0, 104.5, 103.0, 105.0, 106.0],
        "low": [99.5, 101.0, 100.0, 102.5, 103.5],
        "close": [102.0, 101.5, 103.0, 104.0, 105.5],
        "volume": [1000.0, 1500.0, 1200.0, 1800.0, 2000.0],
    })
