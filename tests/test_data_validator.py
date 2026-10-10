import copy
import pandas as pd
import pytest
from src.data_validator import validate_market_data


def test_valid_dataset(valid_ohlcv_df: pd.DataFrame):
    """Verifies that a valid dataset passes with is_valid=True and no issues."""
    report = validate_market_data(valid_ohlcv_df)

    assert report.is_valid is True
    assert len(report.errors) == 0
    assert len(report.warnings) == 0


def test_validation_leaves_input_dataframe_unchanged(valid_ohlcv_df: pd.DataFrame):
    """
    CRITICAL ACCEPTANCE TEST:
    Ensures that validate_market_data leaves the input DataFrame completely unmodified.
    No rows dropped, no nulls filled, no columns added, dtypes unchanged.
    """
    df_clone = valid_ohlcv_df.copy(deep=True)

    report = validate_market_data(valid_ohlcv_df)

    # DataFrame must be bitwise identical before and after validation
    pd.testing.assert_frame_equal(valid_ohlcv_df, df_clone, check_exact=True)


def test_validation_leaves_invalid_dataframe_unchanged():
    """Confirms that even an invalid DataFrame with NaNs and errors is NOT modified in place."""
    df_bad = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=4, freq="1D"),
        "open": [100.0, None, 102.0, 103.0],
        "high": [105.0, 106.0, 95.0, 107.0],  # row 2 has high < open
        "low": [98.0, 97.0, 99.0, 100.0],
        "close": [102.0, 101.0, 100.0, -5.0],  # row 3 has negative price
        "volume": [100.0, -10.0, 0.0, 200.0],   # row 1 negative vol, row 2 zero vol
    })
    df_clone = df_bad.copy(deep=True)

    report = validate_market_data(df_bad)

    assert report.is_valid is False
    pd.testing.assert_frame_equal(df_bad, df_clone, check_exact=True)


def test_missing_required_columns(valid_ohlcv_df: pd.DataFrame):
    """Verifies that missing columns trigger fatal errors without crashing."""
    df_missing = valid_ohlcv_df.drop(columns=["close", "volume"])

    report = validate_market_data(df_missing)

    assert report.is_valid is False
    err = next(e for e in report.errors if e.code == "MISSING_COLUMNS")
    assert "close" in err.details["missing_columns"]
    assert "volume" in err.details["missing_columns"]


def test_duplicate_timestamps(valid_ohlcv_df: pd.DataFrame):
    """Verifies that duplicate timestamps are detected and report exact indices."""
    df_dup = valid_ohlcv_df.copy()
    # Force duplicate timestamp at index 1 and 2
    df_dup.loc[2, "timestamp"] = df_dup.loc[1, "timestamp"]

    report = validate_market_data(df_dup)

    assert report.is_valid is False
    err = next(e for e in report.errors if e.code == "DUPLICATE_TIMESTAMPS")
    assert 1 in err.row_indices
    assert 2 in err.row_indices


def test_unsorted_timestamps(valid_ohlcv_df: pd.DataFrame):
    """Verifies that non-monotonic/unsorted timestamps produce an error."""
    df_unsorted = valid_ohlcv_df.copy()
    # Reverse row order
    df_unsorted = df_unsorted.iloc[::-1].reset_index(drop=True)

    report = validate_market_data(df_unsorted)

    assert report.is_valid is False
    err = next(e for e in report.errors if e.code == "UNSORTED_TIMESTAMPS")
    assert len(err.row_indices) > 0


def test_unparseable_timestamps():
    """Verifies that unparseable timestamps trigger fatal errors."""
    df = pd.DataFrame({
        "timestamp": ["2026-01-01 09:30", "NOT_A_DATE", "2026-01-01 11:30"],
        "open": [100.0, 101.0, 102.0],
        "high": [105.0, 105.0, 105.0],
        "low": [95.0, 95.0, 95.0],
        "close": [102.0, 102.0, 102.0],
        "volume": [100.0, 100.0, 100.0],
    })

    report = validate_market_data(df)

    assert report.is_valid is False
    assert any(e.code == "UNPARSEABLE_TIMESTAMPS" for e in report.errors)
    err = next(e for e in report.errors if e.code == "UNPARSEABLE_TIMESTAMPS")
    assert 1 in err.row_indices


