import pytest

from src.execution.sizing import SizingRejection, compute_quantity


def test_exact_quantity_no_commission():
    quantity, reason = compute_quantity(
        fill_price=100.0, stop_loss=90.0, risk_budget=1000.0, commission_per_fill=0.0, quantity_step=1.0
    )
    assert reason is None
    assert quantity == 100.0  # distance 10 -> 1000 / 10


def test_rounds_down_never_up():
    quantity, reason = compute_quantity(
        fill_price=100.0, stop_loss=93.0, risk_budget=1000.0, commission_per_fill=0.0, quantity_step=1.0
    )
    assert reason is None
    assert quantity == 142.0  # 1000 / 7 = 142.857 -> floor


def test_commission_subtracted_from_budget():
    quantity, reason = compute_quantity(
        fill_price=100.0, stop_loss=90.0, risk_budget=1000.0, commission_per_fill=5.0, quantity_step=1.0
    )
    assert reason is None
    # (1000 - 2*5) / 10 = 99
    assert quantity == 99.0


def test_missing_step_rejected():
    quantity, reason = compute_quantity(100.0, 90.0, 1000.0, 0.0, None)
    assert quantity is None
    assert reason == SizingRejection.MISSING_QUANTITY_STEP


def test_non_positive_step_rejected():
    quantity, reason = compute_quantity(100.0, 90.0, 1000.0, 0.0, 0.0)
    assert quantity is None
    assert reason == SizingRejection.NON_POSITIVE_QUANTITY_STEP

    quantity, reason = compute_quantity(100.0, 90.0, 1000.0, 0.0, -1.0)
    assert quantity is None
    assert reason == SizingRejection.NON_POSITIVE_QUANTITY_STEP


def test_zero_distance_rejected():
    quantity, reason = compute_quantity(100.0, 100.0, 1000.0, 0.0, 1.0)
    assert quantity is None
    assert reason == SizingRejection.NON_POSITIVE_STOP_DISTANCE


def test_zero_quantity_rejected():
    # Budget far smaller than one step of price risk.
    quantity, reason = compute_quantity(100.0, 0.0, 1.0, 0.0, 1000.0)
    assert quantity is None
    assert reason == SizingRejection.ZERO_QUANTITY


def test_budget_not_exceeding_costs_rejected():
    quantity, reason = compute_quantity(100.0, 90.0, 10.0, 5.0, 1.0)
    assert quantity is None
    assert reason == SizingRejection.RISK_BUDGET_TOO_SMALL


@pytest.mark.parametrize(
    "steps, step",
    [(3, 0.1), (7, 0.1), (1, 0.001)],
)
def test_representation_safe_rounding(steps, step):
    # distance == 1.0, so raw_quantity == budget == steps * step (an exact multiple).
    budget = steps * step
    quantity, reason = compute_quantity(
        fill_price=1.0, stop_loss=0.0, risk_budget=budget, commission_per_fill=0.0, quantity_step=step
    )
    assert reason is None
    assert quantity == pytest.approx(steps * step)


def test_representation_safe_common_case():
    # 0.3 / 0.1 == 2.9999999999999996 in binary floating point; must not drop a step.
    quantity, reason = compute_quantity(1.0, 0.0, 0.3, 0.0, 0.1)
    assert reason is None
    assert quantity == pytest.approx(0.3)
