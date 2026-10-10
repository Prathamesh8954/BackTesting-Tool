# Deterministic Local Historical Trading Research System

## Milestone 1: Data Foundation
A minimalist, deterministic data loader and validator for historical OHLCV market data.

### Features
* **Preservation of Raw Data**: `data/raw/` is treated as strictly read-only. Loader functions use non-destructive reading mechanisms.
* **Non-Mutating Validator**: The validator checks OHLCV integrity without altering, dropping rows, or filling values in the input DataFrame.
* **Separation of Errors & Warnings**: Fatal data issues (e.g., negative volume, price <= 0, geometric high/low violations, non-monotonic timestamps, missing required columns) return `is_valid = False`. Market realities like zero volume bars and weekend timestamp gaps are flagged as non-fatal warnings with detailed metadata.

### Virtual Environment Setup
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Running Tests
```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```
