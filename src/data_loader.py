from pathlib import Path
from typing import Union
import pandas as pd


def load_market_data(file_path: Union[str, Path]) -> pd.DataFrame:
    """
    Loads market OHLCV data from a CSV or Parquet file in read-only mode.

    Guarantees:
    - Never modifies or overwrites the source file on disk.
    - Never silently drops rows, fills missing values, or repairs data.
    - Returns an unmodified DataFrame representing the file content.
    - Standardizes column names to lowercase stripped strings.
    - Parses the 'timestamp' column to datetime if present (retaining unparseable values as NaT).

    Raises:
    - FileNotFoundError: If the file does not exist.
    - ValueError: If the file format is unsupported or file is empty.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if not path.is_file():
        raise ValueError(f"Path is not a regular file: {path}")

    suffix = path.suffix.lower()

    if suffix == ".csv":
        # Read CSV with read-only intent
        df = pd.read_csv(path)
    elif suffix in (".parquet", ".pq"):
        # Read Parquet using pyarrow engine
        df = pd.read_parquet(path, engine="pyarrow")
    else:
        raise ValueError(
            f"Unsupported file format '{suffix}'. Supported formats are .csv and .parquet"
        )

    if df.empty:
        raise ValueError(f"File '{path.name}' is empty (0 rows).")

    # Standardize column headers to lowercase and trimmed strings
    normalized_cols = [str(col).strip().lower() for col in df.columns]

    # Detect duplicate column names caused by normalization
    seen = {}
    duplicates = set()
    for orig_col, norm_col in zip(df.columns, normalized_cols):
        if norm_col in seen:
            duplicates.add(norm_col)
        else:
            seen[norm_col] = orig_col

    if duplicates:
        conflicting_cols = [str(col) for col in df.columns if str(col).strip().lower() in duplicates]
        raise ValueError(
            f"Duplicate normalized column name(s) detected: {sorted(duplicates)}. "
            f"Conflicting original columns: {conflicting_cols}"
        )

    df.columns = normalized_cols

    # Parse timestamps if timestamp column is present
    if "timestamp" in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            # Use errors='coerce' so bad timestamps turn to NaT rather than crashing here;
            # the validator will catch and report NaT/unparseable timestamps with exact indices.
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    return df
