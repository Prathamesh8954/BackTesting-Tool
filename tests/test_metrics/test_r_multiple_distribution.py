"""Milestone 45: binned R-multiple distribution analytics.

Approved M45 contract under test:

* Default edges are ``(-3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0)``.
* Bins are half-open ``[lower, upper)`` **except** the final bin, which also
  includes its upper edge (``[lower, upper]``).
* Values strictly outside the edge range are counted separately in
  ``below_range_count`` / ``above_range_count`` and are never clamped/discarded.
* Undefined R-multiples come from ``trade_r_multiple`` (the single source of
  R-multiple semantics) and are counted as non-computable, never binned.
* The invariant ``computable_count == sum(bins) + below + above`` always holds.
* Invalid edges raise ``RMultipleDistributionError`` and are never repaired.
"""

from __future__ import annotations

import copy
import dataclasses

import pytest

from src.metrics import (
    DEFAULT_R_BIN_EDGES,
    RMultipleBin,
    RMultipleDistribution,
    RMultipleDistributionError,
    compute_r_multiple_distribution,
    trade_r_multiple,
)

from tests.test_metrics.helpers import make_trade


def _trade_for_r(r_multiple: float):
    """Builds a trade whose R-multiple is exactly ``r_multiple``.

    Entry 100 / initial stop 90 / quantity 1 -> initial risk ``10``, so a net
    P&L of ``10 * r_multiple`` yields the requested R-multiple.
    """
    return make_trade(10.0 * r_multiple, entry_price=100.0, initial_stop=90.0, quantity=1.0)


def _undefined_trade():
    """A completed trade with no initial stop, so its R-multiple is ``None``."""
    return make_trade(100.0, entry_price=100.0, initial_stop=None, quantity=1.0)


def _counts(distribution: RMultipleDistribution) -> list[int]:
    return [bin.count for bin in distribution.bins]


def _invariant_holds(distribution: RMultipleDistribution) -> bool:
    return (
        distribution.computable_count
        == sum(bin.count for bin in distribution.bins)
        + distribution.below_range_count
        + distribution.above_range_count
    )


# ----------------------------------------------------------------- fixtures / shape


def test_default_edges_are_the_approved_values():
    assert DEFAULT_R_BIN_EDGES == (-3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0)
    distribution = compute_r_multiple_distribution([_trade_for_r(0.0)])
    assert len(distribution.bins) == len(DEFAULT_R_BIN_EDGES) - 1 == 8
    assert [(b.lower, b.upper) for b in distribution.bins] == list(
        zip(DEFAULT_R_BIN_EDGES, DEFAULT_R_BIN_EDGES[1:])
    )
    assert all(isinstance(b, RMultipleBin) for b in distribution.bins)


def test_bins_expose_edge_pairs_for_custom_edges():
    distribution = compute_r_multiple_distribution([_trade_for_r(0.0)], edges=(0.0, 1.0, 2.0))
    assert [(b.lower, b.upper) for b in distribution.bins] == [(0.0, 1.0), (1.0, 2.0)]


# ------------------------------------------------------------- boundaries / edges


def test_bin_boundaries_are_lower_inclusive_and_upper_exclusive():
    values = [-2.5, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, -3.0, 3.0]
    distribution = compute_r_multiple_distribution([_trade_for_r(value) for value in values])
    # bin0: -3.0, -2.5 ; bin7: 2.0, 3.0 ; every interior edge lands in its own bin
    assert _counts(distribution) == [2, 1, 1, 1, 1, 1, 1, 2]
    assert distribution.computable_count == 10
    assert distribution.below_range_count == 0
    assert distribution.above_range_count == 0


def test_exact_interior_edge_lands_in_bin_starting_at_that_edge():
    # -2.0 belongs to [-2, -1) (index 1), not [-3, -2) (index 0).
    distribution = compute_r_multiple_distribution([_trade_for_r(-2.0)])
    assert _counts(distribution) == [0, 1, 0, 0, 0, 0, 0, 0]


def test_first_edge_value_lands_in_the_first_bin():
    distribution = compute_r_multiple_distribution([_trade_for_r(-3.0)])
    assert _counts(distribution) == [1, 0, 0, 0, 0, 0, 0, 0]
    assert distribution.below_range_count == 0


def test_last_edge_value_lands_in_the_final_bin():
    distribution = compute_r_multiple_distribution([_trade_for_r(3.0)])
    assert _counts(distribution) == [0, 0, 0, 0, 0, 0, 0, 1]
    assert distribution.above_range_count == 0


def test_value_inside_a_bin_is_counted_once():
    distribution = compute_r_multiple_distribution([_trade_for_r(1.5), _trade_for_r(-0.25)])
    # 1.5 -> [1, 2) index 6 ; -0.25 -> [-0.5, 0) index 3
    assert _counts(distribution) == [0, 0, 0, 1, 0, 0, 1, 0]


# ---------------------------------------------------------- underflow / overflow


def test_values_outside_the_range_are_counted_separately_not_clamped():
    distribution = compute_r_multiple_distribution([_trade_for_r(-3.5), _trade_for_r(3.5)])
    assert _counts(distribution) == [0, 0, 0, 0, 0, 0, 0, 0]
    assert distribution.below_range_count == 1
    assert distribution.above_range_count == 1
    assert distribution.computable_count == 2
    assert _invariant_holds(distribution)


# ---------------------------------------------------------------- undefined values


