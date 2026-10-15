import pytest

from src.execution import EngineConfig, EngineConfigError


def test_valid_fraction_config():
    config = EngineConfig(initial_capital=100_000.0, risk_fraction=0.01, quantity_step=1.0)
    assert config.risk_fraction == 0.01
    assert config.commission_per_fill == 0.0
    assert config.slippage_fraction == 0.0


def test_valid_absolute_config():
    config = EngineConfig(initial_capital=50_000.0, risk_absolute=500.0, quantity_step=0.1)
    assert config.risk_absolute == 500.0


def test_risk_mode_is_mutually_exclusive_and_required():
    with pytest.raises(EngineConfigError, match="Exactly one"):
        EngineConfig(initial_capital=10_000.0, risk_fraction=0.01, risk_absolute=100.0, quantity_step=1.0)
    with pytest.raises(EngineConfigError, match="Exactly one"):
        EngineConfig(initial_capital=10_000.0, quantity_step=1.0)


def test_initial_capital_must_be_positive():
    with pytest.raises(EngineConfigError, match="initial_capital"):
        EngineConfig(initial_capital=0.0, risk_fraction=0.01, quantity_step=1.0)
    with pytest.raises(EngineConfigError, match="initial_capital"):
        EngineConfig(initial_capital=-5.0, risk_fraction=0.01, quantity_step=1.0)


def test_risk_fraction_range():
    with pytest.raises(EngineConfigError, match="risk_fraction"):
        EngineConfig(initial_capital=10_000.0, risk_fraction=0.0, quantity_step=1.0)
    with pytest.raises(EngineConfigError, match="risk_fraction"):
        EngineConfig(initial_capital=10_000.0, risk_fraction=1.5, quantity_step=1.0)


def test_risk_absolute_positive():
    with pytest.raises(EngineConfigError, match="risk_absolute"):
        EngineConfig(initial_capital=10_000.0, risk_absolute=0.0, quantity_step=1.0)


def test_commission_and_slippage_ranges():
    with pytest.raises(EngineConfigError, match="commission_per_fill"):
        EngineConfig(initial_capital=10_000.0, risk_fraction=0.01, quantity_step=1.0, commission_per_fill=-1.0)
    with pytest.raises(EngineConfigError, match="slippage_fraction"):
        EngineConfig(initial_capital=10_000.0, risk_fraction=0.01, quantity_step=1.0, slippage_fraction=1.0)


def test_quantity_step_is_not_defaulted():
    # Missing / non-positive steps are valid configuration; the engine rejects entries.
    EngineConfig(initial_capital=10_000.0, risk_fraction=0.01)
    EngineConfig(initial_capital=10_000.0, risk_fraction=0.01, quantity_step=0.0)
    EngineConfig(initial_capital=10_000.0, risk_fraction=0.01, quantity_step=-1.0)


def test_non_numeric_fields_rejected():
    with pytest.raises(EngineConfigError, match="initial_capital"):
        EngineConfig(initial_capital="1000", risk_fraction=0.01, quantity_step=1.0)  # type: ignore[arg-type]
    with pytest.raises(EngineConfigError, match="risk_fraction"):
        EngineConfig(initial_capital=1000.0, risk_fraction=float("inf"), quantity_step=1.0)
    with pytest.raises(EngineConfigError, match="quantity_step"):
        EngineConfig(initial_capital=1000.0, risk_fraction=0.01, quantity_step="1")  # type: ignore[arg-type]
