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


def _render_filter_widgets(
    frame: pd.DataFrame,
    columns: tuple[tuple[str, str], ...],
    key_prefix: str,
) -> dict[str, list[str]]:
    """Renders one multiselect per configurable column and returns the selection.

    Options are the distinct values present in ``frame`` (sorted), so a filter
    can only ever offer values the table actually contains. With nothing
    selected every multiselect is empty, which :func:`workflow.filter_rows`
    treats as "no restriction" — the unfiltered view is therefore the default.
    """
    selections: dict[str, list[str]] = {}
    widget_columns = st.columns(len(columns))
    for widget_column, (name, label) in zip(widget_columns, columns):
        options = sorted(frame[name].astype(str).unique().tolist())
        selections[name] = widget_column.multiselect(label, options, key=f"{key_prefix}:{name}")
    return selections


def _render_bar_range_filter(
    frame: pd.DataFrame,
    column: str,
    label: str,
    key: str,
) -> tuple[int, int] | None:
    """Renders an inclusive bar-index range slider and returns its selection.

    The slider spans the column's observed numeric domain, so its default
    minimum-to-maximum position is a full range that reproduces the unfiltered
    table. ``None`` is returned when no usable domain exists — a missing column,
    an empty frame, or a single distinct value — which the caller treats as "no
    restriction"; :func:`workflow.filter_rows_by_range` honours that as a no-op,
    so no invalid (zero-width) slider is ever configured.
    """
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    low = int(values.min())
    high = int(values.max())
    if low >= high:
        return None
    selection = st.slider(label, min_value=low, max_value=high, value=(low, high), key=key)
    return (int(selection[0]), int(selection[1]))


def _render_filtered_table(
    frame: pd.DataFrame,
    criteria: dict[str, list[str]],
    empty_message: str,
    bar_range: tuple[str, int, int] | None = None,
) -> None:
    """Renders ``frame`` through :func:`workflow.filter_rows` and an optional range.

    ``bar_range`` is an ``(column, low, high)`` inclusive bar-index interval
    applied on top of the categorical ``criteria``, so the two filters intersect.
    An empty result (before or after filtering) is reported with ``empty_message``.
    """
    filtered = workflow.filter_rows(frame, criteria)
    if bar_range is not None:
        column, low, high = bar_range
        filtered = workflow.filter_rows_by_range(filtered, column, low, high)
    if filtered.empty:
        st.info(empty_message)
    else:
        st.dataframe(filtered, use_container_width=True)


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
    trade_criteria: dict[str, list[str]] = {}
    trades_range: tuple[int, int] | None = None
    if trades.empty:
        st.info("No completed trades.")
    else:
        # M34: read-only categorical filters over the completed trades. Empty
        # selections are the default and reproduce the unfiltered table exactly.
        trade_criteria = _render_filter_widgets(
            trades,
            (
                ("direction", "Filter trades by direction"),
                ("exit_kind", "Filter trades by exit kind"),
                ("tag", "Filter trades by tag"),
            ),
            "trades_filter",
        )
        # M44: an inclusive entry-bar range that intersects the filters above and
        # is shared with the audit trail below (mapped to its entry fill bar).
        trades_range = _render_bar_range_filter(
            trades,
            "entry_bar",
            "Filter trades by entry bar",
            "trades_filter:entry_bar",
        )
        _render_filtered_table(
            trades,
            trade_criteria,
            "No trades match the selected filters.",
            bar_range=None if trades_range is None else ("entry_bar", *trades_range),
        )

    # M9: read-only trade-to-fill audit trail. Each row pairs a completed trade
    # with the fills that produced it using the M8 linkage; nothing is re-derived
    # here and the strategy is never rerun. A linkage failure is reported without
    # hiding the remaining results sections.
    try:
        audit = workflow.linked_trades_to_dataframe(result)
        linked_fills = workflow.linked_fills_to_dataframe(result)
    except workflow.TradeFillLinkageError as exc:
        audit = None
        linked_fills = None
        linkage_error: workflow.TradeFillLinkageError | None = exc
    else:
        linkage_error = None

    st.subheader("Trade audit trail")
    if linkage_error is not None:
        st.error(
            "Trade-to-fill linkage could not be validated: the result failed a "
            f"linkage consistency check. ({linkage_error})"
        )
    elif audit is not None and audit.empty:
        st.info("No completed trades to audit.")
    else:
        # M34: the audit trail shares the trade filters (its closing-fill kind
        # column is named ``exit_fill_kind``), so the two views stay consistent.
        # M44: it also shares the trades entry-bar range, remapped to the audit's
        # ``entry_fill_bar`` column (the entry fill sits on the entry bar).
        audit_criteria = {
            "direction": trade_criteria.get("direction", []),
            "exit_fill_kind": trade_criteria.get("exit_kind", []),
            "entry_fill_tag": trade_criteria.get("tag", []),
        }
        _render_filtered_table(
            audit,
            audit_criteria,
            "No trades match the selected filters.",
            bar_range=None
            if trades_range is None
            else ("entry_fill_bar", *trades_range),
        )

    st.subheader("Fills")
    fills = (
        linked_fills
        if linked_fills is not None
        else workflow.fills_to_dataframe(result)
    )
    if fills.empty:
        st.info("No fills.")
    else:
        fill_criteria = _render_filter_widgets(
            fills,
            (
                ("kind", "Filter fills by kind"),
                ("direction", "Filter fills by direction"),
                ("tag", "Filter fills by tag"),
            ),
            "fills_filter",
        )
        # M44: an independent fills range over the fill's own ``bar`` column.
        fills_range = _render_bar_range_filter(
            fills,
            "bar",
            "Filter fills by bar",
            "fills_filter:bar",
        )
        _render_filtered_table(
            fills,
            fill_criteria,
            "No fills match the selected filters.",
            bar_range=None if fills_range is None else ("bar", *fills_range),
        )

    st.subheader("Rejections")
    rejections = workflow.rejections_to_dataframe(result)
    if rejections.empty:
        st.info("No rejected decisions.")
    else:
        rejection_criteria = _render_filter_widgets(
            rejections,
            (
                ("reason", "Filter rejections by reason"),
                ("tag", "Filter rejections by tag"),
            ),
            "rejections_filter",
        )
        # M44: an independent rejections range over the rejection's ``bar``.
        rejections_range = _render_bar_range_filter(
            rejections,
            "bar",
            "Filter rejections by bar",
            "rejections_filter:bar",
        )
        _render_filtered_table(
            rejections,
            rejection_criteria,
            "No rejections match the selected filters.",
            bar_range=None
            if rejections_range is None
            else ("bar", *rejections_range),
        )

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
