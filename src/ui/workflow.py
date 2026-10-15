"""Chart-data-to-backtest workflow helpers (Milestone 6).

Pure, framework-free helpers used by the Streamlit front-end (``app.py``) and
tested directly by ``tests/test_ui``. They reuse the Milestone 1 loader/validator
and the Milestone 3 engine; they never re-implement data import.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Type

import pandas as pd

from src.data_loader import load_market_data
from src.data_validator import IssueDetail, ValidationReport, validate_market_data
from src.execution.models import BacktestResult
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
                "entry_commission": trade.entry_commission,
                "exit_commission": trade.exit_commission,
            }
            for trade in result.trades
        ]
    )


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
