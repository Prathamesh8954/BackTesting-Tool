from dataclasses import FrozenInstanceError
import pandas as pd
import pytest
from src.strategy.context import StrategyContext
from src.strategy.models import AccountView, PositionView


def test_context_no_future_candles(valid_ohlcv_df: pd.DataFrame):
    """
    Verifies that StrategyContext strictly enforces lookahead protection:
    history() only contains bars up to current_idx and never exposes future candles.
    """
    for idx in range(len(valid_ohlcv_df)):
        ctx = StrategyContext(full_df=valid_ohlcv_df, current_idx=idx)

        hist = ctx.history()
        assert len(hist) == idx + 1
        assert hist["timestamp"].iloc[-1] == valid_ohlcv_df["timestamp"].iloc[idx]
        assert hist["timestamp"].iloc[0] == valid_ohlcv_df["timestamp"].iloc[0]

        # Verify no future timestamp exists in the returned history
        max_ts_in_history = hist["timestamp"].max()
        assert max_ts_in_history == valid_ohlcv_df["timestamp"].iloc[idx]
        if idx < len(valid_ohlcv_df) - 1:
            future_ts = valid_ohlcv_df["timestamp"].iloc[idx + 1]
            assert future_ts not in hist["timestamp"].values


def test_context_history_window_sizing(valid_ohlcv_df: pd.DataFrame):
    """Verifies that n_bars correctly slices the trailing window up to current_idx."""
    # At index 3 (4 bars available: 0, 1, 2, 3)
    ctx = StrategyContext(full_df=valid_ohlcv_df, current_idx=3)

    # Window of 2 bars -> rows 2 and 3
    hist_2 = ctx.history(n_bars=2)
    assert len(hist_2) == 2
    assert hist_2["timestamp"].iloc[0] == valid_ohlcv_df["timestamp"].iloc[2]
    assert hist_2["timestamp"].iloc[1] == valid_ohlcv_df["timestamp"].iloc[3]

    # Window of 10 bars when only 4 exist -> returns all 4 bars gracefully
    hist_10 = ctx.history(n_bars=10)
    assert len(hist_10) == 4
    assert hist_10["timestamp"].iloc[0] == valid_ohlcv_df["timestamp"].iloc[0]
    assert hist_10["timestamp"].iloc[-1] == valid_ohlcv_df["timestamp"].iloc[3]


def test_context_boundary_conditions(valid_ohlcv_df: pd.DataFrame):
    """Verifies boundary handling for invalid indices and parameters."""
    # Out of bounds indices
    with pytest.raises(IndexError, match="out of bounds"):
        StrategyContext(full_df=valid_ohlcv_df, current_idx=-1)

    with pytest.raises(IndexError, match="out of bounds"):
        StrategyContext(full_df=valid_ohlcv_df, current_idx=len(valid_ohlcv_df))

    # Empty DataFrame
    with pytest.raises(ValueError, match="cannot be empty"):
        StrategyContext(full_df=pd.DataFrame(), current_idx=0)

    # Invalid n_bars values
    ctx = StrategyContext(full_df=valid_ohlcv_df, current_idx=2)
    with pytest.raises(ValueError, match="positive integer"):
        ctx.history(n_bars=0)

    with pytest.raises(ValueError, match="positive integer"):
        ctx.history(n_bars=-5)

    with pytest.raises(ValueError, match="positive integer"):
        ctx.history(n_bars=1.5)  # type: ignore


def test_current_bar_mutation_isolation(valid_ohlcv_df: pd.DataFrame):
    """
    CRITICAL ACCEPTANCE TEST:
    Modifying the Series returned by current_bar must not mutate the engine's DataFrame.
    """
    engine_df = valid_ohlcv_df.copy(deep=True)
    orig_close = engine_df.loc[2, "close"]

    ctx = StrategyContext(full_df=engine_df, current_idx=2)
    bar = ctx.current_bar

    # Strategy attempts to modify the bar
    bar["close"] = 99999.0
    bar["new_feature"] = "test"

    # Engine DataFrame must remain unchanged
    assert engine_df.loc[2, "close"] == orig_close
    assert "new_feature" not in engine_df.columns


def test_history_mutation_isolation(valid_ohlcv_df: pd.DataFrame):
    """
    CRITICAL ACCEPTANCE TEST:
    Adding columns or mutating prices in history() must not alter engine's DataFrame.
    """
    engine_df = valid_ohlcv_df.copy(deep=True)
    ctx = StrategyContext(full_df=engine_df, current_idx=3)

    hist = ctx.history(n_bars=3)

    # Strategy performs in-place modifications and adds indicator columns
    hist.loc[hist.index[0], "open"] = -999.0
    hist["sma_20"] = [1.0, 2.0, 3.0]

    # Engine DataFrame must remain intact
    assert "sma_20" not in engine_df.columns
    assert engine_df.loc[1, "open"] == valid_ohlcv_df.loc[1, "open"]
    assert (engine_df["open"] > 0).all()


def test_context_position_and_account_views(valid_ohlcv_df: pd.DataFrame):
    """Verifies that position and account views are accessible and strictly immutable."""
    pos = PositionView(is_open=True, direction="LONG", entry_price=100.0, bars_held=3)
    acc = AccountView(cash=50000.0, equity=50500.0, initial_capital=50000.0)

    ctx = StrategyContext(full_df=valid_ohlcv_df, current_idx=2, position=pos, account=acc)

    assert ctx.position.is_open is True
    assert ctx.position.entry_price == 100.0
    assert ctx.account.equity == 50500.0

    # Ensure views cannot be mutated
    with pytest.raises(FrozenInstanceError):
        ctx.position.bars_held = 4  # type: ignore

    with pytest.raises(FrozenInstanceError):
        ctx.account.cash = 0.0  # type: ignore
