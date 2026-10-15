from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import pandas as pd


class OrderAction(str, Enum):
    """
    Action intended by a strategy decision.
    Note: An empty sequence of decisions represents 'no action' / hold.
    """
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT = "EXIT"
    MODIFY_PROTECTION = "MODIFY_PROTECTION"


class OrderType(str, Enum):
    """Order type requested by the strategy."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass(frozen=True)
class StrategyDecision:
    """
    Immutable intent emitted by a strategy during bar evaluation.

    Separation of concerns:
    - Represents strategy intent only (order request).
    - Contains no execution assumptions, fill prices, slippage, commission, or account mutation.
    """
    action: OrderAction
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    tag: str = ""


@dataclass(frozen=True)
class PositionView:
    """
    Immutable read-only snapshot of current position state.

    Conceptual Model:
    - Represents a single net position per instrument.
    - Multiple independent tickets, simultaneous hedging (long + short), and scaling
      into separate positions are not supported by this initial model.
    """
    is_open: bool = False
    direction: Optional[str] = None          # "LONG" or "SHORT"
    entry_price: Optional[float] = None
    entry_timestamp: Optional[pd.Timestamp] = None
    current_stop_loss: Optional[float] = None
    current_take_profit: Optional[float] = None
    bars_held: int = 0


@dataclass(frozen=True)
class AccountView:
    """
    Immutable read-only snapshot of account capital state.

    Note:
    - Minimal snapshot for strategy awareness.
    - Does not perform portfolio accounting or active P&L calculations in this milestone.
    """
    cash: float = 0.0
    equity: float = 0.0
    initial_capital: float = 0.0