def test_ohlc_high_less_than_low(valid_ohlcv_df: pd.DataFrame):
    """Verifies that high < low produces a fatal error."""
    df = valid_ohlcv_df.copy()
    df.loc[1, "high"] = 90.0
    df.loc[1, "low"] = 95.0

    report = validate_market_data(df)

    assert report.is_valid is False
    err = next(e for e in report.errors if e.code == "HIGH_LESS_THAN_LOW")
    assert 1 in err.row_indices


def test_ohlc_high_less_than_open_or_close(valid_ohlcv_df: pd.DataFrame):
    """Verifies that high < max(open, close) produces fatal errors."""
    df = valid_ohlcv_df.copy()
    df.loc[2, "high"] = 101.0
    df.loc[2, "open"] = 103.0  # high < open

    df.loc[3, "high"] = 102.0
    df.loc[3, "close"] = 104.0  # high < close

    report = validate_market_data(df)

    assert report.is_valid is False
    assert any(e.code == "HIGH_LESS_THAN_OPEN" for e in report.errors)
    assert any(e.code == "HIGH_LESS_THAN_CLOSE" for e in report.errors)


def test_ohlc_low_greater_than_open_or_close(valid_ohlcv_df: pd.DataFrame):
    """Verifies that low > min(open, close) produces fatal errors."""
    df = valid_ohlcv_df.copy()
    df.loc[0, "low"] = 101.0
    df.loc[0, "open"] = 100.0  # low > open

    df.loc[4, "low"] = 106.0
    df.loc[4, "close"] = 105.5  # low > close

    report = validate_market_data(df)

    assert report.is_valid is False
    assert any(e.code == "LOW_GREATER_THAN_OPEN" for e in report.errors)
    assert any(e.code == "LOW_GREATER_THAN_CLOSE" for e in report.errors)


def test_non_positive_price(valid_ohlcv_df: pd.DataFrame):
    """Verifies that non-positive prices (<= 0) produce fatal errors."""
    df = valid_ohlcv_df.copy()
    df.loc[1, "low"] = 0.0
    df.loc[3, "close"] = -2.5

    report = validate_market_data(df)

    assert report.is_valid is False
    errs = [e for e in report.errors if e.code == "NON_POSITIVE_PRICE"]
    assert len(errs) >= 1
    violating_indices = {idx for e in errs for idx in e.row_indices}
    assert 1 in violating_indices
    assert 3 in violating_indices


def test_missing_values_fatal_error(valid_ohlcv_df: pd.DataFrame):
    """Verifies that NaNs in OHLC prices are flagged as fatal errors and NOT silently dropped."""
    df = valid_ohlcv_df.copy()
    df.loc[2, "close"] = None

    report = validate_market_data(df)

    assert report.is_valid is False
    err = next(e for e in report.errors if e.code == "NULL_VALUES")
    assert 2 in err.row_indices
    assert len(df) == 5  # Confirms no silent row dropping occurred


def test_negative_volume(valid_ohlcv_df: pd.DataFrame):
    """Verifies that volume < 0 produces a fatal error."""
    df = valid_ohlcv_df.copy()
    df.loc[4, "volume"] = -500.0

    report = validate_market_data(df)

    assert report.is_valid is False
    err = next(e for e in report.errors if e.code == "NEGATIVE_VOLUME")
    assert 4 in err.row_indices


def test_zero_volume_is_warning_only(valid_ohlcv_df: pd.DataFrame):
    """
    CORRECTION TEST:
    Zero volume is common in illiquid hours/cash indices; it must be a WARNING, NOT an error.
    is_valid must remain True.
    """
    df = valid_ohlcv_df.copy()
    df.loc[1, "volume"] = 0.0

    report = validate_market_data(df)

    assert report.is_valid is True  # Zero volume does NOT invalidate data
    assert len(report.errors) == 0
    assert len(report.warnings) == 1
    assert report.warnings[0].code == "ZERO_VOLUME"
    assert 1 in report.warnings[0].row_indices


