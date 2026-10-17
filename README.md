# Universal Historical Strategy Backtesting Tool

A local, deterministic research system for backtesting arbitrary user-defined trading strategies against historical OHLCV market data.

---

## 1. Project Status & Architecture

The architecture enforces a strict separation between data ingestion, strategy logic, execution simulation, and reporting.

* **Milestone 1 (Complete)**: Read-only CSV/Parquet data loader and strict non-mutating OHLCV data validator.
* **Milestone 2 (Complete)**: Universal, strategy-independent interface (`Strategy`), simulation context with lookahead protection (`StrategyContext`), immutable decision model (`StrategyDecision`), and structural request validation (`validate_decision`).
* **Milestone 3 (Complete)**: Order execution simulation engine — fill pricing, transaction costs (slippage/commissions), risk-based position sizing, and intrabar ambiguity resolution.
* **Milestone 4 (Complete)**: Read-only performance metrics derived from the engine result — win/loss/breakeven counts, win rate, expectancy, profit factor, averages, average bars held, and maximum currency/percentage drawdown. Trade logs, equity curves, and the drawdown baseline come from the Milestone 3 execution records.
* **Milestone 5 (Complete)**: A read-only, library-only per-bar drawdown series built on the Milestone 4 drawdown conventions.
* **Milestone 6 (Initial workflow complete; broader scope undefined)**: An initial Streamlit chart-data-to-backtest front-end (`app.py`); the specified workflow is functionally complete (the trade audit-trail and read-only results-filtering slices are covered by Milestones 8, 9, 34 and 36), while the broader "full audit dashboard" has no defined specification.
* **Milestone 7 (Complete)**: A read-only Streamlit metrics & drawdown dashboard built on the Milestone 4 performance metrics and the Milestone 5 per-bar drawdown series — a performance-metrics panel and a per-bar percentage drawdown chart in the results view.
* **Milestone 8 (Complete)**: A pure, read-only validated trade-to-fill linkage helper (`link_trade_fills`) that pairs each completed trade with the entry and closing fills that produced it, positionally and field-by-field, and fails loudly on any stream it cannot prove.
* **Milestone 9 (Complete)**: A read-only Streamlit trade audit trail that surfaces the Milestone 8 linkage — one row per completed trade with its validated entry and closing fill details, and an in-place `linkage` annotation on the existing fills table that labels each fill's role (an open position's trailing entry is labelled, never given a synthetic trade row).

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
5. **Run** the strategy and inspect the results, including the accounting summary, the performance metrics panel, the equity curve, the per-bar drawdown chart, the trade audit trail, trades, fills, and rejected decisions. The trades, trade audit trail, fills, and rejected-decisions tables can each be narrowed with read-only filters (see Milestones 34, 36 and 43 in Section 5).

> Note: This is an initial workflow. The full interactive dashboard and the remaining planned milestones are not yet complete.

---

## 5. Current vs. Future Milestone Capabilities