def test_undefined_values_are_non_computable_and_never_binned():
    distribution = compute_r_multiple_distribution(
        [_trade_for_r(1.0), _undefined_trade(), _undefined_trade()]
    )
    assert _counts(distribution) == [0, 0, 0, 0, 0, 0, 1, 0]
    assert distribution.computable_count == 1
    assert distribution.non_computable_count == 2
    assert _invariant_holds(distribution)


def test_non_finite_or_zero_risk_inputs_are_non_computable():
    non_finite = make_trade(10.0, entry_price=float("inf"), initial_stop=90.0)
    zero_risk = make_trade(10.0, entry_price=100.0, initial_stop=100.0)
    assert trade_r_multiple(non_finite) is None
    assert trade_r_multiple(zero_risk) is None

    distribution = compute_r_multiple_distribution([non_finite, zero_risk])
    assert distribution.computable_count == 0
    assert distribution.non_computable_count == 2
    assert all(bin.count == 0 for bin in distribution.bins)
    assert _invariant_holds(distribution)


# ------------------------------------------------------------ empty / all undefined


def test_empty_input_yields_zero_count_bins():
    distribution = compute_r_multiple_distribution([])
    assert _counts(distribution) == [0] * 8
    assert distribution.computable_count == 0
    assert distribution.non_computable_count == 0
    assert distribution.below_range_count == 0
    assert distribution.above_range_count == 0
    assert _invariant_holds(distribution)


def test_all_undefined_input_yields_zero_bins_and_all_non_computable():
    distribution = compute_r_multiple_distribution([_undefined_trade() for _ in range(3)])
    assert _counts(distribution) == [0] * 8
    assert distribution.computable_count == 0
    assert distribution.non_computable_count == 3
    assert _invariant_holds(distribution)


# ------------------------------------------------------------------- custom edges


def test_custom_edges_are_honoured():
    distribution = compute_r_multiple_distribution(
        [_trade_for_r(-1.0), _trade_for_r(-0.5), _trade_for_r(0.5), _trade_for_r(1.0)],
        edges=(-1.0, 0.0, 1.0),
    )
    assert [(b.lower, b.upper) for b in distribution.bins] == [(-1.0, 0.0), (0.0, 1.0)]
    # -1.0 and -0.5 -> bin0 ; 0.5 and 1.0 (final edge) -> bin1
    assert _counts(distribution) == [2, 2]
    assert distribution.below_range_count == 0
    assert distribution.above_range_count == 0


@pytest.mark.parametrize("edges", [(-1.0, 0.0, 1.0), [-1.0, 0.0, 1.0], (0.0, 1.0)])
def test_edges_accept_tuple_and_list(edges):
    distribution = compute_r_multiple_distribution([_trade_for_r(0.5)], edges=edges)
    assert isinstance(distribution.bins, tuple)
    assert sum(bin.count for bin in distribution.bins) == 1


# ------------------------------------------------------------------- invalid edges


@pytest.mark.parametrize(
    "edges",
    [
        (),  # no edges
        (0.0,),  # single edge
        (0.0, 0.0),  # equal -> not strictly increasing
        (1.0, 0.0),  # decreasing
        (0.0, float("nan")),  # non-finite
        (float("-inf"), 0.0),  # non-finite
        (0.0, float("inf")),  # non-finite
        (0.0, "1"),  # non-numeric
        (0.0, None),  # non-numeric
        (0.0, True),  # bool is rejected
    ],
)
def test_invalid_edges_raise_and_are_not_repaired(edges):
    with pytest.raises(RMultipleDistributionError):
        compute_r_multiple_distribution([_trade_for_r(0.0)], edges=edges)


def test_distribution_error_is_a_value_error_subclass():
    assert issubclass(RMultipleDistributionError, ValueError)


# ---------------------------------------------------- determinism / non-mutation


def test_result_is_deterministic_for_equal_inputs():
    trades = [_trade_for_r(value) for value in (-2.5, -0.5, 0.5, 1.5, 3.5)]
    assert compute_r_multiple_distribution(trades) == compute_r_multiple_distribution(trades)


def test_input_is_not_mutated():
    trades = [_trade_for_r(-4.0), _trade_for_r(-1.0), _trade_for_r(0.5), _trade_for_r(5.0)]
    snapshot = copy.deepcopy(trades)
    edges = (-3.0, 0.0, 3.0)

    compute_r_multiple_distribution(trades, edges=edges)

    assert trades == snapshot
    assert len(trades) == 4
    assert edges == (-3.0, 0.0, 3.0)


# ------------------------------------------------------------ accounting invariant


def test_accounting_invariant_holds_for_mixed_inputs():
    trades = [
        _trade_for_r(-4.0),  # below range
        _trade_for_r(-2.5),  # bin 0
        _trade_for_r(-0.5),  # bin 3
        _trade_for_r(0.25),  # bin 4
        _trade_for_r(2.5),  # bin 7
        _trade_for_r(4.0),  # above range
        _undefined_trade(),  # non-computable
    ]
    distribution = compute_r_multiple_distribution(trades)

    assert distribution.computable_count == 6
    assert distribution.non_computable_count == 1
    assert distribution.below_range_count == 1
    assert distribution.above_range_count == 1
    assert sum(bin.count for bin in distribution.bins) == 4
    assert _invariant_holds(distribution)


# ------------------------------------------------------------------- immutability


def test_result_types_are_frozen():
    distribution = compute_r_multiple_distribution([_trade_for_r(0.0)])
    with pytest.raises(dataclasses.FrozenInstanceError):
        distribution.computable_count = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        distribution.bins[0].count = 99  # type: ignore[misc]
