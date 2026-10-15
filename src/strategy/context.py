from typing import Optional
import pandas as pd
from src.strategy.models import AccountView, PositionView


class StrategyContext:
    """
    Simulation context providing a chronological window of market and state data
    to a strategy at bar index i.

    Lookahead Protection (Interface-level):
    - Guarantees that algorithms cannot access future candles (indices > i)
      through this intended public API.
    - All return values (current_bar, history) are detached deep copies. Mutating them
      has zero effect on the engine's underlying market data.
    - IMPORTANT: This is interface-level lookahead protection designed to prevent
      accidental algorithm design errors. It is not an OS/process-level security sandbox
      against hostile or arbitrary Python bytecode.
    """

    def __init__(
        self,
        full_df: pd.DataFrame,
        current_idx: int,
        position: Optional[PositionView] = None,
        account: Optional[AccountView] = None,
    ):
        if full_df is None or full_df.empty:
            raise ValueError("full_df cannot be empty or None.")

        if not isinstance(current_idx, int) or current_idx < 0 or current_idx >= len(full_df):
            raise IndexError(
                f"current_idx {current_idx} is out of bounds for DataFrame with {len(full_df)} rows."
            )

        self._df = full_df
        self._current_idx = current_idx
        self._position = position if position is not None else PositionView()
        self._account = account if account is not None else AccountView()

    @property
    def current_bar(self) -> pd.Series:
        """
        Returns a detached copy of the completed bar at the current index i.
        Modifying this Series will not mutate the engine's underlying market data.
        """
        return self._df.iloc[self._current_idx].copy()

    @property
    def timestamp(self) -> pd.Timestamp:
        """Timestamp of the current bar."""
        return self._df["timestamp"].iloc[self._current_idx]

    @property
    def current_index(self) -> int:
        """Current bar index within the simulation sequence."""
        return self._current_idx

    @property
    def position(self) -> PositionView:
        """Read-only snapshot of the current position state."""
        return self._position

    @property
    def account(self) -> AccountView:
        """Read-only snapshot of the account state."""
        return self._account

    def history(self, n_bars: Optional[int] = None) -> pd.DataFrame:
        """
        Returns historical bars up to and including the current bar at index i.

        Guarantees:
        - Never returns future candles (indices > current_idx).
        - If n_bars is None, returns all bars from start (0) up to current_idx.
        - If n_bars is specified, returns the most recent n_bars up to current_idx.
          If n_bars exceeds available history, returns all available history up to current_idx.
        - Returns a detached deep copy; modifications do not affect engine data.

        Raises:
        - ValueError: If n_bars is not a positive integer.
        """
        if n_bars is not None:
            if not isinstance(n_bars, int) or n_bars <= 0:
                raise ValueError(f"n_bars must be a positive integer, got: {n_bars}")
            start_idx = max(0, self._current_idx + 1 - n_bars)
        else:
            start_idx = 0

        # Slice strictly up to current_idx + 1 and return a deep copy
        return self._df.iloc[start_idx : self._current_idx + 1].copy(deep=True)
