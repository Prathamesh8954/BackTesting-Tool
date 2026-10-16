"""Shared deterministic fixtures for Milestone 4 metrics tests."""

from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd

from src.execution import EngineConfig, run_backtest
from src.execution.models import BacktestResult, EquityPoint, FillKind, Trade
from src.strategy.models import OrderAction, StrategyDecision

from tests.test_execution.helpers import ScriptedStrategy, make_df


def _ts(index: int) -> pd.Timestamp:
    return pd.Timestamp("2026-01-01") + pd.Timedelta(hours=index)


def make_trade(
    net_pnl: float,
    *,
    gross_pnl: Optional[float] = None,
    direction: str = "LONG",
    quantity: float = 1.0,
    entry_price: float = 100.0,
    exit_price: float = 101.0,
    entry_bar_index: int = 0,
    exit_bar_index: int = 1,
    entry_commission: float = 0.0,
    exit_commission: float = 0.0,
    tag: str = "",
    initial_stop: Optional[float] = None,
) -> Trade:
    """Builds a :class:`Trade`. ``net_pnl`` defaults to ``gross - commissions``."""
    if gross_pnl is None:
        gross_pnl = net_pnl + entry_commission + exit_commission
    return Trade(
        direction=direction,
        quantity=quantity,
        entry_price=entry_price,
        exit_price=exit_price,
        entry_bar_index=entry_bar_index,
        exit_bar_index=exit_bar_index,
        entry_timestamp=_ts(entry_bar_index),
        exit_timestamp=_ts(exit_bar_index),
        entry_kind=FillKind.ENTRY,
        exit_kind=FillKind.EXIT,
        entry_commission=entry_commission,
        exit_commission=exit_commission,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        tag=tag,
        initial_stop=initial_stop,
    )


def make_result(
    trades: Sequence[Trade] = (),
    equity_prices: Optional[Sequence[float]] = None,
    *,
    initial_capital: float = 10_000.0,
    realized_pnl: Optional[float] = None,
    unrealized_pnl: float = 0.0,
    is_flat: bool = True,
    open_direction: Optional[str] = None,
    open_quantity: float = 0.0,
) -> BacktestResult:
    """Builds a synthetic, internally consistent :class:`BacktestResult`.

    Used for precise metric edge cases. ``realized_pnl`` defaults to the sum of
    the trades' ``net_pnl`` so the metrics consistency check holds.
    """
    trades = tuple(trades)
    if realized_pnl is None:
        realized_pnl = sum(trade.net_pnl for trade in trades)
    if equity_prices is None:
        equity_prices = (initial_capital, initial_capital + realized_pnl + unrealized_pnl)

    equity_curve = tuple(
        EquityPoint(
            bar_index=i,
            timestamp=_ts(i),
            cash=price,
            equity=price,
            position_value=0.0,
            direction=None,
            quantity=0.0,
        )
        for i, price in enumerate(equity_prices)
    )
    final_equity = equity_curve[-1].equity if equity_curve else initial_capital + realized_pnl + unrealized_pnl

    return BacktestResult(
        initial_capital=initial_capital,
        final_cash=final_equity,
        final_equity=final_equity,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        bars_processed=len(equity_curve),
        is_flat=is_flat,
        open_direction=open_direction,
        open_quantity=open_quantity,
        fills=(),
        trades=trades,
        rejections=(),
        unfilled_orders=(),
        equity_curve=equity_curve,
    )


# --------------------------------------------------------------------- scenarios

THREE_TRADE_ROWS = [
    (100.0, 102.0, 98.0, 100.0),  # bar 0
    (100.0, 108.0, 95.0, 105.0),  # bar 1: long entry fills at 100
    (110.0, 112.0, 109.0, 111.0),  # bar 2: long exit fills at 110
    (100.0, 105.0, 95.0, 100.0),  # bar 3: short entry fills at 100
    (120.0, 122.0, 118.0, 120.0),  # bar 4: short exit fills at 120
    (100.0, 108.0, 95.0, 105.0),  # bar 5: long entry fills at 100
    (90.0, 95.0, 88.0, 92.0),  # bar 6: long exit fills at 90
]


def three_trade_result() -> BacktestResult:
    """Long win (+1000), short loss (-2000), long loss (-1000).

    Engine config: initial capital 100_000, absolute risk 1000, step 1, zero
    commission/slippage. Each entry has a 10.0 stop distance, so quantity is
    the round number 100 on every trade.
    """
    df = make_df(THREE_TRADE_ROWS)
    script = {
        0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        1: [StrategyDecision(action=OrderAction.EXIT)],
        2: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)],
        3: [StrategyDecision(action=OrderAction.EXIT)],
        4: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)],
        5: [StrategyDecision(action=OrderAction.EXIT)],
    }
    config = EngineConfig(
        initial_capital=100_000.0,
        risk_absolute=1000.0,
        quantity_step=1.0,
    )
    return run_backtest(ScriptedStrategy(script), df, config)


def open_long_result() -> BacktestResult:
    """A long position still open at the end of the data.

    Risk budget 1010 with commission 5 gives ``(1010 - 2*5) / 10 = 100`` units
    at the 100.0 entry, so the entry commission is exactly 5.0.
    """
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),  # bar 0
        (100.0, 108.0, 95.0, 105.0),  # bar 1: long entry fills at 100
        (105.0, 110.0, 104.0, 108.0),  # bar 2: still open, close 108
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=90.0)]}
    config = EngineConfig(
        initial_capital=100_000.0,
        risk_absolute=1010.0,
        quantity_step=1.0,
        commission_per_fill=5.0,
    )
    return run_backtest(ScriptedStrategy(script), df, config)


def open_short_result() -> BacktestResult:
    """A short position still open at the end of the data (same sizing math)."""
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),  # bar 0
        (100.0, 98.0, 96.0, 97.0),  # bar 1: short entry fills at 100, close 97
    ])
    script = {0: [StrategyDecision(action=OrderAction.ENTER_SHORT, stop_loss=110.0)]}
    config = EngineConfig(
        initial_capital=100_000.0,
        risk_absolute=1010.0,
        quantity_step=1.0,
        commission_per_fill=5.0,
    )
    return run_backtest(ScriptedStrategy(script), df, config)


def do_nothing_result() -> BacktestResult:
    """A run with no decisions at all: no fills and no trades."""
    df = make_df([
        (100.0, 102.0, 98.0, 100.0),
        (100.0, 108.0, 95.0, 105.0),
    ])
    config = EngineConfig(
        initial_capital=100_000.0,
        risk_absolute=1000.0,
        quantity_step=1.0,
    )
    return run_backtest(ScriptedStrategy({}), df, config)
