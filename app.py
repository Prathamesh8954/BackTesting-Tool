"""Streamlit front-end for the historical backtester (Milestone 6).

Run from the repository root::

    streamlit run app.py

The user journey is: load chart data -> validate it -> review the data state ->
configure the backtest -> run it -> review results. All data import and
validation is delegated to the Milestone 1 loader/validator; all execution is
delegated to the Milestone 3 engine.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure the project root is importable regardless of the launch directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.execution import EngineConfig, EngineConfigError, run_backtest  # noqa: E402
from src.metrics import MetricsConsistencyError  # noqa: E402
from src.strategy.validation import StrategyValidationError  # noqa: E402
from src.ui import workflow  # noqa: E402

st.set_page_config(page_title="Historical Backtester", page_icon="📈", layout="wide")


@st.cache_data(show_spinner=False)
def _cached_inspect(path_str: str, mtime: float) -> workflow.DatasetState:
    """Loads and validates a file, cached until the file changes."""
    return workflow.inspect_dataset(Path(path_str))


def _upload_cache_key(uploaded) -> str:
    return f"{uploaded.name}:{uploaded.size}"


def _resolve_uploaded_path(uploaded) -> Path:
    cache = st.session_state.setdefault("_upload_cache", {})
    key = _upload_cache_key(uploaded)
    if key not in cache:
        cache[key] = workflow.save_uploaded_bytes(uploaded.getvalue(), uploaded.name)
    return cache[key]


def _render_validation(state: workflow.DatasetState) -> None:
    report = state.report
    if report is None:
        return
    if report.is_valid:
        st.success("Data is valid and ready to use.")
    else:
        st.error(f"Data validation failed with {len(report.errors)} fatal issue(s).")
        st.dataframe(pd.DataFrame(workflow.issue_rows(report.errors)), use_container_width=True)
    if report.warnings:
        with st.expander(f"Warnings ({len(report.warnings)})", expanded=False):
            st.dataframe(pd.DataFrame(workflow.issue_rows(report.warnings)), use_container_width=True)


def _render_data_state(state: workflow.DatasetState) -> None:
    st.subheader("Data state")
    col1, col2, col3 = st.columns(3)
    col1.metric("Source", state.source_label)
    col2.metric("Rows", f"{state.row_count:,}")
    col3.metric("Columns", len(state.columns))
    st.caption(f"Time range: {workflow.format_time_range(state)}")
    with st.expander("Columns", expanded=False):
        st.write(", ".join(state.columns) if state.columns else "Unavailable")


def _render_results(result) -> None:
    st.subheader("Performance & accounting")
    summary = workflow.result_summary(result)
    columns = st.columns(3)
    for index, (label, value) in enumerate(summary):
        columns[index % 3].metric(label, value)

    # M7: read-only Milestone 4 performance report. It supplements — never
    # replaces — the accounting summary above, and no figure is re-derived here.
    st.subheader("Performance metrics")
    try:
        performance = workflow.performance_summary(result)
    except MetricsConsistencyError as exc:
        st.error(
            "Performance metrics could not be computed: the result failed an "
            f"accounting consistency check. ({exc})"
        )
    else:
        columns = st.columns(3)
        for index, (label, value) in enumerate(performance):
            columns[index % 3].metric(label, value)

    st.subheader("Equity curve")
    equity = workflow.equity_to_dataframe(result)
    if equity.empty:
        st.info("No equity data was produced.")
    else:
        st.line_chart(equity["equity"])

    # M7: per-bar percentage drawdown (Milestone 5 series), directly beneath the
    # equity curve.
    st.subheader("Drawdown (%)")
    drawdown = workflow.drawdown_to_dataframe(result)
    if drawdown.empty:
        st.info("No drawdown data was produced.")
    else:
        st.line_chart(drawdown["decline_pct"])

    st.subheader("Trades")
    trades = workflow.trades_to_dataframe(result)
    if trades.empty:
        st.info("No completed trades.")
    else:
        st.dataframe(trades, use_container_width=True)

    st.subheader("Fills")
    fills = workflow.fills_to_dataframe(result)
    if fills.empty:
        st.info("No fills.")
    else:
        st.dataframe(fills, use_container_width=True)

    st.subheader("Rejections")
    rejections = workflow.rejections_to_dataframe(result)
    if rejections.empty:
        st.info("No rejected decisions.")
    else:
        st.dataframe(rejections, use_container_width=True)

    if result.unfilled_orders:
        st.subheader("Unfilled orders at end of data")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "action": order.action,
                        "order_type": order.order_type,
                        "limit_price": order.limit_price,
                        "queued_bar": order.queued_bar_index,
                        "tag": order.tag,
                    }
                    for order in result.unfilled_orders
                ]
            ),
            use_container_width=True,
        )


st.title("Historical Strategy Backtester")
st.caption(
    "Load validated OHLCV chart data, configure a risk-based backtest, and run a "
    "strategy through the deterministic execution engine."
)

# --- 1. Load chart data -----------------------------------------------------
st.header("1. Load chart data")
files = workflow.list_data_files()
source_mode = st.radio(
    "Choose a data source",
    ["File from data/raw", "Upload a file"],
    horizontal=True,
)

selected_path: Path | None = None
if source_mode == "File from data/raw":
    if not files:
        st.info(
            "No supported files were found in data/raw. Add a .csv or .parquet file "
            "there, or upload one instead."
        )
    else:
        names = [path.name for path in files]
        selected_name = st.selectbox("Select a chart-data file", names)
        selected_path = files[names.index(selected_name)]
else:
    uploaded = st.file_uploader("Upload a chart-data file", type=["csv", "parquet", "pq"])
    if uploaded is not None:
        try:
            selected_path = _resolve_uploaded_path(uploaded)
        except ValueError as exc:
            st.error(str(exc))

# --- 2. Validate data -------------------------------------------------------
dataset: workflow.DatasetState | None = None
if selected_path is not None:
    try:
        mtime = selected_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    dataset = _cached_inspect(str(selected_path), mtime)

    st.header("2. Validate data")
    if dataset.load_error:
        st.error(dataset.load_error)
        with st.expander("Technical details", expanded=False):
            st.code(dataset.load_error_detail or "")
    else:
        _render_validation(dataset)

# --- 3. Review data state ---------------------------------------------------
if dataset is not None and dataset.is_loaded:
    _render_data_state(dataset)

# --- 4. Configure the backtest ---------------------------------------------
st.header("3. Configure the backtest")
col1, col2, col3 = st.columns(3)
initial_capital = col1.number_input(
    "Initial capital", min_value=0.0, value=100_000.0, step=1_000.0, format="%.2f"
)
risk_mode = col2.selectbox("Risk model", ["Fraction of equity", "Absolute cash"])
if risk_mode == "Fraction of equity":
    risk_value = col2.number_input(
        "Risk fraction per trade", min_value=0.0, max_value=1.0, value=0.01, step=0.001, format="%.4f"
    )
else:
    risk_value = col2.number_input(
        "Risk cash per trade", min_value=0.0, value=1_000.0, step=100.0, format="%.2f"
    )
quantity_step = col3.number_input(
    "Quantity step (required)", min_value=0.0, value=1.0, step=0.1, format="%.6f"
)
commission_per_fill = col1.number_input(
    "Commission per fill", min_value=0.0, value=0.0, step=0.01, format="%.4f"
)
slippage_fraction = col2.number_input(
    "Slippage fraction (market fills)", min_value=0.0, max_value=0.99, value=0.0, step=0.001, format="%.4f"
)

# --- 5. Define the strategy -------------------------------------------------
st.header("4. Define the strategy")
st.caption("Your code runs locally and defines a Strategy subclass through the public API.")
strategy_code = st.text_area(
    "Strategy code (Python)", value=workflow.DEFAULT_STRATEGY_TEMPLATE, height=280
)
strategy_class_name = st.text_input("Strategy class name (optional)", value="")

# --- 6. Run -----------------------------------------------------------------
st.header("5. Run the backtest")
can_run = dataset is not None and dataset.is_valid
run_clicked = st.button("Run backtest", type="primary", disabled=not can_run)
if not can_run:
    st.caption("Load valid chart data to enable the run.")

if run_clicked and dataset is not None and dataset.df is not None:
    config: EngineConfig | None = None
    strategy = None
    try:
        config = EngineConfig(
            initial_capital=initial_capital,
            risk_fraction=risk_value if risk_mode == "Fraction of equity" else None,
            risk_absolute=risk_value if risk_mode == "Absolute cash" else None,
            quantity_step=quantity_step,
            commission_per_fill=commission_per_fill,
            slippage_fraction=slippage_fraction,
        )
        strategy = workflow.build_strategy_from_code(strategy_code, strategy_class_name or None)
    except (EngineConfigError, workflow.StrategyCodeError) as exc:
        st.error(str(exc))

    if config is not None and strategy is not None:
        with st.spinner("Running backtest..."):
            try:
                result = run_backtest(strategy, dataset.df, config)
            except StrategyValidationError as exc:
                st.error("The strategy emitted an invalid order request; the run was aborted.")
                with st.expander("Technical details", expanded=False):
                    st.code(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error("The backtest could not be completed.")
                with st.expander("Technical details", expanded=False):
                    st.code(f"{type(exc).__name__}: {exc}")
            else:
                st.session_state["last_result"] = result
                st.success("Backtest complete.")

# --- 7. Results -------------------------------------------------------------
st.header("6. Results")
if "last_result" in st.session_state:
    _render_results(st.session_state["last_result"])
else:
    st.info("Run a backtest to see results here.")
