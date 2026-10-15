# Universal Historical Strategy Backtesting Tool

A local, deterministic research system for backtesting arbitrary user-defined trading strategies against historical OHLCV market data.

---

## 1. Project Status & Architecture

The architecture enforces a strict separation between data ingestion, strategy logic, execution simulation, and reporting.

* **Milestone 1 (Complete)**: Read-only CSV/Parquet data loader and strict non-mutating OHLCV data validator.
* **Milestone 2 (Complete)**: Universal, strategy-independent interface (`Strategy`), simulation context with lookahead protection (`StrategyContext`), immutable decision model (`StrategyDecision`), and structural request validation (`validate_decision`).
* **Milestone 3 (Complete)**: Order execution simulation engine — fill pricing, transaction costs (slippage/commissions), risk-based position sizing, and intrabar ambiguity resolution.
* **Milestone 6 (Initial workflow)**: An initial Streamlit chart-data-to-backtest front-end (`app.py`). The full UI and the remaining planned milestones are not yet complete.

---

## 2. Providing Historical Market Data

### Target Directory
Place all raw historical data files into:
```
data/raw/
```
*(Full path: `C:\Users\user\Desktop\BackTesting Tool\data\raw\`)*

### Data Preservation & Git Privacy Guarantees
* **Strictly Read-Only**: Application code opens raw files in read-only mode and will **never** overwrite, mutate, drop rows from, or delete files in `data/raw/`.
* **Git Excluded**: All files in `data/raw/` (except `.gitkeep`) are excluded by `.gitignore`. Your market datasets will never be committed to Git.

### Supported File Formats
1. **CSV** (`.csv`)
2. **Parquet** (`.parquet`, `.pq`)

### Required Columns & Schema Rules
The loader automatically strips whitespace and normalizes column headers to lowercase. The following six columns are required:

| Column | Type | Validation Rules |
| :--- | :--- | :--- |
| `timestamp` | Datetime / ISO 8601 string | Must parse to datetime. Must be strictly monotonically increasing (chronological) with **no duplicate timestamps**. |
| `open` | Numeric (float) | Strictly positive ($> 0.0$), finite (no `inf` or `nan`). |
| `high` | Numeric (float) | Must satisfy: `high >= low`, `high >= open`, `high >= close`. |
| `low` | Numeric (float) | Must satisfy: `low <= high`, `low <= open`, `low <= close`. |
| `close` | Numeric (float) | Strictly positive ($> 0.0$), finite (no `inf` or `nan`). |
| `volume` | Numeric (float) | Non-negative ($\ge 0.0$). Negative volume is a fatal error; zero volume is flagged as a non-fatal warning. |

### Example CSV Format (`data/raw/example_symbol.csv`)
```csv
timestamp,open,high,low,close,volume
2026-01-05 09:30:00,100.50,102.00,100.25,101.75,15200
2026-01-05 10:30:00,101.75,103.50,101.50,103.00,18400
2026-01-05 11:30:00,103.00,103.25,101.00,101.50,12100
2026-01-05 12:30:00,101.50,104.00,101.25,103.80,21000
```

---

## 3. Verified Python Usage Example

The following script demonstrates loading a data file, validating its invariants, and running a custom strategy through the context interface:

```python
from pathlib import Path
from src.data_loader import load_market_data
from src.data_validator import validate_market_data
from src.strategy import (
    Strategy,
    StrategyContext,
    StrategyDecision,
    OrderAction,
    OrderType,
    validate_decision,
)

# 1. Load historical data from data/raw/
file_path = Path("data/raw/example_symbol.csv")
df = load_market_data(file_path)

# 2. Validate data invariants
report = validate_market_data(df)
if not report.is_valid:
    print(f"Dataset has {len(report.errors)} fatal errors:")
    for err in report.errors:
        print(f"  [{err.code}] {err.message} (rows: {err.row_indices[:5]})")
    raise ValueError("Market data validation failed.")

if report.warnings:
    print(f"Dataset has {len(report.warnings)} non-fatal warnings (e.g., zero volume or weekend gaps).")

# 3. Define a custom strategy
class SimpleBreakoutStrategy(Strategy):
    def __init__(self, lookback: int = 20):
        self.lookback = lookback
        self.bars_seen = 0

    def on_start(self) -> None:
        self.bars_seen = 0

    def on_bar(self, context: StrategyContext) -> list[StrategyDecision]:
        self.bars_seen += 1

        # Access trailing history safely (strictly <= current candle)
        hist = context.history(n_bars=self.lookback)
        if len(hist) < self.lookback:
            return []  # Not enough history; return empty list for no-op

        current_close = context.current_bar["close"]
        highest_high = hist["high"].iloc[:-1].max()

        # Emit intent to enter long on breakout
        if current_close > highest_high and not context.position.is_open:
            decision = StrategyDecision(
                action=OrderAction.ENTER_LONG,
                order_type=OrderType.MARKET,
                stop_loss=hist["low"].iloc[:-1].min(),
                tag="donchian_breakout",
            )
            validate_decision(decision)
            return [decision]

        return []

# 4. Step through context bar-by-bar (Milestone 2 interface)
strategy = SimpleBreakoutStrategy(lookback=3)
strategy.on_start()

for i in range(len(df)):
    ctx = StrategyContext(full_df=df, current_idx=i)
    decisions = strategy.on_bar(ctx)
    for dec in decisions:
        validate_decision(dec)
        print(f"Bar {i} ({ctx.timestamp}): Decision emitted -> {dec.action} ({dec.tag})")

strategy.on_finish()
```

---

## 4. Running the App

An initial Streamlit workflow is available for taking chart data through to a backtest.

**Prerequisites**: Install the project dependencies first (including Streamlit):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then run the app from the repository root:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The workflow guides you through:

1. **Load or upload** a CSV or Parquet chart-data file (from `data/raw/` or via the upload control).
2. **Validate** the data, with clear messages for missing columns, invalid values, or other failures.
3. **Review** the loaded data state (source, number of rows, available time range, and columns).
4. **Configure** the backtest (initial capital, risk model, quantity step, commission, and slippage).
5. **Run** the strategy and inspect the results, including the accounting summary, equity curve, trades, fills, and rejected decisions.

> Note: This is an initial workflow. The full interactive dashboard and the remaining planned milestones are not yet complete.

---

## 5. Current vs. Future Milestone Capabilities

### Currently Implemented (Milestones 1, 2 & 3)
* **Read-Only Ingestion**: CSV and Parquet files loaded without modifying disk files.
* **Non-Mutating Validation**: Comprehensive OHLC invariant checks, non-numeric checks, and separation of fatal errors from warnings.
* **Strategy Interface**: Universal `Strategy.on_bar(context)` lifecycle supporting stateful strategies.
* **Anti-Lookahead Context**: `StrategyContext.history()` guarantees no access to future bars ($t > t_i$). Detached copies protect engine data from strategy mutations.
* **Structural Decision Validation**: `validate_decision()` rejects non-finite prices, incompatible order types, and contradictory entry brackets.
* **Execution Simulation (Milestone 3)**: Deterministic order matching, fill price determination, slippage and commission accounting, risk-based position sizing, attached stop-loss/take-profit protection, and intrabar ambiguity resolution.

### Partially Implemented
* **User Interface (Milestone 6)**: An initial Streamlit chart-data-to-backtest workflow (see Section 4). The full interactive audit dashboard is not yet complete.

### Deferred to Future Milestones (Not Available Yet)
* **Trade Ledger & Performance Metrics (Milestones 4 & 5)**: Auditable trade logs, equity curves, drawdown series, and $R$-multiple target reachability calculations.

---

## 6. Development & Testing

Run the full automated test suite inside the virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```
