"""Execution engine configuration (Milestone 3).

This module is plumbing only: it defines the shape, types, and validation of the
engine's configuration. It deliberately encodes **no** trading rules. The
simulation rules themselves live in :mod:`src.execution.engine` and are recorded
in ``PROJECT_CONTEXT.md``.

Risk budget
-----------
Exactly one of ``risk_fraction`` (fraction of the equity snapshot at the signal
close) or ``risk_absolute`` (fixed cash budget) must be supplied. Absolute
budgets do not scale with equity.

Quantity precision
------------------
``quantity_step`` is the per-instrument lot increment. It is intentionally
allowed to be ``None`` or non-positive at the configuration level so the engine
can *reject* entries as required by the approved precision rule ("a missing or
non-positive step means the entry is rejected"). It is never defaulted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


class EngineConfigError(ValueError):
    """Raised when an :class:`EngineConfig` is structurally invalid."""


def _require_finite_number(value: object, name: str) -> float:
    """Returns ``value`` as a float after asserting it is a finite real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineConfigError(
            f"'{name}' must be a number, got {type(value).__name__}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise EngineConfigError(f"'{name}' must be finite, got {value}.")
    return number


@dataclass(frozen=True)
class EngineConfig:
    """Immutable, validated configuration for a single backtest run.

    Attributes:
        initial_capital: Starting cash. Must be strictly positive.
        risk_fraction: Fraction of the signal-close equity used as the per-trade
            risk budget (0 < fraction <= 1). Mutually exclusive with
            ``risk_absolute``.
        risk_absolute: Fixed cash risk budget per trade (> 0). Mutually
            exclusive with ``risk_fraction``.
        quantity_step: Per-instrument lot increment. ``None`` or a non-positive
            value causes entries to be rejected at fill (never defaulted).
        commission_per_fill: Absolute cash commission charged on every fill
            (entry and exit). Defaults to zero.
        slippage_fraction: Fraction of price applied against the trader on
            **market** fills only. Defaults to zero.
    """

    initial_capital: float
    risk_fraction: Optional[float] = None
    risk_absolute: Optional[float] = None
    quantity_step: Optional[float] = None
    commission_per_fill: float = 0.0
    slippage_fraction: float = 0.0

    def __post_init__(self) -> None:
        initial_capital = _require_finite_number(self.initial_capital, "initial_capital")
        if initial_capital <= 0.0:
            raise EngineConfigError(
                f"'initial_capital' must be strictly positive, got {self.initial_capital}."
            )

        has_fraction = self.risk_fraction is not None
        has_absolute = self.risk_absolute is not None
        if has_fraction == has_absolute:
            raise EngineConfigError(
                "Exactly one of 'risk_fraction' or 'risk_absolute' must be provided."
            )

        if has_fraction:
            fraction = _require_finite_number(self.risk_fraction, "risk_fraction")
            if not (0.0 < fraction <= 1.0):
                raise EngineConfigError(
                    f"'risk_fraction' must satisfy 0 < fraction <= 1, got {self.risk_fraction}."
                )

        if has_absolute:
            absolute = _require_finite_number(self.risk_absolute, "risk_absolute")
            if absolute <= 0.0:
                raise EngineConfigError(
                    f"'risk_absolute' must be strictly positive, got {self.risk_absolute}."
                )

        commission = _require_finite_number(
            self.commission_per_fill, "commission_per_fill"
        )
        if commission < 0.0:
            raise EngineConfigError(
                f"'commission_per_fill' must be non-negative, got {self.commission_per_fill}."
            )

        slippage = _require_finite_number(self.slippage_fraction, "slippage_fraction")
        if not (0.0 <= slippage < 1.0):
            raise EngineConfigError(
                f"'slippage_fraction' must satisfy 0 <= fraction < 1, got {self.slippage_fraction}."
            )

        # A missing or non-positive step is a *valid* config; the engine rejects
        # entries that require sizing. Only guard the numeric type here.
        if self.quantity_step is not None:
            _require_finite_number(self.quantity_step, "quantity_step")
