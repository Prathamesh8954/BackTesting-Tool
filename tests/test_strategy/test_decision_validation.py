import pytest
from src.strategy.models import OrderAction, OrderType, StrategyDecision
from src.strategy.validation import StrategyValidationError, validate_decision


def test_valid_entry_decisions():
    """Verifies that well-formed entry decisions pass structural validation."""
    # Market entry with no bracket
    d1 = StrategyDecision(action=OrderAction.ENTER_LONG)
    validate_decision(d1)

    # Market entry with valid bracket
    d2 = StrategyDecision(
        action=OrderAction.ENTER_LONG,
        stop_loss=95.0,
        take_profit=110.0,
        tag="trend_follow",
    )
    validate_decision(d2)

    # Limit entry with valid bracket
    d3 = StrategyDecision(
        action=OrderAction.ENTER_SHORT,
        order_type=OrderType.LIMIT,
        limit_price=105.0,
        stop_loss=115.0,
        take_profit=90.0,
    )
    validate_decision(d3)


def test_valid_exit_and_protection_decisions():
    """Verifies that well-formed exit and protection update decisions pass."""
    # Market exit
    validate_decision(StrategyDecision(action=OrderAction.EXIT))

    # Limit exit
    validate_decision(
        StrategyDecision(action=OrderAction.EXIT, order_type=OrderType.LIMIT, limit_price=110.0)
    )

    # Modify protection with SL only
    validate_decision(StrategyDecision(action=OrderAction.MODIFY_PROTECTION, stop_loss=100.0))

    # Modify protection with TP only
    validate_decision(StrategyDecision(action=OrderAction.MODIFY_PROTECTION, take_profit=120.0))

    # Modify protection with both
    validate_decision(
        StrategyDecision(
            action=OrderAction.MODIFY_PROTECTION, stop_loss=100.0, take_profit=130.0
        )
    )


def test_non_positive_and_non_finite_prices():
    """Verifies that prices <= 0, inf, -inf, nan, or strings are rejected."""
    # Zero or negative limit price
    with pytest.raises(StrategyValidationError, match="strictly positive"):
        validate_decision(
            StrategyDecision(
                action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=0.0
            )
        )

    with pytest.raises(StrategyValidationError, match="strictly positive"):
        validate_decision(
            StrategyDecision(
                action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT, limit_price=-5.0
            )
        )

    # Non-finite stop loss (inf, -inf, nan)
    with pytest.raises(StrategyValidationError, match="must be finite"):
        validate_decision(
            StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=float("inf"))
        )

    with pytest.raises(StrategyValidationError, match="must be finite"):
        validate_decision(
            StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=float("-inf"))
        )

    with pytest.raises(StrategyValidationError, match="must be finite"):
        validate_decision(
            StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss=float("nan"))
        )

    # String price
    with pytest.raises(StrategyValidationError, match="must be a numeric value"):
        validate_decision(
            StrategyDecision(action=OrderAction.ENTER_LONG, stop_loss="100.0")  # type: ignore
        )


def test_incompatible_limit_price_combinations():
    """Verifies that limit_price is rejected on market orders and required on limit orders."""
    # Market order with limit_price
    with pytest.raises(StrategyValidationError, match="limit_price cannot be specified for MARKET"):
        validate_decision(
            StrategyDecision(action=OrderAction.ENTER_LONG, limit_price=100.0)
        )

    # Limit order without limit_price
    with pytest.raises(StrategyValidationError, match="limit_price is required for LIMIT"):
        validate_decision(
            StrategyDecision(action=OrderAction.ENTER_LONG, order_type=OrderType.LIMIT)
        )

    # Exit limit order without limit_price
    with pytest.raises(StrategyValidationError, match="limit_price is required for LIMIT"):
        validate_decision(
            StrategyDecision(action=OrderAction.EXIT, order_type=OrderType.LIMIT)
        )

    # Exit market order with limit_price
    with pytest.raises(StrategyValidationError, match="limit_price cannot be specified for MARKET"):
        validate_decision(
            StrategyDecision(action=OrderAction.EXIT, limit_price=105.0)
        )


def test_incompatible_exit_and_modify_protection_fields():
    """Verifies that EXIT cannot specify protection and MODIFY_PROTECTION requires protection."""
    # Exit specifying stop_loss or take_profit
    with pytest.raises(StrategyValidationError, match="EXIT decision cannot specify stop_loss"):
        validate_decision(StrategyDecision(action=OrderAction.EXIT, stop_loss=90.0))

    with pytest.raises(StrategyValidationError, match="EXIT decision cannot specify stop_loss"):
        validate_decision(StrategyDecision(action=OrderAction.EXIT, take_profit=110.0))

    # Modify protection specifying limit_price
    with pytest.raises(StrategyValidationError, match="cannot specify limit_price"):
        validate_decision(
            StrategyDecision(
                action=OrderAction.MODIFY_PROTECTION, stop_loss=100.0, limit_price=105.0
            )
        )

    # Modify protection without any stop_loss or take_profit
    with pytest.raises(StrategyValidationError, match="requires at least one of stop_loss or take_profit"):
        validate_decision(StrategyDecision(action=OrderAction.MODIFY_PROTECTION))


def test_contradictory_entry_brackets():
    """Verifies that contradictory entry brackets (e.g. SL >= TP on long) are rejected."""
    # Long: stop_loss >= take_profit is invalid
    with pytest.raises(StrategyValidationError, match="Contradictory bracket on ENTER_LONG"):
        validate_decision(
            StrategyDecision(
                action=OrderAction.ENTER_LONG,
                stop_loss=110.0,
                take_profit=100.0,
            )
        )

    with pytest.raises(StrategyValidationError, match="Contradictory bracket on ENTER_LONG"):
        validate_decision(
            StrategyDecision(
                action=OrderAction.ENTER_LONG,
                stop_loss=100.0,
                take_profit=100.0,
            )
        )

    # Short: stop_loss <= take_profit is invalid
    with pytest.raises(StrategyValidationError, match="Contradictory bracket on ENTER_SHORT"):
        validate_decision(
            StrategyDecision(
                action=OrderAction.ENTER_SHORT,
                stop_loss=90.0,
                take_profit=110.0,
            )
        )

    with pytest.raises(StrategyValidationError, match="Contradictory bracket on ENTER_SHORT"):
        validate_decision(
            StrategyDecision(
                action=OrderAction.ENTER_SHORT,
                stop_loss=100.0,
                take_profit=100.0,
            )
        )


def test_invalid_decision_type():
    """Verifies that passing non-StrategyDecision objects raises StrategyValidationError."""
    with pytest.raises(StrategyValidationError, match="Expected StrategyDecision"):
        validate_decision("not a decision")  # type: ignore
