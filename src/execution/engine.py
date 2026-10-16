"""Milestone 3 execution simulation engine.

Deterministic, strategy-agnostic order execution over a validated OHLCV frame.
The engine consumes M2 strategy intent (``StrategyDecision``) and produces
immutable execution records (:mod:`src.execution.models`).

All simulation behaviour follows the approved rules recorded in
``PROJECT_CONTEXT.md``. The engine never exposes future candles to the strategy
and never fills a market order on the signal candle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.execution.config import EngineConfig
from src.execution.models import (
    BacktestResult,
    EquityPoint,
    Fill,
    FillKind,
    FillSide,
    Rejection,
    Trade,
    UnfilledOrder,
)
from src.execution.sizing import SizingRejection, compute_quantity
from src.strategy.base import Strategy
from src.strategy.context import StrategyContext
from src.strategy.models import AccountView, OrderAction, OrderType, PositionView, StrategyDecision
from src.strategy.validation import validate_decision


REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class RejectionReason:
    """Reason codes recorded when a decision or fill is refused."""

    ENTRY_WHILE_OPEN = "ENTRY_WHILE_OPEN"
    ENTRY_WHILE_WORKING = "ENTRY_WHILE_WORKING"
    MISSING_STOP_LOSS = "MISSING_STOP_LOSS"
    EXIT_WHILE_FLAT = "EXIT_WHILE_FLAT"
    EXTRA_WORKING_EXIT = "EXTRA_WORKING_EXIT"
    MODIFY_WHILE_FLAT = "MODIFY_WHILE_FLAT"
    WRONG_SIDE_STOP_LOSS_ENTRY = "WRONG_SIDE_STOP_LOSS_ENTRY"
    WRONG_SIDE_TAKE_PROFIT_ENTRY = "WRONG_SIDE_TAKE_PROFIT_ENTRY"
    TAKE_PROFIT_EQUALS_FILL = "TAKE_PROFIT_EQUALS_FILL"
    WRONG_SIDE_STOP_LOSS_MODIFICATION = "WRONG_SIDE_STOP_LOSS_MODIFICATION"
    WRONG_SIDE_TAKE_PROFIT_MODIFICATION = "WRONG_SIDE_TAKE_PROFIT_MODIFICATION"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"


@dataclass
class _Position:
    direction: str  # "LONG" or "SHORT"
    quantity: float
    entry_price: float
    entry_bar_index: int
    entry_timestamp: object
    stop_loss: Optional[float]
    take_profit: Optional[float]
    entry_commission: float
    initial_stop: Optional[float]
    tag: str


@dataclass
class _WorkingOrder:
    action: OrderAction
    order_type: OrderType
    limit_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    tag: str
    signal_bar_index: int
    signal_timestamp: object
    risk_budget: Optional[float] = None


class ExecutionEngine:
    """Single-run engine. Construct via :func:`run_backtest`."""

    def __init__(self, strategy: Strategy, df: pd.DataFrame, config: EngineConfig):
        self._strategy = strategy
        self._df = df
        self._config = config

        self._cash = 0.0
        self._position: Optional[_Position] = None
        self._working_entry: Optional[_WorkingOrder] = None
        self._working_exit: Optional[_WorkingOrder] = None
        self._staged_stop: Optional[float] = None
        self._staged_take_profit: Optional[float] = None
        self._realized_pnl = 0.0
        self._fills: list[Fill] = []
        self._trades: list[Trade] = []
        self._rejections: list[Rejection] = []
        self._unfilled: list[UnfilledOrder] = []
        self._equity_curve: list[EquityPoint] = []

    # ------------------------------------------------------------------ public

    def run(self) -> BacktestResult:
        self._validate_dataframe()
        self._strategy.on_start()
        self._cash = float(self._config.initial_capital)

        for i in range(len(self._df)):
            row = self._df.iloc[i]
            self._apply_staged_protection()

            # (1) working orders + attached SL/TP against this candle
            self._process_working_orders(i, row)

            # (2) mark-to-market at close
            equity = self._mark_to_market(row)

            # (3) strategy sees the completed candle after the close
            self._record_equity(i, row, equity)
            context = self._build_context(i, equity)
            decisions = self._strategy.on_bar(context)

            # (4) validate, queue new orders, stage protection modifications
            self._process_decisions(list(decisions), i, row, equity)

        self._strategy.on_finish()
        self._expire_orders()
        return self._build_result()

    # --------------------------------------------------------------- internals

    def _validate_dataframe(self) -> None:
        if self._df is None or self._df.empty:
            raise ValueError("Cannot run a backtest on an empty DataFrame.")
        missing = [column for column in REQUIRED_COLUMNS if column not in self._df.columns]
        if missing:
            raise ValueError(
                f"DataFrame is missing required column(s): {', '.join(sorted(missing))}."
            )

    def _apply_staged_protection(self) -> None:
        """Applies a protection modification staged on the previous candle.

        A ``MODIFY_PROTECTION`` requested after candle ``i`` is first eligible on
        candle ``i + 1``. Staging keeps the applied levels identical to that
        rule; validation uses the request candle's close as the mark for the
        stop-loss (rule 2) and the entry fill price for the take-profit (rule 4).
        """
        if self._position is None:
            self._staged_stop = None
            self._staged_take_profit = None
            return
        if self._staged_stop is not None:
            self._position.stop_loss = self._staged_stop
            self._staged_stop = None
        if self._staged_take_profit is not None:
            self._position.take_profit = self._staged_take_profit
            self._staged_take_profit = None

    def _process_working_orders(self, i: int, row: pd.Series) -> None:
        # Approved intrabar ordering: working orders first, then attached protection.
        if self._working_exit is not None:
            self._try_fill_exit(i, row)
        if self._working_entry is not None and self._position is None:
            self._try_fill_entry(i, row)
        if self._position is not None:
            self._process_protection(i, row)

    def _resolve_fill(
        self, order: _WorkingOrder, row: pd.Series, side: FillSide
    ) -> Optional[tuple[float, float]]:
        """Returns ``(fill_price, slippage_per_unit)`` or ``None`` if unfilled."""
        open_price = float(row["open"])
        if order.order_type == OrderType.MARKET:
            slip = self._config.slippage_fraction
            if side == FillSide.BUY:
                return open_price * (1.0 + slip), open_price * slip
            return open_price * (1.0 - slip), open_price * slip

        limit = order.limit_price
        if limit is None:
            return None
        if side == FillSide.BUY:
            if float(row["low"]) <= limit:
                return (open_price if open_price <= limit else limit), 0.0
            return None
        # SELL
        if float(row["high"]) >= limit:
            return (open_price if open_price >= limit else limit), 0.0
        return None

    def _try_fill_entry(self, i: int, row: pd.Series) -> None:
        order = self._working_entry
        assert order is not None
        side = FillSide.BUY if order.action == OrderAction.ENTER_LONG else FillSide.SELL
        resolved = self._resolve_fill(order, row, side)
        if resolved is None:
            return  # limit not touched; stays working
        fill_price, slippage_per_unit = resolved
        self._working_entry = None  # consumed regardless of outcome
        direction = "LONG" if order.action == OrderAction.ENTER_LONG else "SHORT"
        timestamp = row["timestamp"]

        if order.stop_loss is None:
            self._reject(RejectionReason.MISSING_STOP_LOSS, i, timestamp, order.tag)
            return

        if (direction == "LONG" and order.stop_loss > fill_price) or (
            direction == "SHORT" and order.stop_loss < fill_price
        ):
            self._reject(
                RejectionReason.WRONG_SIDE_STOP_LOSS_ENTRY,
                i,
                timestamp,
                order.tag,
                {"fill_price": fill_price, "stop_loss": order.stop_loss},
            )
            return

        if order.take_profit is not None:
            if (direction == "LONG" and order.take_profit < fill_price) or (
                direction == "SHORT" and order.take_profit > fill_price
            ):
                self._reject(
                    RejectionReason.WRONG_SIDE_TAKE_PROFIT_ENTRY,
                    i,
                    timestamp,
                    order.tag,
                    {"fill_price": fill_price, "take_profit": order.take_profit},
                )
                return
            if order.take_profit == fill_price:
                self._reject(
                    RejectionReason.TAKE_PROFIT_EQUALS_FILL,
                    i,
                    timestamp,
                    order.tag,
                    {"fill_price": fill_price},
                )
                return

        assert order.risk_budget is not None
        quantity, reason = compute_quantity(
            fill_price=fill_price,
            stop_loss=order.stop_loss,
            risk_budget=order.risk_budget,
            commission_per_fill=self._config.commission_per_fill,
            quantity_step=self._config.quantity_step,
        )
        if reason is not None:
            self._reject(reason, i, timestamp, order.tag, {"message": SizingRejection.message(reason)})
            return

        assert quantity is not None
        commission = self._config.commission_per_fill
        required_cash = quantity * fill_price + commission
        if self._cash < required_cash:
            self._reject(
                RejectionReason.INSUFFICIENT_CASH,
                i,
                timestamp,
                order.tag,
                {"required_cash": required_cash, "cash": self._cash, "quantity": quantity},
            )
            return

        if direction == "LONG":
            self._cash -= quantity * fill_price + commission
        else:
            self._cash += quantity * fill_price - commission

        self._position = _Position(
            direction=direction,
            quantity=quantity,
            entry_price=fill_price,
            entry_bar_index=i,
            entry_timestamp=timestamp,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            entry_commission=commission,
            initial_stop=order.stop_loss,
            tag=order.tag,
        )
        self._fills.append(
            Fill(
                kind=FillKind.ENTRY,
                side=side,
                direction=direction,
                quantity=quantity,
                price=fill_price,
                commission=commission,
                slippage=slippage_per_unit * quantity,
                bar_index=i,
                timestamp=timestamp,
                tag=order.tag,
            )
        )

    def _try_fill_exit(self, i: int, row: pd.Series) -> None:
        order = self._working_exit
        position = self._position
        assert order is not None and position is not None
        side = FillSide.SELL if position.direction == "LONG" else FillSide.BUY
        resolved = self._resolve_fill(order, row, side)
        if resolved is None:
            return  # limit not touched; stays working
        fill_price, slippage_per_unit = resolved
        self._working_exit = None
        self._close_position(
            i, row["timestamp"], fill_price, FillKind.EXIT, order.tag, slippage_per_unit
        )

    def _process_protection(self, i: int, row: pd.Series) -> None:
        position = self._position
        assert position is not None
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        stop = position.stop_loss
        target = position.take_profit

        if position.direction == "LONG":
            stop_hit = stop is not None and low <= stop
            target_hit = target is not None and high >= target
        else:
            stop_hit = stop is not None and high >= stop
            target_hit = target is not None and low <= target

        if stop_hit:
            # Stop-loss is processed before take-profit when both are touched.
            assert stop is not None
            fill_price = min(open_price, stop) if position.direction == "LONG" else max(open_price, stop)
            self._close_position(i, row["timestamp"], fill_price, FillKind.STOP_LOSS, "", 0.0)
            return

        if target_hit:
            assert target is not None
            if position.direction == "LONG":
                fill_price = open_price if open_price >= target else target
            else:
                fill_price = open_price if open_price <= target else target
            self._close_position(i, row["timestamp"], fill_price, FillKind.TAKE_PROFIT, "", 0.0)

    def _close_position(
        self,
        i: int,
        timestamp: object,
        exit_price: float,
        kind: FillKind,
        tag: str,
        slippage_per_unit: float,
    ) -> None:
        position = self._position
        assert position is not None
        direction = position.direction
        quantity = position.quantity
        commission = self._config.commission_per_fill
        side = FillSide.SELL if direction == "LONG" else FillSide.BUY

        if direction == "LONG":
            self._cash += quantity * exit_price - commission
            gross = quantity * (exit_price - position.entry_price)
        else:
            self._cash -= quantity * exit_price + commission
            gross = quantity * (position.entry_price - exit_price)
        net = gross - position.entry_commission - commission
        self._realized_pnl += net

        self._fills.append(
            Fill(
                kind=kind,
                side=side,
                direction=direction,
                quantity=quantity,
                price=exit_price,
                commission=commission,
                slippage=slippage_per_unit * quantity,
                bar_index=i,
                timestamp=timestamp,
                tag=tag or position.tag,
            )
        )
        self._trades.append(
            Trade(
                direction=direction,
                quantity=quantity,
                entry_price=position.entry_price,
                exit_price=exit_price,
                entry_bar_index=position.entry_bar_index,
                exit_bar_index=i,
                entry_timestamp=position.entry_timestamp,
                exit_timestamp=timestamp,
                entry_kind=FillKind.ENTRY,
                exit_kind=kind,
                entry_commission=position.entry_commission,
                exit_commission=commission,
                gross_pnl=gross,
                net_pnl=net,
                tag=position.tag,
                initial_stop=position.initial_stop,
            )
        )

        self._position = None
        self._working_exit = None
        self._staged_stop = None
        self._staged_take_profit = None

    def _process_decisions(
        self, decisions: list[StrategyDecision], i: int, row: pd.Series, equity: float
    ) -> None:
        timestamp = row["timestamp"]
        close = float(row["close"])

        for decision in decisions:
            # Structural validation failure aborts the entire run.
            validate_decision(decision)
            action = decision.action

            if action in (OrderAction.ENTER_LONG, OrderAction.ENTER_SHORT):
                if self._position is not None:
                    self._reject(RejectionReason.ENTRY_WHILE_OPEN, i, timestamp, decision.tag)
                elif self._working_entry is not None:
                    self._reject(RejectionReason.ENTRY_WHILE_WORKING, i, timestamp, decision.tag)
                elif decision.stop_loss is None:
                    self._reject(RejectionReason.MISSING_STOP_LOSS, i, timestamp, decision.tag)
                else:
                    self._working_entry = _WorkingOrder(
                        action=action,
                        order_type=decision.order_type,
                        limit_price=decision.limit_price,
                        stop_loss=decision.stop_loss,
                        take_profit=decision.take_profit,
                        tag=decision.tag,
                        signal_bar_index=i,
                        signal_timestamp=timestamp,
                        risk_budget=self._risk_budget(equity),
                    )

            elif action == OrderAction.EXIT:
                if self._position is None:
                    self._reject(RejectionReason.EXIT_WHILE_FLAT, i, timestamp, decision.tag)
                elif self._working_exit is not None:
                    self._reject(RejectionReason.EXTRA_WORKING_EXIT, i, timestamp, decision.tag)
                else:
                    self._working_exit = _WorkingOrder(
                        action=OrderAction.EXIT,
                        order_type=decision.order_type,
                        limit_price=decision.limit_price,
                        stop_loss=None,
                        take_profit=None,
                        tag=decision.tag,
                        signal_bar_index=i,
                        signal_timestamp=timestamp,
                    )

            elif action == OrderAction.MODIFY_PROTECTION:
                if self._position is None:
                    self._reject(RejectionReason.MODIFY_WHILE_FLAT, i, timestamp, decision.tag)
                else:
                    self._stage_modification(decision, i, timestamp, close)

    def _stage_modification(
        self, decision: StrategyDecision, i: int, timestamp: object, mark: float
    ) -> None:
        position = self._position
        assert position is not None
        direction = position.direction

        if decision.stop_loss is not None:
            stop_wrong_side = (
                direction == "LONG" and decision.stop_loss > mark
            ) or (direction == "SHORT" and decision.stop_loss < mark)
            if stop_wrong_side:
                self._reject(
                    RejectionReason.WRONG_SIDE_STOP_LOSS_MODIFICATION,
                    i,
                    timestamp,
                    decision.tag,
                    {"mark": mark, "stop_loss": decision.stop_loss},
                )
            else:
                self._staged_stop = decision.stop_loss

        if decision.take_profit is not None:
            # Rule 4 (amended): take-profit modifications are validated against the
            # position's original entry fill price, not the current market mark. This
            # is intentionally asymmetric with the stop-loss rule (rule 2) above.
            entry_price = position.entry_price
            target_wrong_side = (
                direction == "LONG" and decision.take_profit < entry_price
            ) or (direction == "SHORT" and decision.take_profit > entry_price)
            if target_wrong_side:
                self._reject(
                    RejectionReason.WRONG_SIDE_TAKE_PROFIT_MODIFICATION,
                    i,
                    timestamp,
                    decision.tag,
                    {"entry_price": entry_price, "take_profit": decision.take_profit},
                )
            else:
                self._staged_take_profit = decision.take_profit

    def _risk_budget(self, equity: float) -> float:
        if self._config.risk_fraction is not None:
            return equity * self._config.risk_fraction
        assert self._config.risk_absolute is not None
        return self._config.risk_absolute

    def _mark_to_market(self, row: pd.Series) -> float:
        if self._position is None:
            return self._cash
        close = float(row["close"])
        if self._position.direction == "LONG":
            return self._cash + self._position.quantity * close
        return self._cash - self._position.quantity * close

    def _record_equity(self, i: int, row: pd.Series, equity: float) -> None:
        position = self._position
        close = float(row["close"])
        if position is None:
            position_value = 0.0
            direction = None
            quantity = 0.0
        else:
            direction = position.direction
            quantity = position.quantity
            position_value = (
                position.quantity * close
                if direction == "LONG"
                else -position.quantity * close
            )
        self._equity_curve.append(
            EquityPoint(
                bar_index=i,
                timestamp=row["timestamp"],
                cash=self._cash,
                equity=equity,
                position_value=position_value,
                direction=direction,
                quantity=quantity,
            )
        )

    def _build_context(self, i: int, equity: float) -> StrategyContext:
        if self._position is None:
            position_view = PositionView()
        else:
            position = self._position
            position_view = PositionView(
                is_open=True,
                direction=position.direction,
                entry_price=position.entry_price,
                entry_timestamp=position.entry_timestamp,
                current_stop_loss=position.stop_loss,
                current_take_profit=position.take_profit,
                bars_held=i - position.entry_bar_index,
            )
        account_view = AccountView(
            cash=self._cash,
            equity=equity,
            initial_capital=float(self._config.initial_capital),
        )
        return StrategyContext(
            full_df=self._df,
            current_idx=i,
            position=position_view,
            account=account_view,
        )

    def _reject(
        self,
        reason: str,
        bar_index: int,
        timestamp: object,
        tag: str,
        details: Optional[dict] = None,
    ) -> None:
        self._rejections.append(
            Rejection(
                reason=reason,
                message=_REJECTION_MESSAGES.get(reason, reason),
                bar_index=bar_index,
                timestamp=timestamp,
                tag=tag or "",
                details=details or {},
            )
        )

    def _expire_orders(self) -> None:
        for order in (self._working_entry, self._working_exit):
            if order is None:
                continue
            self._unfilled.append(
                UnfilledOrder(
                    action=order.action.value,
                    order_type=order.order_type.value,
                    limit_price=order.limit_price,
                    queued_bar_index=order.signal_bar_index,
                    queued_timestamp=order.signal_timestamp,
                    tag=order.tag,
                )
            )
        self._working_entry = None
        self._working_exit = None

    def _build_result(self) -> BacktestResult:
        last_row = self._df.iloc[-1]
        last_close = float(last_row["close"])
        if self._position is None:
            final_equity = self._cash
            unrealized = 0.0
            is_flat = True
            open_direction = None
            open_quantity = 0.0
        else:
            position = self._position
            is_flat = False
            open_direction = position.direction
            open_quantity = position.quantity
            if position.direction == "LONG":
                unrealized = position.quantity * (last_close - position.entry_price)
                final_equity = self._cash + position.quantity * last_close
            else:
                unrealized = position.quantity * (position.entry_price - last_close)
                final_equity = self._cash - position.quantity * last_close

        return BacktestResult(
            initial_capital=float(self._config.initial_capital),
            final_cash=self._cash,
            final_equity=final_equity,
            realized_pnl=self._realized_pnl,
            unrealized_pnl=unrealized,
            bars_processed=len(self._df),
            is_flat=is_flat,
            open_direction=open_direction,
            open_quantity=open_quantity,
            fills=tuple(self._fills),
            trades=tuple(self._trades),
            rejections=tuple(self._rejections),
            unfilled_orders=tuple(self._unfilled),
            equity_curve=tuple(self._equity_curve),
        )


_REJECTION_MESSAGES = {
    RejectionReason.ENTRY_WHILE_OPEN: "Entry rejected: a position is already open.",
    RejectionReason.ENTRY_WHILE_WORKING: "Entry rejected: a working entry order already exists.",
    RejectionReason.MISSING_STOP_LOSS: "Entry rejected: a stop-loss is required.",
    RejectionReason.EXIT_WHILE_FLAT: "Exit rejected: no open position.",
    RejectionReason.EXTRA_WORKING_EXIT: "Exit rejected: a working exit order already exists.",
    RejectionReason.MODIFY_WHILE_FLAT: "Protection modification rejected: no open position.",
    RejectionReason.WRONG_SIDE_STOP_LOSS_ENTRY: "Entry rejected: stop-loss is on the wrong side of the fill.",
    RejectionReason.WRONG_SIDE_TAKE_PROFIT_ENTRY: "Entry rejected: take-profit is on the wrong side of the fill.",
    RejectionReason.TAKE_PROFIT_EQUALS_FILL: "Entry rejected: take-profit equals the fill price.",
    RejectionReason.WRONG_SIDE_STOP_LOSS_MODIFICATION: "Modification rejected: stop-loss is on the wrong side of the current mark.",
    RejectionReason.WRONG_SIDE_TAKE_PROFIT_MODIFICATION: "Modification rejected: take-profit is on the wrong side of the entry price.",
    RejectionReason.INSUFFICIENT_CASH: "Entry rejected: insufficient cash to fund the position.",
}


def run_backtest(strategy: Strategy, df: pd.DataFrame, config: EngineConfig) -> BacktestResult:
    """Runs a single deterministic backtest.

    Args:
        strategy: A fresh or resettable :class:`~src.strategy.base.Strategy`.
        df: Validated OHLCV data with the required columns.
        config: A validated :class:`~src.execution.config.EngineConfig`.

    Returns:
        An immutable :class:`~src.execution.models.BacktestResult`.
    """
    return ExecutionEngine(strategy, df, config).run()
