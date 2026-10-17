"""Chart-data-to-backtest workflow helpers (Milestone 6).

Pure, framework-free helpers used by the Streamlit front-end (``app.py``) and
tested directly by ``tests/test_ui``. They reuse the Milestone 1 loader/validator
and the Milestone 3 engine; they never re-implement data import.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Mapping, Optional, Type

import pandas as pd

from src.data_loader import load_market_data
from src.data_validator import IssueDetail, ValidationReport, validate_market_data
from src.execution.models import BacktestResult, Fill, FillKind, Trade
from src.metrics import (
    compute_drawdown_series,
    compute_metrics,
    compute_r_multiple_summary,
    trade_r_multiple,
)
from src.strategy.base import Strategy
from src.strategy.context import StrategyContext
from src.strategy.models import OrderAction, OrderType, StrategyDecision


SUPPORTED_EXTENSIONS = (".csv", ".parquet", ".pq")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = _REPO_ROOT / "data" / "raw"

DEFAULT_STRATEGY_TEMPLATE = '''"""Define your strategy here.

A strategy subclasses Strategy and returns a sequence of StrategyDecision
objects from on_bar (an empty list means "hold").
"""


class MyStrategy(Strategy):
    def on_start(self) -> None:
        # Reset any state so replays are deterministic.
        pass

    def on_bar(self, context: StrategyContext) -> list[StrategyDecision]:
        # Example intent: enter long once, with a stop-loss, when flat.
        if not context.position.is_open:
            return [
                StrategyDecision(
                    action=OrderAction.ENTER_LONG,
                    order_type=OrderType.MARKET,
                    stop_loss=context.current_bar["close"] * 0.95,
                    tag="example_entry",
                )
            ]
        return []
'''


class StrategyCodeError(ValueError):
    """Raised when user-supplied strategy code cannot be loaded."""


class TradeFillLinkageError(ValueError):
    """Raised when a result's fill stream cannot be linked to its trade records.

    Distinguishes "linkage unavailable" (trades recorded without any fills, as
    only synthetic fixtures can produce) from "linkage invalid" (a malformed,
    out-of-order or self-inconsistent fill stream). Either way the helper fails
    loudly instead of returning an association it cannot prove.
    """


# The M3 engine only ever closes a position with one of these three fills.
_CLOSING_FILL_KINDS = (FillKind.EXIT, FillKind.STOP_LOSS, FillKind.TAKE_PROFIT)

# Same tolerance convention as ``src.metrics.metrics`` consistency checks.
_LINKAGE_REL_TOL = 1e-9
_LINKAGE_ABS_TOL = 1e-9


@dataclass(frozen=True)
class LinkedTrade:
    """A completed trade together with the two fills that produced it."""

    index: int
    trade: Trade
    entry_fill: Fill
    exit_fill: Fill


def link_trade_fills(result: BacktestResult) -> tuple[LinkedTrade, ...]:
    """Pairs every completed trade in ``result`` with its entry and closing fills.

    Pure and read-only: ``result`` is inspected but never mutated, the strategy
    is never rerun, and no fill or trade is ever synthesised. The same input
    always yields the same output.

    Linkage contract
    ----------------
    The M3 engine appends one ``ENTRY`` fill when it opens a position, and a
    closing fill (``EXIT``, ``STOP_LOSS`` or ``TAKE_PROFIT``) *in the same call*
    as the ``Trade`` that closes it (``ExecutionEngine._close_position``).
    Rejected entries append no fill at all, and a position can only be closed
    after it was opened, so the fill stream alternates strictly::

        ENTRY, closing, ENTRY, closing, ...

    Trade ``k`` therefore pairs positionally with ``fills[2k]`` (its entry) and
    ``fills[2k + 1]`` (its close). A position left open at the end of the data
    adds one trailing ``ENTRY`` fill with no matching trade.

    Pairing is deliberately **not** keyed on timestamps (a same-bar round trip
    reuses one timestamp for both fills) or on tags (a manual ``EXIT`` may carry
    an exit tag that differs from the entry tag that ``Trade.tag`` records).

    Every pair is validated against its trade before being returned: kinds,
    direction, quantity, prices, bar indices, timestamps, commissions, tag
    semantics, and the gross/net P&L conventions used by the engine. Anything
    that cannot be proven raises :class:`TradeFillLinkageError`.

    Parameters
    ----------
    result:
        The :class:`~src.execution.models.BacktestResult` to inspect.

    Returns
    -------
    tuple of :class:`LinkedTrade`
        One entry per completed trade, in trade order. The trailing entry fill
        of an open position is validated but not returned, because it has no
        completed trade to pair with.

    Raises
    ------
    TradeFillLinkageError
        If trades are recorded without fills (linkage unavailable), if the fill
        stream is missing, extra or out of order, or if any field of a pair
        disagrees with its trade.
    """
    fills = tuple(result.fills)
    trades = tuple(result.trades)

    # A position left open at the end of the data accounts for one extra,
    # unmatched ENTRY fill; a flat result accounts for none.
    expected_fills = 2 * len(trades) + (0 if result.is_flat else 1)
    if len(fills) != expected_fills:
        if trades and not fills:
            raise TradeFillLinkageError(
                f"Linkage unavailable: result records {len(trades)} completed "
                "trade(s) but contains no fills, so trade-to-fill linkage cannot "
                "be derived from trades alone."
            )
        trailing = "" if result.is_flat else " plus one trailing ENTRY fill for the open position"
        raise TradeFillLinkageError(
            f"Malformed fill stream: expected {expected_fills} fill(s) for "
            f"{len(trades)} completed trade(s){trailing}, found {len(fills)}."
        )

    linked: list[LinkedTrade] = []
    for index, trade in enumerate(trades):
        entry_fill = fills[2 * index]
        closing_fill = fills[2 * index + 1]

        if entry_fill.kind != FillKind.ENTRY:
            raise TradeFillLinkageError(
                f"Out-of-order fill stream at index {2 * index}: an ENTRY fill "
                f"is required to open trade {index}, found {_kind_name(entry_fill.kind)}."
            )
        if closing_fill.kind not in _CLOSING_FILL_KINDS:
            raise TradeFillLinkageError(
                f"Out-of-order fill stream at index {2 * index + 1}: a closing "
                f"fill is required to close trade {index}, found "
                f"{_kind_name(closing_fill.kind)}."
            )

        _validate_pair(index, trade, entry_fill, closing_fill)
        linked.append(
            LinkedTrade(
                index=index,
                trade=trade,
                entry_fill=entry_fill,
                exit_fill=closing_fill,
            )
        )

    if not result.is_flat and fills and fills[-1].kind != FillKind.ENTRY:
        raise TradeFillLinkageError(
            "Out-of-order fill stream: the unmatched trailing fill of an open "
            f"position must be an ENTRY, found {_kind_name(fills[-1].kind)}."
        )

    return tuple(linked)


def _kind_name(kind: object) -> str:
    """Returns the value of a ``FillKind`` (or ``str`` of it) for messages."""
    value = getattr(kind, "value", None)
    return str(value) if value is not None else str(kind)


def _values_close(left: object, right: object) -> bool:
    """Numeric comparison that reports ``False`` instead of raising on bad input."""
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return math.isclose(
        left, right, rel_tol=_LINKAGE_REL_TOL, abs_tol=_LINKAGE_ABS_TOL
    )


def _record_mismatch(
    index: int,
    field: str,
    trade_value: object,
    fill_value: object,
) -> TradeFillLinkageError:
    """Builds the error raised when a trade field disagrees with a fill."""
    return TradeFillLinkageError(
        f"Trade {index} does not match its paired fills: {field} differs "
        f"(trade={trade_value!r}, fill={fill_value!r})."
    )


def _accounting_mismatch(
    index: int,
    field: str,
    trade_value: float,
    recomputed: float,
) -> TradeFillLinkageError:
    """Builds the error raised when a trade's P&L contradicts its own fields."""
    return TradeFillLinkageError(
        f"Trade {index} accounting is inconsistent: {field} differs "
        f"(trade={trade_value!r}, recomputed={recomputed!r})."
    )


