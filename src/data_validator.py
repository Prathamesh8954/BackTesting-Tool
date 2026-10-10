from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Union
import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class IssueDetail:
    """Represents a specific validation issue found in market data."""
    code: str
    message: str
    row_indices: tuple[Any, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    """Complete validation report distinguishing fatal errors from non-fatal warnings."""
    is_valid: bool
    errors: list[IssueDetail] = field(default_factory=list)
    warnings: list[IssueDetail] = field(default_factory=list)


def validate_market_data(
    df: pd.DataFrame,
    expected_interval: Optional[Union[str, pd.Timedelta]] = None,
) -> ValidationReport:
    """
    Validates market OHLCV data against deterministic correctness rules.

    Guarantees:
    - Never mutates the input DataFrame (no column changes, row drops, or in-place sorting).
    - Separates fatal errors (is_valid = False) from informational warnings (is_valid = True if no errors).
    - Never silently fills, repairs, or drops invalid records.
    - Accurately reports row indices for every detected issue.

    Checks:
    - Errors:
      * Missing required columns ('timestamp', 'open', 'high', 'low', 'close', 'volume')
      * Empty DataFrame
      * Null or NaN values in core fields (timestamp, open, high, low, close)
      * Unparseable timestamps
      * Duplicate timestamps
      * Non-chronological (unsorted) timestamps
      * Non-positive prices (<= 0.0)
      * OHLC geometric violations (high < low, high < open, high < close, low > open, low > close)
      * Negative volume (< 0.0)
    - Warnings:
      * Zero volume bars (volume == 0.0)
      * Missing/NaN volume values
      * Timestamp gaps exceeding normal intervals (e.g., weekends, holidays, halt periods)
    """
    errors: list[IssueDetail] = []
    warnings: list[IssueDetail] = []

    # 1. Check for empty DataFrame
    if df is None or df.empty:
        errors.append(
            IssueDetail(
                code="EMPTY_DATAFRAME",
                message="DataFrame is empty or None.",
            )
        )
        return ValidationReport(is_valid=False, errors=errors, warnings=warnings)

    # 2. Check required columns (case-insensitive check)
    existing_cols = {str(c).strip().lower(): c for c in df.columns}
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in existing_cols]

    if missing_cols:
        errors.append(
            IssueDetail(
                code="MISSING_COLUMNS",
                message=f"Missing required column(s): {', '.join(sorted(missing_cols))}",
                details={"missing_columns": sorted(missing_cols)},
            )
        )
        # If fundamental columns are missing, geometric checks cannot proceed safely
        return ValidationReport(is_valid=False, errors=errors, warnings=warnings)

    # Map column names as referenced in the DataFrame
    col_map = {c: existing_cols[c] for c in REQUIRED_COLUMNS}

    ts_col = col_map["timestamp"]
    open_col = col_map["open"]
    high_col = col_map["high"]
    low_col = col_map["low"]
    close_col = col_map["close"]
    vol_col = col_map["volume"]

    # 3. Check for null values in core fields (Fatal Errors)
    for c_name, c_key in [
        ("timestamp", ts_col),
        ("open", open_col),
        ("high", high_col),
        ("low", low_col),
        ("close", close_col),
    ]:
        null_mask = df[c_key].isna()
        if null_mask.any():
            violating_indices = tuple(df.index[null_mask].tolist())
            errors.append(
                IssueDetail(
                    code="NULL_VALUES",
                    message=f"Column '{c_name}' contains {len(violating_indices)} null/NaN value(s).",
                    row_indices=violating_indices,
                    details={"column": c_name, "count": len(violating_indices)},
                )
            )

    # 4. Check for null values in volume (Warning only)
    vol_null_mask = df[vol_col].isna()
    if vol_null_mask.any():
        violating_indices = tuple(df.index[vol_null_mask].tolist())
        warnings.append(
            IssueDetail(
                code="NULL_VOLUME",
                message=f"Volume column contains {len(violating_indices)} null/NaN value(s).",
                row_indices=violating_indices,
                details={"column": "volume", "count": len(violating_indices)},
            )
        )

    # 5. Timestamp validation: parsing, duplicates, ordering
    ts_series = df[ts_col]
    parsed_ts: Optional[pd.Series] = None

    if not pd.api.types.is_datetime64_any_dtype(ts_series):
        # Attempt non-mutating conversion on a copy
        try:
            parsed_ts = pd.to_datetime(ts_series, errors="coerce")
            unparseable_mask = parsed_ts.isna() & ts_series.notna()
            if unparseable_mask.any():
                violating_indices = tuple(df.index[unparseable_mask].tolist())
                errors.append(
                    IssueDetail(
                        code="UNPARSEABLE_TIMESTAMPS",
                        message=f"Found {len(violating_indices)} unparseable timestamp record(s).",
                        row_indices=violating_indices,
                        details={"count": len(violating_indices)},
                    )
                )
        except Exception as e:
            errors.append(
                IssueDetail(
                    code="TIMESTAMP_PARSING_FAILED",
                    message=f"Failed to parse timestamp series: {e}",
                )
            )
    else:
        parsed_ts = ts_series

    if parsed_ts is not None and not parsed_ts.isna().all():
        # Check duplicate timestamps (Error)
        dup_mask = parsed_ts.duplicated(keep=False)
        if dup_mask.any():
            dup_indices = tuple(df.index[dup_mask].tolist())
            errors.append(
                IssueDetail(
                    code="DUPLICATE_TIMESTAMPS",
                    message=f"Found {len(dup_indices)} duplicate timestamp records.",
                    row_indices=dup_indices,
                    details={"count": len(dup_indices)},
                )
            )

        # Check timestamp ordering: must be strictly monotonic increasing (Error)
        valid_ts = parsed_ts.dropna()
        if len(valid_ts) > 1:
            diffs = valid_ts.diff()
            # Non-increasing includes negative diffs (reverse order)
            unordered_mask = diffs < pd.Timedelta(0)
            if unordered_mask.any():
                violating_indices = tuple(valid_ts.index[unordered_mask].tolist())
                errors.append(
                    IssueDetail(
                        code="UNSORTED_TIMESTAMPS",
                        message=f"Found {len(violating_indices)} non-chronological timestamp record(s).",
                        row_indices=violating_indices,
                        details={"count": len(violating_indices)},
                    )
                )

            # Check timestamp gaps (Warning only)
            if expected_interval is not None:
                threshold_gap = (
                    pd.to_timedelta(expected_interval)
                    if isinstance(expected_interval, str)
                    else expected_interval
                )
            else:
                # Use 3x median interval as standard threshold for flagging potential gaps
                median_delta = diffs.median()
                threshold_gap = 3 * median_delta if (pd.notna(median_delta) and median_delta > pd.Timedelta(0)) else None

            if threshold_gap is not None and threshold_gap > pd.Timedelta(0):
                gap_mask = diffs > threshold_gap
                if gap_mask.any():
                    gap_indices = tuple(valid_ts.index[gap_mask].tolist())
                    for idx in gap_indices:
                        loc = valid_ts.index.get_loc(idx)
                        prev_ts = valid_ts.iloc[loc - 1]
                        curr_ts = valid_ts.iloc[loc]
                        warnings.append(
                            IssueDetail(
                                code="TIMESTAMP_GAP",
                                message=f"Timestamp gap of {curr_ts - prev_ts} detected between {prev_ts} and {curr_ts}.",
                                row_indices=(idx,),
                                details={
                                    "previous_timestamp": str(prev_ts),
                                    "current_timestamp": str(curr_ts),
                                    "gap_duration": str(curr_ts - prev_ts),
                                },
                            )
                        )

    # 6. OHLC Numeric & Geometric Invariant Validation (Fatal Errors)
    # Convert series to numeric non-destructively for mathematical comparison
    try:
        open_s = pd.to_numeric(df[open_col], errors="coerce")
        high_s = pd.to_numeric(df[high_col], errors="coerce")
        low_s = pd.to_numeric(df[low_col], errors="coerce")
        close_s = pd.to_numeric(df[close_col], errors="coerce")
        vol_s = pd.to_numeric(df[vol_col], errors="coerce")
    except Exception as e:
        errors.append(
            IssueDetail(
                code="NUMERIC_CONVERSION_ERROR",
                message=f"Failed to parse numeric columns: {e}",
            )
        )
        return ValidationReport(is_valid=False, errors=errors, warnings=warnings)

    # Non-positive prices (Error)
    for p_name, p_series in [("open", open_s), ("high", high_s), ("low", low_s), ("close", close_s)]:
        non_pos_mask = (p_series <= 0.0) & p_series.notna()
        if non_pos_mask.any():
            violating_indices = tuple(df.index[non_pos_mask].tolist())
            errors.append(
                IssueDetail(
                    code="NON_POSITIVE_PRICE",
                    message=f"Detected non-positive price (<= 0.0) in '{p_name}'.",
                    row_indices=violating_indices,
                    details={"column": p_name, "count": len(violating_indices)},
                )
            )

    # High < Low (Error)
    h_lt_l = (high_s < low_s) & high_s.notna() & low_s.notna()
    if h_lt_l.any():
        violating_indices = tuple(df.index[h_lt_l].tolist())
        errors.append(
            IssueDetail(
                code="HIGH_LESS_THAN_LOW",
                message=f"High is lower than Low on {len(violating_indices)} row(s).",
                row_indices=violating_indices,
                details={"count": len(violating_indices)},
            )
        )

    # High < Open (Error)
    h_lt_o = (high_s < open_s) & high_s.notna() & open_s.notna()
    if h_lt_o.any():
        violating_indices = tuple(df.index[h_lt_o].tolist())
        errors.append(
            IssueDetail(
                code="HIGH_LESS_THAN_OPEN",
                message=f"High is lower than Open on {len(violating_indices)} row(s).",
                row_indices=violating_indices,
                details={"count": len(violating_indices)},
            )
        )

    # High < Close (Error)
    h_lt_c = (high_s < close_s) & high_s.notna() & close_s.notna()
    if h_lt_c.any():
        violating_indices = tuple(df.index[h_lt_c].tolist())
        errors.append(
            IssueDetail(
                code="HIGH_LESS_THAN_CLOSE",
                message=f"High is lower than Close on {len(violating_indices)} row(s).",
                row_indices=violating_indices,
                details={"count": len(violating_indices)},
            )
        )

    # Low > Open (Error)
    l_gt_o = (low_s > open_s) & low_s.notna() & open_s.notna()
    if l_gt_o.any():
        violating_indices = tuple(df.index[l_gt_o].tolist())
        errors.append(
            IssueDetail(
                code="LOW_GREATER_THAN_OPEN",
                message=f"Low is greater than Open on {len(violating_indices)} row(s).",
                row_indices=violating_indices,
                details={"count": len(violating_indices)},
            )
        )

    # Low > Close (Error)
    l_gt_c = (low_s > close_s) & low_s.notna() & close_s.notna()
    if l_gt_c.any():
        violating_indices = tuple(df.index[l_gt_c].tolist())
        errors.append(
            IssueDetail(
                code="LOW_GREATER_THAN_CLOSE",
                message=f"Low is greater than Close on {len(violating_indices)} row(s).",
                row_indices=violating_indices,
                details={"count": len(violating_indices)},
            )
        )

    # 7. Volume Invariants
    # Negative Volume (Fatal Error)
    neg_vol = (vol_s < 0.0) & vol_s.notna()
    if neg_vol.any():
        violating_indices = tuple(df.index[neg_vol].tolist())
        errors.append(
            IssueDetail(
                code="NEGATIVE_VOLUME",
                message=f"Negative volume (< 0.0) on {len(violating_indices)} row(s).",
                row_indices=violating_indices,
                details={"count": len(violating_indices)},
            )
        )

    # Zero Volume (Warning Only)
    zero_vol = (vol_s == 0.0) & vol_s.notna()
    if zero_vol.any():
        violating_indices = tuple(df.index[zero_vol].tolist())
        warnings.append(
            IssueDetail(
                code="ZERO_VOLUME",
                message=f"Zero volume (volume == 0.0) detected on {len(violating_indices)} row(s).",
                row_indices=violating_indices,
                details={"count": len(violating_indices)},
            )
        )

    is_valid = len(errors) == 0
    return ValidationReport(is_valid=is_valid, errors=errors, warnings=warnings)
