import hashlib
from pathlib import Path
import pandas as pd
import pytest
from src.data_loader import load_market_data


def get_file_hash(path: Path) -> str:
    """Computes SHA-256 hash of a file on disk."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_load_csv_success(tmp_path: Path, valid_ohlcv_df: pd.DataFrame):
    """Verifies that a valid CSV is loaded accurately and timestamps are parsed."""
    csv_file = tmp_path / "sample.csv"
    valid_ohlcv_df.to_csv(csv_file, index=False)

    df_loaded = load_market_data(csv_file)

    assert len(df_loaded) == 5
    assert list(df_loaded.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert pd.api.types.is_datetime64_any_dtype(df_loaded["timestamp"])
    assert df_loaded["open"].iloc[0] == 100.0


def test_load_parquet_success(tmp_path: Path, valid_ohlcv_df: pd.DataFrame):
    """Verifies that a valid Parquet file is loaded accurately with pyarrow."""
    parquet_file = tmp_path / "sample.parquet"
    valid_ohlcv_df.to_parquet(parquet_file, engine="pyarrow", index=False)

    df_loaded = load_market_data(parquet_file)

    assert len(df_loaded) == 5
    assert pd.api.types.is_datetime64_any_dtype(df_loaded["timestamp"])
    assert df_loaded["close"].iloc[-1] == 105.5


def test_load_nonexistent_file():
    """Verifies that attempting to load a missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="File not found"):
        load_market_data("nonexistent_path_xyz_123.csv")


def test_load_unsupported_format(tmp_path: Path):
    """Verifies that unsupported file extensions raise ValueError."""
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("dummy content")

    with pytest.raises(ValueError, match="Unsupported file format"):
        load_market_data(txt_file)


def test_load_empty_file(tmp_path: Path):
    """Verifies that an empty CSV file raises ValueError rather than failing silently."""
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("timestamp,open,high,low,close,volume\n")

    with pytest.raises(ValueError, match="is empty"):
        load_market_data(empty_csv)


def test_load_does_not_modify_source_file(tmp_path: Path, valid_ohlcv_df: pd.DataFrame):
    """Guarantees raw data preservation: file hash and mtime are strictly preserved."""
    csv_file = tmp_path / "raw_input.csv"
    valid_ohlcv_df.to_csv(csv_file, index=False)

    hash_before = get_file_hash(csv_file)
    mtime_before = csv_file.stat().st_mtime_ns

    # Perform load
    _ = load_market_data(csv_file)

    hash_after = get_file_hash(csv_file)
    mtime_after = csv_file.stat().st_mtime_ns

    assert hash_before == hash_after, "File content was modified during load!"
    assert mtime_before == mtime_after, "File modification time was changed during load!"


def test_load_does_not_silently_drop_rows(tmp_path: Path):
    """Verifies that rows with corrupt values or NaNs are retained rather than dropped."""
    csv_file = tmp_path / "with_bad_rows.csv"
    csv_content = (
        "timestamp,open,high,low,close,volume\n"
        "2026-01-01 09:30:00,100,105,95,102,1000\n"
        "INVALID_DATE,NaN,105,95,102,1000\n"
        "2026-01-01 11:30:00,100,105,95,102,1000\n"
    )
    csv_file.write_text(csv_content)

    df_loaded = load_market_data(csv_file)

    # Exactly 3 rows must be preserved; no silent dropping
    assert len(df_loaded) == 3
    assert pd.isna(df_loaded["timestamp"].iloc[1])
    assert pd.isna(df_loaded["open"].iloc[1])


def test_load_duplicate_normalized_columns(tmp_path: Path):
    """
    Verifies that duplicate column names resulting from trimming/lowercasing
    (e.g., 'Close' and ' close ') trigger a clear ValueError listing the conflict.
    """
    csv_file = tmp_path / "duplicate_cols.csv"
    csv_content = (
        "timestamp,open,high,low,Close, close ,volume\n"
        "2026-01-01 09:30:00,100,105,95,102,102.5,1000\n"
    )
    csv_file.write_text(csv_content)

    with pytest.raises(ValueError, match="Duplicate normalized column name"):
        load_market_data(csv_file)
