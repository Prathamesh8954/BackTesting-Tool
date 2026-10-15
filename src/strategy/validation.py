import math
from typing import Optional
import numpy as np
from src.strategy.models import OrderAction, OrderType, StrategyDecision


class StrategyValidationError(ValueError):
    """Raised when a strategy decision violates structural validation rules."""
    pass


def _validate_price(price: Optional[float], field_name: str) -> None:
    """Validates that an optional price, if provided, is a strictly positive finite number."""
    if price is None:
        return

    if not isinstance(price, (int, float)) or isinstance(price, bool):
        raise StrategyValidationError(
            f"Field '{field_name}' must be a numeric value, got {type(price).__name__}."
        )

    if not np.isfinite(price):
        raise StrategyValidationError(
            f"Field '{field_name}' must be finite, got {price}."
        )

    if price <= 0.0:
        raise StrategyValidationError(
            f"Field '{field_name}' must be strictly positive (> 0.0), got {price}."
        )


def validate_decision(decision: StrategyDecision) -> None:
    """
    Performs structural validation on a StrategyDecision.

    Rules Enforced:
    1. Valid Action & Order Type: Must be valid enum instances.
    2. Numerical Prices: Any provided limit_price, stop_loss, or take_profit must be > 0.0 and finite.
    3. Action-Field Compatibility:
       - ENTER_LONG / ENTER_SHORT:
         * MARKET orders must not specify limit_price.
         * LIMIT orders require a positive finite limit_price.
         * If both stop_loss and take_profit are provided on ENTER_LONG, stop_loss < take_profit.
         * If both stop_loss and take_profit are provided on ENTER_SHORT, stop_loss > take_profit.
       - EXIT:
         * Cannot specify stop_loss or take_profit.
         * MARKET exit must not specify limit_price.
         * LIMIT exit requires limit_price.
       - MODIFY_PROTECTION:
         * Cannot specify limit_price.
         * Must specify at least one of stop_loss or take_profit.
    
    Explicit Boundaries:
    - Avoids validating assumptions that depend on execution simulation, current position,
      live fill prices, or account state (which are handled by the execution engine in Milestone 3).
    """
    if not isinstance(decision, StrategyDecision):
        raise StrategyValidationError(
            f"Expected StrategyDecision, got {type(decision).__name__}."
        )

    if not isinstance(decision.action, OrderAction):
        raise StrategyValidationError(
            f"Invalid action: {decision.action}. Must be an OrderAction enum."
        )

    if not isinstance(decision.order_type, OrderType):
        raise StrategyValidationError(
            f"Invalid order_type: {decision.order_type}. Must be an OrderType enum."
        )

    # Validate individual prices for positivity and finiteness
    _validate_price(decision.limit_price, "limit_price")
    _validate_price(decision.stop_loss, "stop_loss")
    _validate_price(decision.take_profit, "take_profit")

    action = decision.action
    order_type = decision.order_type

    # 1. Entry validation (ENTER_LONG, ENTER_SHORT)
    if action in (OrderAction.ENTER_LONG, OrderAction.ENTER_SHORT):
        if order_type == OrderType.MARKET and decision.limit_price is not None:
            raise StrategyValidationError(
                f"limit_price cannot be specified for MARKET {action.value} order."
            )
        if order_type == OrderType.LIMIT and decision.limit_price is None:
            raise StrategyValidationError(
                f"limit_price is required for LIMIT {action.value} order."
            )

        # Check contradictory entry brackets
        if decision.stop_loss is not None and decision.take_profit is not None:
            if action == OrderAction.ENTER_LONG and decision.stop_loss >= decision.take_profit:
                raise StrategyValidationError(
                    f"Contradictory bracket on ENTER_LONG: stop_loss ({decision.stop_loss}) "
                    f"must be strictly less than take_profit ({decision.take_profit})."
                )
            if action == OrderAction.ENTER_SHORT and decision.stop_loss <= decision.take_profit:
                raise StrategyValidationError(
                    f"Contradictory bracket on ENTER_SHORT: stop_loss ({decision.stop_loss}) "
                    f"must be strictly greater than take_profit ({decision.take_profit})."
                )

    # 2. Exit validation (EXIT)
    elif action == OrderAction.EXIT:
        if decision.stop_loss is not None or decision.take_profit is not None:
            raise StrategyValidationError(
                "EXIT decision cannot specify stop_loss or take_profit."
            )
        if order_type == OrderType.MARKET and decision.limit_price is not None:
            raise StrategyValidationError(
                "limit_price cannot be specified for MARKET EXIT order."
            )
        if order_type == OrderType.LIMIT and decision.limit_price is None:
            raise StrategyValidationError(
                "limit_price is required for LIMIT EXIT order."
            )

    # 3. Protection update validation (MODIFY_PROTECTION)
    elif action == OrderAction.MODIFY_PROTECTION:
        if decision.limit_price is not None:
            raise StrategyValidationError(
                "MODIFY_PROTECTION decision cannot specify limit_price."
            )
        if decision.stop_loss is None and decision.take_profit is None:
            raise StrategyValidationError(
                "MODIFY_PROTECTION requires at least one of stop_loss or take_profit."
            )