def test_null_volume_is_warning_only(valid_ohlcv_df: pd.DataFrame):
    """Verifies that missing volume is reported as a warning, not fatal error."""
    df = valid_ohlcv_df.copy()
    df.loc[3, "volume"] = None

    report = validate_market_data(df)

    assert report.is_valid is True  # Missing volume is non-fatal warning
    assert len(report.errors) == 0
    assert len(report.warnings) == 1
    assert report.warnings[0].code == "NULL_VOLUME"
    assert 3 in report.warnings[0].row_indices


def test_timestamp_gap_is_warning_only(valid_ohlcv_df: pd.DataFrame):
    """
    CORRECTION TEST:
    Timestamp gaps (e.g. weekends/holidays) must be reported as WARNINGS, NOT fatal errors.
    is_valid must remain True.
    """
    df = valid_ohlcv_df.copy()
    # Introduce a 4-day weekend gap between bar 2 and 3
    df.loc[3, "timestamp"] = pd.Timestamp("2026-01-05 09:30")
    df.loc[4, "timestamp"] = pd.Timestamp("2026-01-05 10:30")

    report = validate_market_data(df, expected_interval="1h")

    assert report.is_valid is True  # Gap does NOT invalidate data
    assert len(report.errors) == 0
    assert len(report.warnings) >= 1
    gap_warn = next(w for w in report.warnings if w.code == "TIMESTAMP_GAP")
    assert 3 in gap_warn.row_indices
    assert gap_warn.details["previous_timestamp"] == "2026-01-01 11:30:00"
    assert gap_warn.details["current_timestamp"] == "2026-01-05 09:30:00"
    assert gap_warn.details["gap_duration"] == "3 days 22:00:00"


def test_empty_dataframe():
    """Verifies that an empty DataFrame triggers fatal error without raising an unhandled exception."""
    report = validate_market_data(pd.DataFrame())

    assert report.is_valid is False
    assert any(e.code == "EMPTY_DATAFRAME" for e in report.errors)


def test_non_numeric_price_value(valid_ohlcv_df: pd.DataFrame):
    """Verifies that non-numeric text in OHLC prices is reported as fatal error."""
    df = valid_ohlcv_df.astype({"open": "object"}).copy()
    df.loc[1, "open"] = "INVALID_PRICE"

    report = validate_market_data(df)

    assert report.is_valid is False
    err = next(e for e in report.errors if e.code == "NON_NUMERIC_VALUE")
    assert 1 in err.row_indices
    assert err.details["column"] == "open"


def test_non_numeric_volume_value(valid_ohlcv_df: pd.DataFrame):
    """
    Verifies that non-numeric volume text is a fatal error and NOT silently converted
    into a missing-volume (NULL_VOLUME) warning.
    """
    df = valid_ohlcv_df.astype({"volume": "object"}).copy()
    df.loc[2, "volume"] = "CORRUPT_VOLUME_TEXT"

    report = validate_market_data(df)

    assert report.is_valid is False
    assert any(e.code == "NON_NUMERIC_VALUE" for e in report.errors)
    assert not any(w.code == "NULL_VOLUME" for w in report.warnings)
    err = next(e for e in report.errors if e.code == "NON_NUMERIC_VALUE")
    assert 2 in err.row_indices
    assert err.details["column"] == "volume"