def _validate_pair(index: int, trade: Trade, entry_fill: Fill, closing_fill: Fill) -> None:
    """Checks one ``(entry fill, closing fill)`` pair against its trade record.

    Raises :class:`TradeFillLinkageError` on the first disagreement.
    """
    # --- non-identity fields -----------------------------------------------
    for field, trade_value, fill_value in (
        ("entry kind", trade.entry_kind, entry_fill.kind),
        ("exit kind", trade.exit_kind, closing_fill.kind),
        ("entry direction", trade.direction, entry_fill.direction),
        ("exit direction", trade.direction, closing_fill.direction),
        ("entry bar index", trade.entry_bar_index, entry_fill.bar_index),
        ("exit bar index", trade.exit_bar_index, closing_fill.bar_index),
        ("entry timestamp", trade.entry_timestamp, entry_fill.timestamp),
        ("exit timestamp", trade.exit_timestamp, closing_fill.timestamp),
        ("entry tag", trade.tag, entry_fill.tag),
    ):
        if trade_value != fill_value:
            raise _record_mismatch(index, field, trade_value, fill_value)

    # A stop-loss/take-profit close inherits the position tag, so it must agree.
    # A manual EXIT decision may carry its own tag, so its fill tag is
    # informational only and is never used to join records.
    if closing_fill.kind != FillKind.EXIT and trade.tag != closing_fill.tag:
        raise _record_mismatch(index, "exit tag", trade.tag, closing_fill.tag)

    # --- float identity fields ---------------------------------------------
    for field, trade_value, fill_value in (
        ("entry quantity", trade.quantity, entry_fill.quantity),
        ("exit quantity", trade.quantity, closing_fill.quantity),
        ("entry price", trade.entry_price, entry_fill.price),
        ("exit price", trade.exit_price, closing_fill.price),
        ("entry commission", trade.entry_commission, entry_fill.commission),
        ("exit commission", trade.exit_commission, closing_fill.commission),
    ):
        if not _values_close(trade_value, fill_value):
            raise _record_mismatch(index, field, trade_value, fill_value)

    # --- accounting conventions (mirrors ExecutionEngine._close_position) ----
    if trade.direction == "LONG":
        gross = trade.quantity * (trade.exit_price - trade.entry_price)
    else:
        gross = trade.quantity * (trade.entry_price - trade.exit_price)
    net = gross - trade.entry_commission - trade.exit_commission

    if not _values_close(trade.gross_pnl, gross):
        raise _accounting_mismatch(index, "gross P&L", trade.gross_pnl, gross)
    if not _values_close(trade.net_pnl, net):
        raise _accounting_mismatch(index, "net P&L", trade.net_pnl, net)