### Currently Implemented (Milestones 1, 2, 3, 4, 5, 7, 8, 9, 10, 13, 25, 34, 36 & 43)
* **Read-Only Ingestion**: CSV and Parquet files loaded without modifying disk files.
* **Non-Mutating Validation**: Comprehensive OHLC invariant checks, non-numeric checks, and separation of fatal errors from warnings.
* **Strategy Interface**: Universal `Strategy.on_bar(context)` lifecycle supporting stateful strategies.
* **Anti-Lookahead Context**: `StrategyContext.history()` guarantees no access to future bars ($t > t_i$). Detached copies protect engine data from strategy mutations.
* **Structural Decision Validation**: `validate_decision()` rejects non-finite prices, incompatible order types, and contradictory entry brackets.
* **Execution Simulation (Milestone 3)**: Deterministic order matching, fill price determination, slippage and commission accounting, risk-based position sizing, attached stop-loss/take-profit protection, and intrabar ambiguity resolution.
* **Performance Metrics (Milestone 4)**: Read-only summary derived from the engine result — win/loss/breakeven counts, win rate, expectancy, profit factor, averages, average bars held, and maximum currency/percentage drawdown. Auditable trade logs, equity curves, and the drawdown baseline come from the Milestone 3 execution records.
* **Per-Bar Drawdown Series (Milestone 5)**: A read-only, library-only per-bar drawdown path derived from the equity curve using the Milestone 4 drawdown conventions.
* **Metrics & Drawdown Dashboard (Milestone 7)**: The Streamlit results view surfaces the Milestone 4 performance metrics in a dedicated panel and charts the Milestone 5 per-bar percentage drawdown beneath the equity curve. Undefined metrics are shown as `n/a`.
* **Validated Trade-to-Fill Linkage (Milestone 8)**: A pure, read-only helper pairs every completed trade with its entry and closing fills positionally (never by timestamp or tag) and validates the association field-by-field, raising an explicit error on any stream it cannot prove.
* **Trade Audit Trail (Milestone 9)**: The Streamlit results view adds a read-only audit section between Trades and Fills that shows each completed trade with its validated entry and closing fill details, and annotates the existing fills table in place with a role column (`Trade <n> entry` / `Trade <n> close`, or an open-position entry label). A linkage failure is shown to the user while the remaining results sections still render.
* **Execution-Engine Test Coverage (Milestone 10)**: Regression tests close the two documented Milestone 3 test gaps — the reverse per-field protection-modification combination (stop applied while the take-profit is rejected in the same decision) and multiple `MODIFY_PROTECTION` decisions in one bar. Test-only: no engine, accounting, or metric behaviour changed.
* **R-Multiple Analytics (Milestone 13)**: A pure, read-only helper computes each completed trade's $R$-multiple as `R = net_pnl / (quantity * abs(entry_price - initial_stop))`, where the initial stop is captured at entry (before any later protection modification) and recorded on the trade as `Trade.initial_stop`. A companion summary reports the mean $R$ across computable trades plus the computable/non-computable counts. Undefined results are `None`, never `0`. The metric is a library API; the Milestone 13 commit itself changed no performance report, dashboard column, or audit-trail behaviour.
* **R-Multiple UI Integration (Milestone 25)**: The Streamlit results view surfaces the Milestone 13 metric read-only — an `r_multiple` column on the Trades table, and `Mean R` plus computable/non-computable counts in the performance-metrics panel, taken directly from the Milestone 13 helper. An undefined mean is rendered as `n/a`, never `0`; the performance report, the execution records, and the audit trail are unchanged.
* **Read-Only Results Filtering (Milestones 34 & 36)**: The Streamlit results view adds read-only multiselect filters that narrow four tables — the Trades table (by `direction` and `exit_kind`), the trade audit trail (sharing the trade filters via the Milestone 9 exit-kind mapping), the Fills table (by `kind` and `direction`), and the Rejections table (by `reason`). Filtering only narrows the displayed tables; it never changes backtest execution or the underlying results. The reusable `filter_rows` helper lives in `src/ui/workflow.py`, and Milestone 36 added two regression tests.
* **Read-Only Tag Filtering (Milestone 43)**: Tag-based read-only filtering across the same four results tables. The Trades table now displays the existing `Trade.tag` value and offers a tag filter; the trade audit trail shares that Trades tag selection, mapped through its canonical `entry_fill_tag` column (no independent entry- or exit-tag controls exist); and the Fills and Rejections tables each add their own tag filter over their existing tag data. Clearing a tag selection removes only that restriction while other active filters remain in effect, and an empty tag selection imposes no tag restriction. The M43 change is display-only: it never mutates backtest results, persisted state, or the engine. `filter_rows` also continues to ignore unknown filter columns safely.

### Partially Implemented
* **User Interface (Milestone 6)**: An initial Streamlit chart-data-to-backtest workflow (see Section 4). Its broader scope has no defined specification (the trade audit-trail slice is covered by Milestones 8 and 9, and the read-only results-filtering slice by Milestones 34 and 36); completing the wider interactive audit dashboard requires a supervisor decision.

### Deferred to Future Milestones (Not Available Yet)
* **Excursion Analytics**: $R$-multiple target reachability, MFE/MAE, Sharpe, annualization, and exposure remain deferred (they require Milestone 3 record extensions). Per-trade $R$-multiples and their mean/coverage summary are available (library Milestone 13, surfaced read-only in the UI by Milestone 25).

---

## 6. Development & Testing

Run the full automated test suite inside the virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

Currently **325 tests** pass, of which **112** are the UI tests in `tests/test_ui/` (verified during the Milestone 43 documentation reconciliation).
