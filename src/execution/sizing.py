"""Risk-based position sizing at fill time (Milestone 3).

Implements the approved sizing rules:

* Quantity is computed only at **fill** time from the actual eligible fill price
  and the stop-loss distance (never from future prices at signal time).
* Estimated entry and stop-exit commissions are subtracted from the risk budget
  before dividing by price distance.
* The result is rounded **down** to the configured step; the step is never
  defaulted and a missing/non-positive step rejects the entry.
* Representation-safe arithmetic prevents a valid exact multiple from being
  rounded to zero by floating point error.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple


class SizingRejection:
    """A named reason an entry could not be sized."""

    NON_POSITIVE_STOP_DISTANCE = "NON_POSITIVE_STOP_DISTANCE"
    RISK_BUDGET_TOO_SMALL = "RISK_BUDGET_TOO_SMALL"
    MISSING_QUANTITY_STEP = "MISSING_QUANTITY_STEP"
    NON_POSITIVE_QUANTITY_STEP = "NON_POSITIVE_QUANTITY_STEP"
    ZERO_QUANTITY = "ZERO_QUANTITY"

    _MESSAGES = {
        NON_POSITIVE_STOP_DISTANCE: "Entry rejected: |fill - stop_loss| must be strictly positive.",
        RISK_BUDGET_TOO_SMALL: "Entry rejected: risk budget does not exceed estimated entry + stop-exit costs.",
        MISSING_QUANTITY_STEP: "Entry rejected: no quantity step was configured.",
        NON_POSITIVE_QUANTITY_STEP: "Entry rejected: quantity step must be strictly positive.",
        ZERO_QUANTITY: "Entry rejected: rounded quantity is zero.",
    }

    @classmethod
    def message(cls, reason: str) -> str:
        return cls._MESSAGES.get(reason, reason)


def _round_down_to_step(raw_quantity: float, step: float) -> int:
    """Returns the integer number of steps in ``raw_quantity``, rounded down.

    Uses ``round(ratio, 9)`` before flooring so that representation error in the
    division (for example ``0.3 / 0.1 == 2.9999999999999996``) cannot drop a
    legitimate exact multiple by a whole step.
    """
    ratio = raw_quantity / step
    return math.floor(round(ratio, 9))


def compute_quantity(
    fill_price: float,
    stop_loss: float,
    risk_budget: float,
    commission_per_fill: float,
    quantity_step: Optional[float],
) -> Tuple[Optional[float], Optional[str]]:
    """Computes the entry quantity.

    Returns:
        ``(quantity, None)`` on success, or ``(None, rejection_reason)`` when the
        entry cannot be sized. The caller is responsible for recording the
        rejection and continuing.
    """
    distance = abs(fill_price - stop_loss)
    if not distance > 0.0:
        return None, SizingRejection.NON_POSITIVE_STOP_DISTANCE

    estimated_costs = 2.0 * commission_per_fill
    if not risk_budget > estimated_costs:
        return None, SizingRejection.RISK_BUDGET_TOO_SMALL

    if quantity_step is None:
        return None, SizingRejection.MISSING_QUANTITY_STEP
    if not quantity_step > 0.0:
        return None, SizingRejection.NON_POSITIVE_QUANTITY_STEP

    raw_quantity = (risk_budget - estimated_costs) / distance
    steps = _round_down_to_step(raw_quantity, quantity_step)
    if steps <= 0:
        return None, SizingRejection.ZERO_QUANTITY

    return steps * quantity_step, None