def test_non_finite_price_and_volume(valid_ohlcv_df: pd.DataFrame):
    """
    Verifies that inf and -inf values in OHLC prices and volume are fatal errors,
    and do NOT generate misleading NEGATIVE_VOLUME, ZERO_VOLUME, or NON_POSITIVE_PRICE diagnostics.
    """
    df = valid_ohlcv_df.copy()
    df.loc[0, "high"] = float("inf")
    df.loc[1, "close"] = float("-inf")
    df.loc[2, "volume"] = float("inf")
    df.loc[3, "volume"] = float("-inf")

    report = validate_market_data(df)

    assert report.is_valid is False
    inf_errs = [e for e in report.errors if e.code == "NON_FINITE_VALUE"]
    assert len(inf_errs) == 3
    violating_cols = {e.details["column"] for e in inf_errs}
    assert violating_cols == {"high", "close", "volume"}

    vol_err = next(e for e in inf_errs if e.details["column"] == "volume")
    assert vol_err.row_indices == (2, 3)
    assert vol_err.details["count"] == 2

    # Confirm that non-finite values do NOT generate secondary misleading diagnostics
    assert not any(e.code == "NEGATIVE_VOLUME" for e in report.errors)
    assert not any(w.code == "ZERO_VOLUME" for w in report.warnings)
    assert not any(e.code == "NON_POSITIVE_PRICE" for e in report.errors)


def test_gap_detection_with_duplicate_index_labels():
    """
    Verifies that timestamp gap detection does not crash and correctly reports
    the exact previous and current timestamps when the DataFrame index contains duplicate labels.
    """
    df = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-01-01 09:30"),
                pd.Timestamp("2026-01-01 10:30"),
                pd.Timestamp("2026-01-05 09:30"),  # weekend gap
                pd.Timestamp("2026-01-05 10:30"),
            ],
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [105.0, 105.0, 105.0, 105.0],
            "low": [95.0, 95.0, 95.0, 95.0],
            "close": [102.0, 102.0, 102.0, 102.0],
            "volume": [100.0, 100.0, 100.0, 100.0],
        },
        index=[10, 10, 20, 20],  # Duplicate labels, but rows across gap (10 and 20) are distinct
    )

    report = validate_market_data(df, expected_interval="1h")

    assert report.is_valid is True
    assert len(report.errors) == 0
    assert any(w.code == "TIMESTAMP_GAP" for w in report.warnings)
    gap_warn = next(w for w in report.warnings if w.code == "TIMESTAMP_GAP")
    assert gap_warn.row_indices == (20,)
    assert gap_warn.details["previous_timestamp"] == "2026-01-01 10:30:00"
    assert gap_warn.details["current_timestamp"] == "2026-01-05 09:30:00"
    assert gap_warn.details["gap_duration"] == "3 days 23:00:00"


def test_unsorted_timestamps_skips_gap_detection(valid_ohlcv_df: pd.DataFrame):
    """
    Verifies that unsorted timestamps are reported as fatal errors and do NOT emit
    misleading inferred timestamp gap warnings.
    """
    df = valid_ohlcv_df.copy()
    # Disrupt chronological sequence
    df.loc[2, "timestamp"] = pd.Timestamp("2025-01-01 00:00")

    report = validate_market_data(df, expected_interval="1h")

    assert report.is_valid is False
    assert any(e.code == "UNSORTED_TIMESTAMPS" for e in report.errors)
    # Crucially: no false gap warning should be emitted on an unsorted sequence
    assert not any(w.code == "TIMESTAMP_GAP" for w in report.warnings)


def test_duplicate_timestamps_skips_gap_detection(valid_ohlcv_df: pd.DataFrame):
    """
    Verifies that duplicate timestamps are reported as fatal errors and do NOT emit
    misleading inferred timestamp gap warnings.
    """
    df = valid_ohlcv_df.copy()
    # Introduce duplicate timestamp and large jump afterward
    df.loc[2, "timestamp"] = df.loc[1, "timestamp"]
    df.loc[3, "timestamp"] = pd.Timestamp("2026-01-10 09:30")

    report = validate_market_data(df, expected_interval="1h")

    assert report.is_valid is False
    assert any(e.code == "DUPLICATE_TIMESTAMPS" for e in report.errors)
    # Crucially: no false gap warning should be emitted when duplicates are present
    assert not any(w.code == "TIMESTAMP_GAP" for w in report.warnings)