@dataclass
class DatasetState:
    """The result of loading and validating a single chart-data file."""

    source_label: str
    path: Optional[Path] = None
    df: Optional[pd.DataFrame] = None
    report: Optional[ValidationReport] = None
    load_error: Optional[str] = None
    load_error_detail: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        return self.df is not None and self.report is not None

    @property
    def is_valid(self) -> bool:
        return self.report is not None and self.report.is_valid

    @property
    def row_count(self) -> int:
        return 0 if self.df is None else int(len(self.df))

    @property
    def columns(self) -> list[str]:
        return [] if self.df is None else [str(c) for c in self.df.columns]

    @property
    def start_timestamp(self):
        return self._timestamp_bound(low=True)

    @property
    def end_timestamp(self):
        return self._timestamp_bound(low=False)

    def _timestamp_bound(self, low: bool):
        if self.df is None or "timestamp" not in self.df.columns or self.df.empty:
            return None
        timestamps = pd.to_datetime(self.df["timestamp"], errors="coerce").dropna()
        if timestamps.empty:
            return None
        return timestamps.min() if low else timestamps.max()


def list_data_files(raw_dir: Optional[Path] = None) -> list[Path]:
    """Returns supported data files in ``raw_dir`` (sorted by name)."""
    directory = Path(raw_dir) if raw_dir is not None else DEFAULT_RAW_DIR
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda path: path.name.lower())


