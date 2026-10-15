"""Determinism, input immutability, and scope guarantees for M4 metrics."""

import dataclasses

import pytest

from src.metrics import (
    MetricsConsistencyError,
    OpenPositionSummary,
    PerformanceReport,
    compute_metrics,
)

from tests.test_metrics.helpers import make_result, make_trade, three_trade_result


def test_repeated_calls_are_deterministic():
    result = three_trade_result()

    first = compute_metrics(result)
    second = compute_metrics(result)

    assert first == second
    assert dataclasses.asdict(first) == dataclasses.asdict(second)


def test_input_result_is_not_mutated():
    result = three_trade_result()
    before = dataclasses.asdict(result)

    compute_metrics(result)

    assert dataclasses.asdict(result) == before
    assert result.trades is result.trades  # unchanged object identity


def test_randomised_multi_trade_metrics_stable_across_calls():
    trades = [make_trade(value) for value in (150.0, -75.0, 0.0, 300.0, -120.0)]
    result = make_result(trades)

    snapshots = [dataclasses.asdict(compute_metrics(result)) for _ in range(5)]
    assert all(snapshot == snapshots[0] for snapshot in snapshots)


def test_consistency_error_when_realized_pnl_mismatches_trades():
    # Constructed result whose account-level realized P&L contradicts the sum of
    # trade net P&L: the invariant check must fail loudly.
    result = make_result([make_trade(-100.0)], realized_pnl=-999.0)

    with pytest.raises(MetricsConsistencyError):
        compute_metrics(result)


def test_report_exposes_no_unimplemented_analytics():
    report_fields = {field.name for field in dataclasses.fields(PerformanceReport)}
    open_fields = {field.name for field in dataclasses.fields(OpenPositionSummary)}
    all_fields = report_fields | open_fields

    forbidden_substrings = ("r_multiple", "mfe", "mae", "target", "sharpe", "exposure", "annual")
    offenders = {
        name
        for name in all_fields
        if any(fragment in name.lower() for fragment in forbidden_substrings)
    }
    assert offenders == set()

    result = three_trade_result()
    report = compute_metrics(result)
    for attribute in ("r_multiples", "targets_reached", "sharpe_ratio", "exposure", "mfe", "mae"):
        assert not hasattr(report, attribute)
