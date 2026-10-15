"""Shared deterministic helpers for Milestone 3 execution tests."""

from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd

from src.strategy.base import Strategy
from src.strategy.context import StrategyContext
from src.strategy.models import StrategyDecision


def make_df(rows: Sequence[tuple[float, float, float, float]], start: str = "2026-01-01 09:30") -> pd.DataFrame:
    """Builds an OHLCV frame from ``(open, high, low, close)`` tuples."""
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=len(rows), freq="1h"),
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [1000.0] * len(rows),
        }
    )


class ScriptedStrategy(Strategy):
    """Emits a fixed list of decisions at specific bar indices."""

    def __init__(self, script: Optional[dict[int, Sequence[StrategyDecision]]] = None):
        self._script = {int(k): list(v) for k, v in (script or {}).items()}
        self.seen_indices: list[int] = []

    def on_start(self) -> None:
        self.seen_indices = []

    def on_bar(self, context: StrategyContext) -> Sequence[StrategyDecision]:
        self.seen_indices.append(context.current_index)
        return list(self._script.get(context.current_index, []))


def kinds(result) -> list[str]:
    """Returns the ordered fill kinds of a backtest result."""
    return [fill.kind.value for fill in result.fills]