def save_uploaded_bytes(data: bytes, filename: str) -> Path:
    """Persists uploaded bytes to a temporary file the loader can read."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{suffix or filename}'. "
            f"Supported types: {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="upload_")
    try:
        handle.write(data)
    finally:
        handle.close()
    return Path(handle.name)


def inspect_dataset(path: Path, source_label: Optional[str] = None) -> DatasetState:
    """Loads and validates ``path``, returning a :class:`DatasetState`.

    File-format and parsing problems are reported as friendly messages rather
    than raised, so the UI can display them.
    """
    label = source_label or Path(path).name
    try:
        df = load_market_data(path)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a message
        return DatasetState(
            source_label=label,
            path=Path(path),
            load_error="The selected file could not be read.",
            load_error_detail=f"{type(exc).__name__}: {exc}",
        )

    try:
        report = validate_market_data(df)
    except Exception as exc:  # noqa: BLE001
        return DatasetState(
            source_label=label,
            path=Path(path),
            df=df,
            load_error="The selected file could not be validated.",
            load_error_detail=f"{type(exc).__name__}: {exc}",
        )

    return DatasetState(source_label=label, path=Path(path), df=df, report=report)


def format_time_range(state: DatasetState) -> str:
    """Human-readable data time range, or a placeholder when unavailable."""
    start, end = state.start_timestamp, state.end_timestamp
    if start is None or end is None:
        return "Unavailable"
    return f"{start}  \u2192  {end}"


def issue_rows(issues: list[IssueDetail]) -> list[dict]:
    """Converts validator issues into display rows."""
    rows = []
    for issue in issues:
        rows.append(
            {
                "code": issue.code,
                "message": issue.message,
                "rows": _format_indices(issue.row_indices),
            }
        )
    return rows


def _format_indices(row_indices) -> str:
    if not row_indices:
        return ""
    preview = ", ".join(str(i) for i in row_indices[:5])
    if len(row_indices) > 5:
        preview += f", ... (+{len(row_indices) - 5} more)"
    return preview


def build_strategy_from_code(code: str, class_name: Optional[str] = None) -> Strategy:
    """Instantiates a :class:`Strategy` from user-supplied Python source.

    The code is executed in an isolated namespace that already provides the
    public strategy API names. A ``Strategy`` subclass (optionally named
    ``class_name``) or a module-level ``strategy`` instance must be defined.
    """
    if not code or not code.strip():
        raise StrategyCodeError("No strategy code was provided.")

    namespace: dict = {
        "__name__": "user_strategy",
        "Strategy": Strategy,
        "StrategyContext": StrategyContext,
        "StrategyDecision": StrategyDecision,
        "OrderAction": OrderAction,
        "OrderType": OrderType,
    }
    try:
        compiled = compile(code, "<strategy>", "exec")
        exec(compiled, namespace)  # noqa: S102 - intentional user-supplied code
    except StrategyCodeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise StrategyCodeError(
            f"The strategy code could not be loaded: {type(exc).__name__}: {exc}"
        ) from exc

    instance = namespace.get("strategy")
    if isinstance(instance, Strategy):
        return instance

    candidates: list[Type[Strategy]] = []
    for name, value in namespace.items():
        if (
            isinstance(value, type)
            and issubclass(value, Strategy)
            and value is not Strategy
            and getattr(value, "__module__", None) == "user_strategy"
        ):
            candidates.append(value)

    chosen: Optional[Type[Strategy]] = None
    if class_name:
        match = next((c for c in candidates if c.__name__ == class_name), None)
        if match is None:
            raise StrategyCodeError(
                f"No Strategy subclass named '{class_name}' was found in the strategy code."
            )
        chosen = match
    elif len(candidates) == 1:
        chosen = candidates[0]
    elif len(candidates) > 1:
        names = ", ".join(sorted(c.__name__ for c in candidates))
        raise StrategyCodeError(
            f"Multiple Strategy subclasses were found ({names}). "
            f"Define exactly one, or provide a module-level 'strategy' instance."
        )
    else:
        raise StrategyCodeError(
            "No Strategy subclass was found. Define a class that subclasses Strategy."
        )

    try:
        return chosen()
    except Exception as exc:  # noqa: BLE001
        raise StrategyCodeError(
            f"The strategy '{chosen.__name__}' could not be instantiated: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


# --------------------------------------------------------------------- display


def fills_to_dataframe(result: BacktestResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bar": fill.bar_index,
                "timestamp": fill.timestamp,
                "kind": fill.kind.value,
                "side": fill.side.value,
                "direction": fill.direction,
                "quantity": fill.quantity,
                "price": fill.price,
                "commission": fill.commission,
                "slippage": fill.slippage,
                "tag": fill.tag,
            }
            for fill in result.fills
        ]
    )


def trades_to_dataframe(result: BacktestResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "direction": trade.direction,
                "quantity": trade.quantity,
                "entry_bar": trade.entry_bar_index,
                "exit_bar": trade.exit_bar_index,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "exit_kind": trade.exit_kind.value,
                "gross_pnl": trade.gross_pnl,
                "net_pnl": trade.net_pnl,
                "r_multiple": trade_r_multiple(trade),
                "entry_commission": trade.entry_commission,
                "exit_commission": trade.exit_commission,
                "tag": trade.tag,
            }
            for trade in result.trades
        ]
    )


# Role shown for the unmatched ENTRY fill of a position left open at the end of
# the data. It is deliberately explicit that no completed trade exists for it.
OPEN_POSITION_ENTRY_LINKAGE = "Open-position entry — no completed trade."


def linked_trades_to_dataframe(result: BacktestResult) -> pd.DataFrame:
    """One row per completed trade with its validated entry and closing fills.

    Read-only: ``result`` is inspected via :func:`link_trade_fills` and never
    mutated or rerun. Every displayed fill value comes from the paired source
    records, which the M8 linkage has already validated field-by-field against
    the trade. No row is produced for a position left open at the end of the
    data (its trailing ENTRY fill has no completed trade).

    Columns carry the trade's identity and economics plus the bar, timestamp,
    price, commission, tag and close-kind of both of its fills. The entry kind
    is omitted because it is always ``ENTRY`` (validated by the linkage), and
    ``side``/``slippage`` are omitted because they have no ``Trade`` counterpart
    and therefore take part in no validated comparison.

    Raises
    ------
    TradeFillLinkageError
        If the records cannot be linked or validated; nothing is rendered from
        an unprovable association.
    """
    rows = []
    for item in link_trade_fills(result):
        trade = item.trade
        entry = item.entry_fill
        closing = item.exit_fill
        rows.append(
            {
                "trade": item.index,
                "direction": trade.direction,
                "quantity": trade.quantity,
                "entry_fill_bar": entry.bar_index,
                "entry_fill_timestamp": entry.timestamp,
                "entry_fill_price": entry.price,
                "entry_fill_commission": entry.commission,
                "entry_fill_tag": entry.tag,
                "exit_fill_kind": closing.kind.value,
                "exit_fill_bar": closing.bar_index,
                "exit_fill_timestamp": closing.timestamp,
                "exit_fill_price": closing.price,
                "exit_fill_commission": closing.commission,
                "exit_fill_tag": closing.tag,
                "gross_pnl": trade.gross_pnl,
                "net_pnl": trade.net_pnl,
            }
        )
    return pd.DataFrame(rows)


def linked_fills_to_dataframe(result: BacktestResult) -> pd.DataFrame:
    """The fills table annotated with a ``linkage`` column naming each fill's role.

    The columns of :func:`fills_to_dataframe` are preserved in order; ``linkage``
    is appended as the final column so the existing fills view gains traceability
    without becoming a second table. Values are ``"Trade <n> entry"`` /
    ``"Trade <n> close"`` (0-based trade index, matching ``LinkedTrade.index``)
    or :data:`OPEN_POSITION_ENTRY_LINKAGE` for the unmatched trailing ENTRY fill
    of an open position.

    Read-only and deterministic. Raises :class:`TradeFillLinkageError` when the
    linkage cannot be validated.
    """
    frame = fills_to_dataframe(result)
    linked = link_trade_fills(result)
    # Built in fill-stream order, so it aligns row-for-row with the fills table.
    roles: list[str] = []
    for item in linked:
        roles.append(f"Trade {item.index} entry")
        roles.append(f"Trade {item.index} close")
    if not result.is_flat:
        # Validated by link_trade_fills: the trailing fill of an open position
        # is exactly one unmatched ENTRY.
        roles.append(OPEN_POSITION_ENTRY_LINKAGE)
    # A length mismatch would raise rather than silently mislabel a fill.
    frame["linkage"] = roles
    return frame


def rejections_to_dataframe(result: BacktestResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bar": rejection.bar_index,
                "timestamp": rejection.timestamp,
                "reason": rejection.reason,
                "message": rejection.message,
                "tag": rejection.tag,
            }
            for rejection in result.rejections
        ]
    )


def equity_to_dataframe(result: BacktestResult) -> pd.DataFrame:
    rows = [
        {
            "timestamp": point.timestamp,
            "equity": point.equity,
            "cash": point.cash,
        }
        for point in result.equity_curve
    ]
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.set_index("timestamp")
    return frame


def result_summary(result: BacktestResult) -> list[tuple[str, str]]:
    """Ordered (label, value) summary rows for display."""
    return [
        ("Initial capital", f"{result.initial_capital:,.2f}"),
        ("Final equity", f"{result.final_equity:,.2f}"),
        ("Total P&L", f"{result.total_pnl:,.2f}"),
        ("Total return", f"{result.total_return_pct:,.2f}%"),
        ("Realized P&L", f"{result.realized_pnl:,.2f}"),
        ("Unrealized P&L", f"{result.unrealized_pnl:,.2f}"),
        ("Completed trades", f"{len(result.trades)}"),
        ("Winning / losing", f"{result.winning_trades} / {result.losing_trades}"),
        ("Fills", f"{len(result.fills)}"),
        ("Rejections", f"{len(result.rejections)}"),
        ("Open position", "None" if result.is_flat else f"{result.open_direction} x{result.open_quantity:g}"),
    ]


# Milestone 7 display formatting. ``_UNDEFINED`` is the single rendering of an
# undefined (``None``) metric: never a substituted zero.
_UNDEFINED = "n/a"


def _format_money(value: Optional[float]) -> str:
    """Formats currency with thousands separators; ``None`` stays undefined."""
    return _UNDEFINED if value is None else f"{value:,.2f}"


def _format_ratio(value: Optional[float]) -> str:
    """Formats a unitless ratio to two decimals; ``None`` stays undefined."""
    return _UNDEFINED if value is None else f"{value:,.2f}"


def _format_percent_points(value: Optional[float]) -> str:
    """Formats an already-scaled percentage (percentage points, M4/M5 style)."""
    return _UNDEFINED if value is None else f"{value:,.2f}%"


def _format_percent_fraction(value: Optional[float]) -> str:
    """Formats a 0-1 fraction (the M4 win rate) as a percentage."""
    return _UNDEFINED if value is None else f"{value * 100:.2f}%"


def _format_bar_index(value: Optional[int]) -> str:
    """Formats a bar index; ``None`` means no such bar exists."""
    return _UNDEFINED if value is None else str(value)


def performance_summary(result: BacktestResult) -> list[tuple[str, str]]:
    """Ordered (label, value) rows for the Milestone 7 performance panel.

    Read-only: the Milestone 4/7 figures are taken from the ``compute_metrics``
    report and merely formatted here, so the panel can never disagree with the
    metrics library; the R-multiple rows come from the Milestone 13 helper
    (``compute_r_multiple_summary``) and are likewise only formatted. Undefined
    metrics (``None``, e.g. a win rate with no closed trades, or a mean R with no
    computable trade) render as ``"n/a"`` and are never replaced with zero.

    ``MetricsConsistencyError`` is deliberately **not** caught here: it
    propagates so the caller can show the failure instead of hiding the panel.
    """
    report = compute_metrics(result)
    r_summary = compute_r_multiple_summary(result.trades)
    rows: list[tuple[str, str]] = [
        # Closed-trade statistics (M4)
        ("Closed trades", str(report.closed_trade_count)),
        ("Winning trades", str(report.winning_trades)),
        ("Losing trades", str(report.losing_trades)),
        ("Breakeven trades", str(report.breakeven_trades)),
        ("Win rate", _format_percent_fraction(report.win_rate)),
        ("All trades winning", "Yes" if report.all_trades_winning else "No"),
        ("Gross realized P&L", _format_money(report.gross_realized_pnl)),
        ("Net realized P&L", _format_money(report.net_realized_pnl)),
        ("Total P&L", _format_money(report.total_pnl)),
        ("Total return", _format_percent_points(report.total_return_pct)),
        ("Average winning trade", _format_money(report.average_winning_trade)),
        ("Average losing trade", _format_money(report.average_losing_trade)),
        ("Expectancy per trade", _format_money(report.expectancy)),
        ("Profit factor", _format_ratio(report.profit_factor)),
        ("Average bars held", _format_ratio(report.average_bars_held)),
        # Maximum drawdown (M4), currency and percentage computed independently
        ("Max drawdown", _format_money(report.drawdown.currency)),
        ("Max drawdown %", _format_percent_points(report.drawdown.pct)),
        (
            "Max drawdown currency peak bar",
            _format_bar_index(report.drawdown.currency_peak_bar_index),
        ),
        (
            "Max drawdown currency trough bar",
            _format_bar_index(report.drawdown.currency_trough_bar_index),
        ),
        ("Max drawdown % peak bar", _format_bar_index(report.drawdown.pct_peak_bar_index)),
        (
            "Max drawdown % trough bar",
            _format_bar_index(report.drawdown.pct_trough_bar_index),
        ),
        # Informational open-position summary (M4/F3: unrealized P&L stays gross)
        ("Open position", "None" if report.open_position is None else f"{report.open_position.direction} x{report.open_position.quantity:g}"),
        ("Reconciliation difference", _format_money(report.reconciliation_difference)),
        # R-multiple analytics (M13). Derived from the immutable Trade records by
        # the pure M13 helper; never re-derived here, and an undefined mean stays
        # "n/a" (it is never replaced with zero).
        ("Mean R", _format_ratio(r_summary.mean_r)),
        ("R-multiple computable trades", str(r_summary.computable_count)),
        ("R-multiple non-computable trades", str(r_summary.non_computable_count)),
    ]
    if report.open_position is not None:
        position = report.open_position
        rows.extend(
            [
                ("Open unrealized P&L (gross)", _format_money(position.unrealized_pnl_gross)),
                ("Open entry price", _format_money(position.entry_price)),
                (
                    "Open entry bar",
                    _format_bar_index(position.entry_bar_index),
                ),
                (
                    "Open entry timestamp",
                    _UNDEFINED if position.entry_timestamp is None else str(position.entry_timestamp),
                ),
                ("Open entry commission", _format_money(position.entry_commission)),
                ("Open mark price", _format_money(position.mark_price)),
            ]
        )
    return rows


def drawdown_to_dataframe(result: BacktestResult) -> pd.DataFrame:
    """Per-bar drawdown path for display (Milestone 5 series, read-only).

    Wraps ``compute_drawdown_series`` over the same ``(bar_index, equity)`` pairs
    the engine recorded, using the run's ``initial_capital`` as the peak anchor,
    so the chart cannot diverge from the M4 maximum-drawdown summary.

    Returns a timestamp-indexed frame with ``decline_pct`` (percentage points)
    and ``decline_currency`` columns. An empty equity curve yields an empty
    frame, matching :func:`equity_to_dataframe`.
    """
    series = compute_drawdown_series(
        [(point.bar_index, point.equity) for point in result.equity_curve],
        result.initial_capital,
    )
    rows = [
        {
            "timestamp": equity_point.timestamp,
            "decline_pct": drawdown_point.decline_pct,
            "decline_currency": drawdown_point.decline_currency,
        }
        # The series preserves input order and bar indices, so the n-th point
        # always describes the n-th equity point.
        for equity_point, drawdown_point in zip(result.equity_curve, series.points)
    ]
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.set_index("timestamp")
    return frame


# ------------------------------------------------------------------- filtering


def filter_rows(
    frame: pd.DataFrame,
    criteria: Optional[Mapping[str, Collection[str]]] = None,
) -> pd.DataFrame:
    """Returns a copy of ``frame`` keeping the rows that satisfy every criterion.

    ``criteria`` maps a column name to the collection of values the user has
    selected for it. The rules are deliberately simple and total:

    * A criterion that is ``None`` or empty selects **every** row, so an
      all-unset filter set reproduces ``frame`` exactly (the default UI state).
    * A criterion naming a column that ``frame`` does not have imposes no
      restriction, so the helper can never raise on an unexpected table shape.
    * Rows are kept only when they match **all** supplied criteria (the
      combination is an intersection).

    Read-only and deterministic, like the other ``src.ui.workflow`` helpers: the
    input is never mutated, the result preserves the input column order and the
    relative order of the surviving rows, and an empty match is an empty frame
    that still carries the input columns.
    """
    filtered = frame.copy()
    if not criteria:
        return filtered
    for column, allowed in criteria.items():
        if allowed is None:
            continue
        allowed_values = list(allowed)
        if not allowed_values or column not in filtered.columns:
            continue
        filtered = filtered.loc[filtered[column].isin(allowed_values)]
    return filtered.copy()
