# Project context (agent working memory)

Source of truth: this file plus the current repository, `README.md`, and tests. Verify APIs in source before coding. Update this file only when milestone status or simulation decisions change.

## Goal and architecture

Local, deterministic, strategy-agnostic historical backtester. Users define rules via a Python `Strategy` interface and run them against OHLCV data.

Layers stay separate: ingestion → strategy intent → execution simulation → reporting. Do not mix them.

Python `>=3.12`. Dependencies (do not add others without asking): pandas, pyarrow, numpy, pytest. `streamlit` was added **with explicit user authorization** to implement the Milestone 6 UI. Package name: `backtesting-tool`.

## Milestone status

| Milestone | Status | Notes |
|---|---|---|
| 1 Data loader + validator | Complete (committed) | `src/data_loader.py`, `src/data_validator.py` |
| 2 Strategy interface | Complete (committed at `7ad7715`) | `src/strategy/`, `tests/test_strategy/` |
| 3 Execution engine | Complete (committed at `7ad7715`) | `src/execution/`, `tests/test_execution/` |
| 4 Metrics layer | Complete (committed at `ef2cb46`) | `src/metrics/`, `tests/test_metrics/`; read-only, derived from M3 records |
| 5 Drawdown series | Complete (committed at `6c50daf`) | `src/metrics/drawdown.py`; read-only per-bar drawdown series, library-only |
| 6 Streamlit UI | Initial workflow implemented (committed at `7ad7715`, user-authorized); the specified workflow is functionally complete; the broader "full audit dashboard" has **no defined specification** and requires a supervisor decision | `app.py`, `src/ui/`, `tests/test_ui/` |
| 7 Metrics & drawdown dashboard | Complete (committed at `6b31b74`) | `app.py`, `src/ui/workflow.py`, `tests/test_ui/`; read-only UI surfacing of the M4 metrics and the M5 per-bar drawdown |
| 8 Validated trade-to-fill linkage | Complete (committed at `8186f20`) | `src/ui/workflow.py`, `tests/test_ui/test_linkage.py`; pure `link_trade_fills` helper (`TradeFillLinkageError`, frozen `LinkedTrade`) pairing each completed trade with its entry and closing fills, positionally and field-by-field |
| 9 Trade-to-fill audit trail | Complete (committed at `dcdde65`) | `app.py`, `src/ui/workflow.py`, `tests/test_ui/`; read-only UI audit section that surfaces the M8 linkage. The M8 helper is a prerequisite; this audit-trail linkage is the concrete M8/M9 implementation, while the broader dashboard scope remains unspecified and requires a supervisor decision |
| 10 Execution-engine test-gap coverage | Implemented (committed at `4227413`) | `tests/test_execution/test_engine_protection.py`; closes the two documented M3 gaps (reverse per-field protection-modification combination; multiple `MODIFY_PROTECTION` decisions in one bar). Test-only; no production change |
| 13 R-multiple analytics | Implemented (committed at `4227413`) | `src/metrics/r_multiple.py`, `src/execution/models.py` (`Trade.initial_stop`), `src/execution/engine.py` (`_Position.initial_stop`), `tests/test_execution/test_engine_initial_stop.py`, `tests/test_metrics/test_r_multiple.py`; per-trade `R = net_pnl / (quantity * abs(entry_price - initial_stop))` plus a mean/coverage summary. Additive and library-only at M13; the M13 commit changed no `PerformanceReport` or UI (the read-only UI surfacing arrived later in M25) |
| 25 R-multiple UI integration | Complete (committed at `0dffc7c`) | `src/ui/workflow.py`, `tests/test_ui/test_app.py`, `tests/test_ui/test_workflow.py`; read-only UI surfacing of the M13 per-trade R-multiple (Trades `r_multiple` column) and of the mean/coverage summary (`Mean R` plus computable/non-computable counts) in the M7 performance panel. An undefined mean renders `n/a`, never `0`; additive, with no `PerformanceReport`/`OpenPositionSummary`/record/engine change |
| 34/36 Read-only results filtering | Complete (committed at `983acdc`) | `app.py`, `src/ui/workflow.py`, `tests/test_ui/`; read-only filter widgets (`app.py`) plus the reusable `filter_rows` helper (`src/ui/workflow.py`) that narrow the Trades, trade audit trail, Fills, and Rejections tables. Filtering only narrows the displayed tables — it never changes backtest execution or the underlying results. The audit-trail filter reuses the M9 exit-kind mapping; M36 added two regression tests |

Milestones 11 and 12 have no table row: M11 was a documentation reconciliation and M12 was a read-only design review — neither produced implementation artifacts.

README is user-facing and `PROJECT_CONTEXT.md` is implementation memory; README was updated for M3/M6 under prior user authorization (M3 marked complete; M6 described as an initial workflow), for M5/M7 and M8/M9 in earlier reconciliations, and for M10 and the M13 R-multiple metric in the documentation reconciliations committed in `4227413`. The M25 R-multiple UI integration is recorded in the `2a7a401` documentation reconciliation, and the M34/M36 read-only results filtering is recorded in this documentation reconciliation.

## Git (do not stage or commit unless asked)

- Branch: `master`. History: `983acdc` (M34/M36 read-only results filtering) → `2a7a401` (docs: reconcile M25 implementation status) → `0dffc7c` (M25 R-multiple UI integration) → `ad1e30d` (docs: reconcile milestone status and M6 scope) → `4227413` (combined M10/M11/M13/M15: R-multiple analytics, execution-engine test-gap coverage, and documentation reconciliations) → `82354c9` (docs: mark M9 audit trail complete) → `dcdde65` (M9 audit trail) → `8186f20` (M8 linkage) → `a66ee8e` (docs reconciliation) → `6b31b74` (M7 metrics & drawdown dashboard) → `6c50daf` (M5 drawdown series) → `ef2cb46` (M4 metrics) → `7ad7715` (M2/M3/M6) → `c46e62b` (M1, intact).
- Committed milestone work at `4227413` (the combined M10/M11/M13/M15 commit): the M10 execution-engine test-gap coverage (`tests/test_execution/test_engine_protection.py`), the M11 `EngineConfig` documentation reconciliation, the M13 R-multiple analytics (`src/metrics/r_multiple.py`, `src/execution/models.py`, `src/execution/engine.py`, `src/metrics/__init__.py`, `tests/test_metrics/helpers.py`, `tests/test_execution/test_engine_initial_stop.py`, `tests/test_metrics/test_r_multiple.py`), and the M15 documentation polish were all included in the single combined commit `4227413` (`feat: add initial-stop-based R-multiple analytics`). The milestone-status/M6 documentation reconciliation is now committed at `ad1e30d`, and the M25 R-multiple UI integration is committed at `0dffc7c`. M8 is committed at `8186f20` and M9 is committed at `dcdde65`. The M34/M36 read-only results filtering is committed at `983acdc`.
- Preserve all committed work (M1–M5, the M6 UI, the M7 dashboard, the M8 linkage, and the M9 audit trail). Do not rewrite loader/validator behavior, existing strategy models, M3 execution, the committed M4 metrics, the committed M5 drawdown series, the committed M7 UI integration, the committed M8 linkage, or the committed M9 audit trail without an identified need and approval.

Baseline tests: `.\.venv\Scripts\python.exe -m pytest tests -q` → **320 passed** (213 at M7 + 43 M8 linkage tests + 15 M9 audit-trail tests + 5 M10 execution-coverage tests + 19 M13 R-multiple tests + 5 M25 R-multiple UI tests + 20 M34/M36 results-filtering tests; **107** of the 320 are the UI tests in `tests/test_ui/`). (Fresh results verified for this documentation change: **320 passed** / **107** UI tests.)

## Data contracts (M1)

- Raw files live in `data/raw/` (gitignored except `.gitkeep`). Loader is read-only; never mutate or delete source files.
- Formats: `.csv`, `.parquet` / `.pq`.
- Required columns after lowercase/strip: `timestamp`, `open`, `high`, `low`, `close`, `volume`.
- Fatal vs warning split is in `validate_market_data`; validator must not mutate the input DataFrame.

## Strategy contracts (M2)

Lifecycle: `on_start()` → `on_bar(context)` → `on_finish()`. Empty decision sequence = hold. Strategies may be stateful; `on_start` must reset for replay.

**`StrategyDecision`:** `action`, `order_type` (`MARKET`/`LIMIT`), `limit_price`, `stop_loss`, `take_profit`, `tag`. No quantity. Intent only — no fills or account mutation. Engine-side sizing; do not add `quantity` to this model unless a later decision requires it.

**Actions:** `ENTER_LONG`, `ENTER_SHORT`, `EXIT`, `MODIFY_PROTECTION`.

**`StrategyContext`:** bar `i` after close. `history()` never includes `t > i`. `current_bar` / `history` are detached copies. `position` / `account` are frozen snapshots. Interface-level lookahead protection only (not a sandbox).

**`PositionView`:** one net position per instrument. No hedging, pyramiding, or separate tickets. No quantity field. `direction` is `"LONG"` or `"SHORT"`.

**`AccountView`:** `cash`, `equity`, `initial_capital` only. No P&L fields yet. Engine results must still track realized/unrealized P&L.

**`validate_decision`:** structural only (enums, positive finite prices, MARKET/LIMIT field rules, long/short bracket orientation, EXIT/MODIFY field rules). Does not check position, cash, or fills.

Timing already documented on `Strategy`: a market request at index `i` must not fill before index `i+1` open.

## Milestone 3 — approved simulation rules

User-approved. Preserve these rules; do not re-open them. The remaining precision/rounding schema was later approved (see the approved quantity precision rule below); no sizing decision remains open.

1. **Position sizing:** Risk-based from account risk and stop-loss distance. Fixed quantity is **not** the default model. Details in "Approved risk sizing" below.
2. **Initial account:** Configurable initial capital; start **flat** (all capital in cash, no position).
3. **Short selling:** Allowed, **cash-secured**, no leverage or margin borrowing. Require `cash >= quantity * fill + commission` before a short (and before a long).
4. **Position model:** One net position. No pyramiding, hedging, or partial exits. `EXIT` closes the full position.
5. **Execution timing:** A market order generated after candle `i` closes cannot fill before the next eligible candle's open. Do not fill a market order on the signal candle.
6. **Limit orders:** Become eligible from the next candle. Fill at **limit or better** when eligible: buy if `low <= limit`, sell if `high >= limit`; fill at limit unless `open` is already through, then fill at `open`. Unfilled limits stay working until fill, cancel, or expiry.
7. **Stop-loss / take-profit:** Attached to the position (not independent tickets). Levels from the entry decision apply at fill. Protection is active after the entry fill, including remaining movement in the **entry candle**.
8. **Protection modifications:** `MODIFY_PROTECTION` requested after candle `i` is first eligible on candle `i+1`. Omitted SL or TP field leaves the existing level unchanged.
9. **Intrabar ambiguity:** If both SL and TP are touched in the same candle, process **stop-loss first**.
10. **Gaps (conservative):** Stop fills at the worse of the stop level and `open` (long stop: `min(open, stop)`; short stop: `max(open, stop)`). Take-profit fills at the target, or at `open` if `open` is already through the target.
11. **State-incompatible decisions:** Record rejection details (reason, tag, bar) and **continue**. Examples: `ENTER_*` while open or while an entry is working; `EXIT` / `MODIFY_PROTECTION` while flat.
12. **Costs:** Configurable; **both default to zero**. Commission = absolute cash **per fill**, charged on every entry and exit fill, subtracted from cash. Slippage = fraction of price on **market** fills only, against the trader (buy `price * (1 + s)`, sell `price * (1 - s)`). Not applied to limit, SL, or TP fills.
13. **Final candle:** Orders that cannot execute because no later eligible candle exists **expire unfilled**.
14. **Accounting:** Track cash, realized P&L, unrealized P&L, and equity. No margin engine. Mark at close. Long: `equity = cash + qty * close`. Short: `equity = cash - qty * close`. Flat: `equity == cash`. Unrealized long = `qty * (close - entry)`; short = `qty * (entry - close)`. Realized P&L uses **actual** fill prices (slippage already in market fills) and **actual** commissions charged at execution. Do **not** subtract sizing-time cost estimates again from realized P&L.
15. **Replay:** Same data, same engine config, freshly initialized strategy (`on_start`) → identical orders, fills, and equity path.

**Approved bar loop (follows 5, 7, 8, 13):** (1) working orders + attached SL/TP against this candle, (2) mark-to-market at close, (3) `on_bar`, (4) validate and queue new orders / stage protection mods. Capture the entry **risk budget** from the account equity snapshot at this close, **before** queueing the order. Engine calls `validate_decision`; structural failure aborts the run. Multiple decisions in one `on_bar` apply in list order; at most one working entry/exit; extras rejected and recorded.

**Approved risk sizing**
- User configures a risk **fraction** or an **absolute** risk budget per trade. If a fraction: `risk_budget = equity_at_signal_close * fraction`, using the snapshot at the signal candle close, before order submission (after that bar's mark-to-market). Absolute budget does not scale with equity.
- Do **not** compute quantity at signal time. Never use future prices (including the next candle's open) for a signal-time sizing decision. Missing `stop_loss` on an entry is rejected at the signal (record reason, continue).
- At **fill** time, quantity uses the **actual eligible fill price** and stop-loss distance. Market fill already includes market slippage (rule 12). Limit fill is limit or better (rule 6).
- Per-unit **price** risk = `|fill_price - stop_loss|`. If this distance is not strictly positive, reject the entry.
- Include **estimated** entry and stop-exit transaction costs in sizing. Commission is cash per fill, so the unique linear form consistent with `qty = budget / (distance + costs/qty)` is: subtract estimated **entry commission + stop-exit commission** from `risk_budget`, then divide by price distance. Stop-exit slippage estimate is **0** (SL fills have no slippage). Do **not** add entry slippage a second time on top of a slippage-inclusive fill price (that would double-count slippage in sizing). If `risk_budget <= estimated commissions`, reject.
- Charge **actual** commission and slippage once at execution/accounting (rules 12 and 14). Sizing estimates must not be applied again to realized P&L.
- Apply caller-supplied quantity precision / lot-size rules when those rules are present and fully specified. If precision/lot-size rules are **unspecified**, **reject the trade**. Do not assume whole shares, unrestricted fractions, or any implicit lot.
- After a valid quantity is obtained, if `cash < quantity * fill + commission`, **reject the entire entry**. Do not reduce quantity. Same cash-secured check for long and short.
- No fixed-quantity fallback.

## Milestone 3 — approved decision record

**Single authoritative list.** User-approved; do not re-open. These five restate the "Approved risk sizing" rules above; where any earlier wording is looser, this record governs.

1. **Risk base:** the risk budget is calculated from the current account **equity snapshot taken at the signal candle's close**, before order submission (after that bar's mark-to-market).
2. **Quantity precision:** explicit quantity precision or lot-size rules are **required**. If they are unspecified, **reject the trade** rather than assume whole units or fractional quantities.
3. **Sizing at fill time:** quantity is calculated using the **actual eligible fill price** and the stop-loss distance. Never use future prices (such as the next candle's open) in the signal-time sizing decision.
4. **Transaction costs:** estimated **entry and stop-exit** costs are included in per-unit risk when computing quantity. Actual commission and slippage are charged **once** at execution/accounting; costs are **not** double-counted in realized P&L.
5. **Cash constraint:** if the calculated quantity cannot be funded under the cash-secured rules, **reject the entire entry**. Do not silently reduce quantity.

### Consistency audit (cross-reference only; introduces no rules)

No contradictions found among the flagged interactions:

- *Deferred sizing / risk-budget capture:* the budget is fixed from the post-mark-to-market equity snapshot at the signal close, before submission, while quantity is computed only at fill time from the actual eligible fill price ("Approved risk sizing" above). Absolute budgets do not scale with equity.
- *Estimated vs. actual costs:* sizing subtracts estimated entry + stop-exit commission (cash-per-fill, so the estimate matches the eventual charge). Actual commission and slippage are charged once at execution and never re-applied to realized P&L (simulation rules 12 and 14).
- *Affordability:* the cash-secured check is identical in simulation rule 3 and the sizing rules (`cash >= quantity * fill + commission`); failure rejects the whole entry, and rounding quantity **down** to the step can only lower required cash.

### Risk-budget semantics vs. configuration/API shape

- **Approved (semantics):** the risk budget is a user-configured **fraction of equity** or an **absolute** amount; a fraction uses the equity snapshot at the signal close, before submission; an absolute budget does not scale with equity. Per-unit risk, cost inclusion, rounding, and affordability are as listed above.
- **Implemented (Phase B plumbing; no trading rule):** the concrete **configuration/API shape** is implemented and committed as the frozen `EngineConfig` dataclass in `src/execution/config.py` (exported from `src.execution`; the fields and the `risk_fraction` XOR `risk_absolute` rule also appear on the "Engine API" line under "Current work and next actions"). It supplies `initial_capital` (required, > 0), `risk_fraction` (in `(0, 1]`) **or** `risk_absolute` (> 0), `quantity_step` (per-instrument lot increment; **never defaulted** — `None`/non-positive is a valid config that makes the engine reject entries, per the approved precision rule), `commission_per_fill` (default `0.0`), and `slippage_fraction` (default `0.0`). Structurally invalid input raises `EngineConfigError` (a `ValueError` subclass). It is plumbing only and encodes **no** trading rules, so it does not change any approved simulation semantics; the field names, types, and validation-error behaviour that the former note listed as undecided are settled by this implementation. Verified by `tests/test_execution/test_config.py`.

### Approved stop / take-profit orientation rules

User-approved (Decisions A–D plus the follow-up clarifications; **rule 4 has since been amended — see rule 4**). These apply at the **fill** moment using the **actual eligible fill price**; they reuse the rule 11 record-and-continue mechanism (record reason + tag + bar) and do **not** change M2 structural validation (`validate_decision` stays structural only).

1. **Wrong-side stop-loss (entry):** if an entry's stop-loss is on the wrong side of the actual fill price (long: `stop_loss > fill`; short: `stop_loss < fill`), **reject the entry at fill** (record and continue); do not open the position.
2. **Wrong-side stop-loss (protection modification):** if `MODIFY_PROTECTION` would move a stop to the wrong side of the **current market mark** (long: `stop_loss > mark`; short: `stop_loss < mark`), **reject the modification** (record and continue); the prior stop level is retained. The reference is the current mark, **not** the entry fill, so valid profitable trailing stops above the entry fill remain possible.
3. **Wrong-side take-profit (entry):** if an entry's take-profit is on the wrong side of the actual fill price (long: `take_profit < fill`; short: `take_profit > fill`), **reject the entry at fill** (record and continue), symmetric with the stop rule.
4. **Wrong-side take-profit (protection modification) — amended (user-approved):** the reference is the **entry fill price**, **not** the current market mark. A `MODIFY_PROTECTION` that would set a take-profit on the wrong side of the original entry fill (long: `take_profit < entry_fill`; short: `take_profit > entry_fill`) is **rejected** (record and continue); the prior TP is retained. A correct-side TP modification is applied. This is intentionally **asymmetric with rule 2**: stops are mark-referenced so profitable trailing stops remain valid, while targets are anchored to the entry fill price.
5. **Equality is invalid (take-profit):** a take-profit exactly equal to the actual entry fill price is not a valid correct-side target — **reject the entry** (record and continue), requiring a strictly correct side. (`stop_loss == fill` is already rejected by the sizing rule's "distance not strictly positive" condition; no separate rule is needed.)
6. **Rejected limit entry is cancelled permanently:** when a working limit entry is rejected at fill under rules 1, 3, or 5, the order is **cancelled** (the entry intent is consumed); it does **not** remain eligible for a later fill.
7. **Stop-trigger predicates (confirmed):** a long stop is touched when `low <= stop`; a short stop is touched when `high >= stop`. These are the authoritative stop-touch conditions matching rule 10's gap-fill formulas.

**Definition — "current market mark" (used by rule 2 only; rule 4, amended, uses the entry fill price):** the most recent completed mark-to-market close. With rule 8, a `MODIFY_PROTECTION` requested after candle `i` is first eligible on candle `i+1`, so the applicable mark is the close of the candle at which the modification was requested (the last completed close before the eligibility candle).

Consequence for sizing: with rules 1 and 3 in force, the sizing distance `|fill_price - stop_loss|` is only used for correctly-oriented stops; a wrong-side stop is rejected at fill rather than sized into a position.

## Milestone 3 — approved quantity precision rule (final)

User-approved. This resolves the open sizing/precision question; it supersedes the former "unresolved implementation details" note. Do not re-open it. Do not invent defaults.

1. **Explicit step, no default:** quantity uses an explicitly configured **positive step/increment per instrument** (e.g. `1`, `0.1`, `0.001`). There are **no implicit defaults**; a missing or non-positive step means the entry is rejected, consistent with the require-explicit-rules decision above.
2. **Round down only:** round the calculated quantity **down** to the nearest valid multiple of the configured step. **Never round up.**
3. **Reject invalid results:** if the rounded quantity is zero or otherwise invalid, **reject the trade**.
4. **Numerically safe arithmetic:** use floating-point-safe arithmetic so representation error cannot produce an invalid lot multiple or a false zero.
5. **Cash constraint unchanged:** preserve the existing rule — **reject the entire entry** if the resulting quantity is unaffordable; never silently downsize to fit available cash.

**Status:** Orientation rules 1–3, 5, 6, and 7 above are approved and recorded as written. **Rule 4 (take-profit modification) was amended by explicit user decision** (see rule 4): take-profit modifications are validated against the **entry fill price**, while stop-loss modifications remain validated against the **current market mark**. All rule-level orientation questions are resolved and none remain open. The M3 engine is **implemented** (`src/execution/`, committed at `7ad7715`), and the Rule 4 amendment **is reflected in code and covered by tests**.

## Milestone 4 — implemented metrics contract

Read-only metrics layer. Pure: derived from an existing `BacktestResult`; it never reruns a strategy, mutates M3 records, or changes execution behaviour. Public API: `src.metrics.compute_metrics(result) -> PerformanceReport`, with frozen dataclasses `PerformanceReport`, `DrawdownResult`, `OpenPositionSummary` and the helper `compute_drawdown(equity_points, initial_capital)`.

Approved policies (do not re-open; these restate the approved M4 decisions):

- Win: `net_pnl > 0`; loss: `net_pnl < 0`; breakeven: `net_pnl == 0`. Breakevens count in the closed-trade total and expectancy, not in the win/loss counts.
- Win rate = wins / all closed trades (breakevens are in the denominator). `None` when there are no closed trades.
- Undefined ratios and averages return `None`; counts and additive monetary totals return `0`.
- Profit factor = `gross_profit / |gross_loss|`; `None` when there are no losing trades (the all-winning case is flagged by `all_trades_winning`) and `0.0` when there are losses but no wins.
- Average winning/losing trade are means of `net_pnl` over trades that are strictly winning / losing; the losing average is signed and negative. Expectancy = mean net P&L per closed trade.
- `total_pnl` / `total_return_pct` reuse the existing `BacktestResult` properties (not re-derived).
- Maximum currency and maximum percentage drawdown are computed **independently** and may occur at different bars. The running peak is initialized to `initial_capital`; percentage is expressed in percentage points (`x 100`). Empty, single-point and flat curves have zero drawdown.
- Average bars held = mean `exit_bar_index - entry_bar_index` (a same-bar entry+exit is `0`).
- `sum(trade.net_pnl)` is verified against `result.realized_pnl` (floating-point comparison); a mismatch raises `MetricsConsistencyError`.
- **F3 preserved:** open-position `unrealized_pnl` stays **gross**. The difference from account-level P&L is reported as an informational `reconciliation_difference` (equal to `-open entry commission` when a position is open, `0.0` when flat) and is never adjusted away.
- Open positions stay separate from completed trades; no synthetic exit trade is created. `OpenPositionSummary` derives `entry_price`/`entry_timestamp`/`entry_bar_index`/`entry_commission` from the last `ENTRY` fill and `mark_price` from the final equity point — both unambiguous for the one-net-position engine.

Out of scope, explicitly deferred: R-multiple counts (require M3 to retain the entry stop/risk level) and target-reachability analytics (require post-entry excursion / MFE-MAE data); also MFE/MAE, Sharpe, annualization, risk-free inputs, and exposure. No UI integration in this milestone. (M3 now retains the entry stop as `Trade.initial_stop` and M13 implements per-trade R-multiples plus the mean/coverage summary, surfaced read-only in the UI by M25; binned R-multiple counts, target reachability, MFE/MAE, Sharpe, annualization, risk-free inputs, and exposure remain deferred.)

## Milestone 5 — implemented scope (per-bar drawdown series)

Approved as a minimal, additive, read-only extension of the M4 metrics library. It does not touch M3 records or behavior, the M4 outputs, or the UI.

- Public API: `src.metrics.compute_drawdown_series(equity_points, initial_capital) -> DrawdownSeries`, plus the frozen dataclasses `DrawdownPoint` (`bar_index`, `equity`, `peak`, `peak_bar_index`, `decline_currency`, `decline_pct`) and `DrawdownSeries` (immutable tuple `points`).
- Same conventions as the M4 `compute_drawdown`: the running peak starts at `initial_capital` and updates when `equity >= peak` (the latest bar wins ties); `decline_currency = peak - equity`; `decline_pct = decline_currency / peak * 100` when `peak > 0`, otherwise `0.0` (values in percentage points). Input order and bar indices are preserved; an empty input yields an empty series; the input is never mutated.
- Parity is enforced by tests: the series' maximum currency/percentage declines and their peak/trough bar indices match `compute_drawdown` on the engine fixture and on hand-built curves, including duplicate maximum-drawdown values (M4 keeps the first bar because it updates only on a strictly greater decline).

Explicitly excluded (deferred): binned R-multiple counts (histograms), target reachability, MFE/MAE, Sharpe, annualization, risk-free inputs, and exposure. No UI integration, no `PerformanceReport` change, no new ledger abstraction/export, and no engine or model change.

Auditable ledger: the documented "auditable trade logs" requirement is already satisfied by the M3 `Trade`/`Fill`/`Rejection`/`UnfilledOrder` records (deterministic, ordered, immutable) together with the M4 realized-P&L reconciliation; M5 adds no redundant ledger abstraction and no export feature.

## Milestone 7 — implemented scope (metrics & drawdown dashboard)

Approved as a minimal, additive, read-only UI integration of the committed M4 metrics and M5 drawdown series. It does not touch the engine, strategy interface, data loading/validation, the M4 metrics library, or the M5 drawdown series.

- `app.py` renders a **Performance metrics** panel beneath the existing accounting summary, populated by `src.ui.workflow.performance_summary`, and a **Drawdown (%)** per-bar percentage chart beneath the equity curve, built by `drawdown_to_dataframe`, which wraps the committed M5 series (`src.metrics.compute_drawdown_series`).
- `performance_summary(result)` returns an ordered list of `(label, value)` rows covering every M4 `PerformanceReport` field: trade counts, win rate, expectancy, profit factor, gross/net realized and total P&L, total return, averages, average bars held, maximum currency/percentage drawdown with its peak/trough bar indices, the reconciliation difference, and — only when a position is open — the `OpenPositionSummary` details.
- Undefined metrics (`None`) render as `n/a` and are never shown as `0`; counts and additive monetary totals continue to render their real values. `Total P&L`, `Total return`, and `Open position` intentionally appear in both the accounting summary and the metrics panel.
- `drawdown_to_dataframe(result)` returns a chart-ready, timestamp-indexed frame of the M5 per-bar percentage declines (already percentage points, plotted without rescaling); it preserves input bar order and the M5 initial-capital peak anchor.
- A `MetricsConsistencyError` raised while computing the panel is caught and surfaced with `st.error` (the run continues); unrelated exceptions are left to propagate so failures remain visible rather than being silently swallowed.
- The pre-existing `result_summary` (accounting summary), equity curve, trades, fills, rejections, and unfilled-orders sections are unchanged; the integration adds no new dependency and changes no engine behavior.

Explicitly excluded (deferred, unchanged from M4/M5): binned R-multiple counts (histograms), target reachability, MFE/MAE, Sharpe, annualization, risk-free inputs, and exposure.

## Milestone 8 — implemented scope (validated trade-to-fill linkage)

Approved as a narrow, pure, library-only helper. It does not touch the UI, the models, the engine, or the accounting, and it adds no dependency.

- Public API in `src/ui/workflow.py`: `link_trade_fills(result) -> tuple[LinkedTrade, ...]`, the frozen dataclass `LinkedTrade` (`index`, `trade`, `entry_fill`, `exit_fill`), and the exception `TradeFillLinkageError` (a `ValueError` subclass, matching `MetricsConsistencyError` / `StrategyCodeError`).
- Pairing is **positional** from the fill-stream order (fills `2k` / `2k+1` for trade `k`); it never joins on timestamps or tags. Timestamps collide on same-bar round trips and tags are not join keys (a manual `EXIT` tag may differ from the position tag; protection closes inherit it).
- Each pair is validated field-by-field against the trade: direction, quantity, entry/exit bar index, timestamp, price, commission, entry kind, exit kind, and tag; float comparisons use `math.isclose(rel_tol=1e-9, abs_tol=1e-9)`. A flat result must have exactly `2N` fills; an open result exactly `2N+1`, the trailing fill being the single unmatched `ENTRY`. Malformed, out-of-order, or self-inconsistent streams fail loudly (`Linkage unavailable` / `Malformed fill stream` / `Out-of-order fill stream`).
- A position left open at the end of the data is validated but paired with no trade; no synthetic exit or completed trade is ever created. `Fill.side` and `Fill.slippage` have no `Trade` counterpart and are deliberately not validated (documented in tests).

## Milestone 9 — implemented scope (trade-to-fill audit trail)

Approved as a minimal, additive, read-only UI integration of the committed M8 linkage. It does not touch the engine, strategy interface, data loading/validation, the M4 metrics, the M5 drawdown series, or the M8 helper, and it adds no dependency.

- `app.py` renders a **Trade audit trail** section between the existing **Trades** and **Fills** sections. All pre-existing sections and their behaviour are preserved.
- `linked_trades_to_dataframe(result)` returns one row per completed trade pairing the trade's identity/economics (`trade` index, direction, quantity, gross/net P&L) with its validated entry and closing fill details (bar, timestamp, price, commission, tag) plus the closing fill's kind. The entry kind is omitted (always `ENTRY`, validated by the linkage); `side`/`slippage` are omitted because they take part in no validated comparison.
- `linked_fills_to_dataframe(result)` returns the existing `fills_to_dataframe` frame with a `linkage` column appended (existing columns and order preserved), so the single fills table is **annotated in place**, not duplicated. Values are `"Trade <n> entry"` / `"Trade <n> close"` (0-based), or the constant `OPEN_POSITION_ENTRY_LINKAGE` = **"Open-position entry — no completed trade."** for the unmatched trailing `ENTRY` fill of an open position.
- A position left open at the end of the data is labelled, never given a synthetic exit or completed-trade row; when there are no completed trades the section reports "No completed trades to audit.".
- A `TradeFillLinkageError` raised while building either frame is caught and surfaced with `st.error` (the run continues), and the **Fills** section falls back to the un-annotated `fills_to_dataframe` view so the remaining results still render. Unrelated exceptions are left to propagate so failures stay visible.
- Both helpers are pure and read-only: they inspect `result` only, never mutate it, never rerun the strategy, and are deterministic.

Explicitly excluded (deferred, unchanged): binned R-multiple counts (histograms), target reachability, MFE/MAE, Sharpe, annualization, risk-free inputs, and exposure; also the earlier M8 UI items (`trade_bar_window`, in-place ledger timestamp/tag columns).

## Milestone 10 — implemented scope (execution-engine test-gap coverage)

Closes the two M3 test gaps previously recorded under "Verification" as intentionally left. Test-only: no engine, model, accounting, metric, loader, UI, M8, or M9 code changes, and no new dependency.

- **Reverse per-field protection-modification combination:** a single `MODIFY_PROTECTION` whose stop-loss is valid (correct side of the request-candle mark, rule 2) while its take-profit is invalid (wrong side of the entry fill, rule 4, amended) stages the stop and rejects only the take-profit; the prior take-profit is retained. Covered for both long and short (`test_modification_stop_applied_while_take_profit_rejected_same_decision`, `test_short_modification_stop_applied_while_take_profit_rejected_same_decision`).
- **Multiple `MODIFY_PROTECTION` decisions in one bar:** they apply in list order (approved bar loop); for each field the last valid staged write is the one that becomes eligible on the next candle, and a rejected later decision does not clobber an earlier valid staged value. Covered for the stop-loss and take-profit fields plus the rejection interaction (`test_multiple_modifications_in_one_bar_last_stop_wins`, `test_multiple_modifications_in_one_bar_last_take_profit_wins`, `test_multiple_modifications_in_one_bar_rejected_one_preserves_staged_value`).

## Milestone 13 — implemented scope (R-multiple analytics)

Approved as a minimal, additive, strategy-agnostic metric. It changes no entry validation, sizing, fill prices, stop execution, commissions, slippage, P&L, trade ordering, or open-position accounting; adds no field to `PerformanceReport`/`OpenPositionSummary`; adds no UI column at M13 (the read-only UI surfacing arrived later in M25); and does not alter the M8 linkage or the M9 audit trail.

- **Initial stop captured at entry (Phase 1):** `_Position` gains an internal `initial_stop` field set once from the validated entry stop (`order.stop_loss`) when the position is created and never changed by protection modifications; `_Position.stop_loss` keeps its existing meaning as the mutable working stop. `_close_position` copies `position.initial_stop` onto the completed record.
- **Additive model field:** `Trade.initial_stop: Optional[float] = None` — a new defaulted, backward-compatible descriptive field (existing keyword-only construction and synthetic fixtures are unaffected). It is descriptive only and participates in no execution or accounting calculation.
- **Exact formula:** with `E = Trade.entry_price`, `S0 = Trade.initial_stop` (the stop at entry, before any later modification), `Q = Trade.quantity` and `P = Trade.net_pnl` (net of the existing entry/exit commissions; slippage is already embedded in the actual fill prices): `initial_risk = Q * abs(E - S0)` and `R = P / initial_risk`. Commissions are **not** added to the denominator, and the denominator is anchored to the initial stop, so modifying the working stop does not change it; a trade closed at a modified stop is therefore **not** guaranteed to be exactly `-1R`.
- **Public API** in the new module `src/metrics/r_multiple.py` (exported from `src.metrics`), following the existing metrics conventions: `trade_r_multiple(trade) -> Optional[float]` returns `None` (never `0`) when any required input is absent/non-numeric/non-finite, when the initial risk is not strictly positive (missing initial stop, zero entry-to-stop distance, or non-positive quantity), or when the resulting R-multiple is non-finite — it never raises an arithmetic exception; and the frozen dataclass `RMultipleSummary(mean_r, computable_count, non_computable_count)` built by the pure helper `compute_r_multiple_summary(trades)`. The mean excludes `None` values and is `None` when no trade is computable; an empty collection yields `mean_r=None` and both counts `0`. No sum R, histogram, annualization, or other analytics are added.
- **Boundaries preserved:** the metric is derived purely from the immutable M3 `Trade` records — no backtest is rerun, no execution/accounting semantics are changed to force a preferred R, and `PerformanceReport`/`OpenPositionSummary`, the UI columns (at M13; the read-only `r_multiple` Trades column and the mean/coverage panel rows were added later in M25), and the M9 audit trail are untouched. Verified by `tests/test_execution/test_engine_initial_stop.py` and `tests/test_metrics/test_r_multiple.py`.

## Current work and next actions

Current: **M4 metrics layer implemented** in `src/metrics/` (see "Milestone 4 — implemented metrics contract"); it is read-only and derived from M3 records. **M3 engine implemented** in `src/execution/` (approved rules, defaults A–E, per-field protection-modification rejection; Rule 4 correction applied — take-profit modifications are validated against the entry fill price and stop-loss modifications against the current market mark). **M5 drawdown series implemented** in `src/metrics/drawdown.py` (see "Milestone 5 — implemented scope"). **M7 metrics & drawdown dashboard implemented** in `app.py` + `src/ui/workflow.py` (see "Milestone 7 — implemented scope"). **M8 validated trade-to-fill linkage implemented and committed** at `8186f20` (see "Milestone 8 — implemented scope"). **M9 trade-to-fill audit trail implemented and committed** at `dcdde65` in `app.py` + `src/ui/workflow.py` (see "Milestone 9 — implemented scope"). **M10 execution-engine test-gap coverage implemented and committed** at `4227413` in `tests/test_execution/test_engine_protection.py` (see "Milestone 10 — implemented scope"). **M13 R-multiple analytics implemented and committed** at `4227413` in `src/metrics/r_multiple.py` + `src/execution/` (see "Milestone 13 — implemented scope"). **M25 R-multiple UI integration implemented and committed** at `0dffc7c` in `src/ui/workflow.py` + `tests/test_ui/` (read-only surfacing of the M13 per-trade R-multiple and its mean/coverage summary; see the milestone table). **M34/M36 read-only results filtering implemented and committed** at `983acdc` in `app.py` + `src/ui/workflow.py` (read-only filter widgets plus the reusable `filter_rows` helper narrowing the Trades, trade audit trail, Fills, and Rejections tables; the audit-trail filter reuses the M9 exit-kind mapping; see the milestone table). **M6 initial UI implemented** in `app.py` + `src/ui/` (initial workflow; the specified workflow is functionally complete, the audit-trail slice of the broader dashboard scope is addressed by M8/M9, and the remainder has no defined specification and requires a supervisor decision). The principal approved paths and the rule 4 amendment are covered by `tests/test_execution/`, the M4 contract and the M5 drawdown series by `tests/test_metrics/`, and the M6 workflow, M7 dashboard, M8 linkage, and M9 audit trail by `tests/test_ui/`; the M10 pass closes the two previously-recorded M3 gaps, and coverage remains deliberately not exhaustive. Full suite: **320 passed** (fresh results verified for this documentation change).

Engine API: `run_backtest(strategy, df, EngineConfig(initial_capital, risk_fraction XOR risk_absolute, quantity_step, commission_per_fill, slippage_fraction)) -> BacktestResult`. `strategy.on_start()` runs before the loop and `on_finish()` after it. A structural validation failure raises `StrategyValidationError` and aborts the run; state-incompatible decisions are recorded and the run continues.

Implementation interpretations recorded (these restate the approved rules, they introduce no new trading rules):
- Protection-modification fields are validated **per field**: the stop-loss against the request-candle close (the "current market mark", rule 2), and the take-profit against the **entry fill price** (rule 4). A wrong-side field is rejected and keeps its prior level, while a valid sibling field in the same decision is applied.
- `MODIFY_PROTECTION` is staged and becomes active at the start of the next candle (rule 8); stop-loss validation uses the mark at the request candle, and take-profit validation uses the entry fill price (rule 4, amended).
- `BacktestResult.unfilled_orders` records working orders that expire unfilled at end of data (rule 13); an open position at end of data is left open and marked at the final close (default E).
- **Entry-candle protection scope (approved convention, F1):** protection is evaluated against the **full entry candle** for both market and limit entries. OHLC bars cannot distinguish movement before vs. after a limit fill within the same candle, so a limit entry's stop or target may be triggered by a price the candle reached before the fill. This is the approved, deterministic convention (rule 7 read as "the entry candle as a whole"); see `test_limit_entry_protection_uses_full_entry_candle_range`.
- **P&L convention (approved, F3):** `BacktestResult.unrealized_pnl` is **gross** — `qty * (close - entry)` long, `qty * (entry - close)` short — and does not deduct the open position's entry commission, whereas equity-based `total_pnl` / `final_equity` already reflect commissions actually charged at execution. Therefore `realized_pnl + unrealized_pnl` can differ from `total_pnl` by the open trade's entry commission; this is intended, not a defect.

Remaining / deferred: M4 metrics layer is committed (`ef2cb46`), the M5 per-bar drawdown series is committed (`6c50daf`), the M7 metrics & drawdown dashboard is committed (`6b31b74`), the M8 linkage is committed (`8186f20`), and the M9 audit trail is committed (`dcdde65`) (see above). The M10 execution-engine test-gap coverage and the M13 R-multiple analytics are implemented and committed in `4227413` (see above). Per-trade R-multiples and their mean/coverage summary are implemented (library M13; surfaced read-only in the UI by M25), and read-only results filtering (Trades `direction`/`exit_kind`, Fills `kind`/`direction`, Rejections `reason`, and the audit trail) is implemented and committed at `983acdc` (no other filter dimensions are implemented); binned R-multiple counts, target reachability, MFE/MAE, Sharpe, annualization, and exposure remain deferred. The UI is a single-page Streamlit workflow; beyond the M8/M9 audit-trail slice, the broader "full audit dashboard" has no defined specification and requires a supervisor decision; README was updated for M3/M6 under prior user authorization, for M5/M7 and M8/M9 in earlier reconciliations, and for M10 and the M13 R-multiple metric in the documentation reconciliations committed in `4227413`.

Running the UI: from the repository root, `.\.venv\Scripts\python.exe -m streamlit run app.py` (or `streamlit run app.py`). Place datasets in `data/raw/` or upload them in the app.

Verification: `.\.venv\Scripts\python.exe -m pytest tests -q` → **320 passed** (213 at M7: 150 original + 35 M4 metrics + 19 M5 drawdown-series + 9 M7 UI tests; plus 43 M8 linkage tests, 15 M9 audit-trail tests, 5 M10 execution-coverage tests, 19 M13 R-multiple tests, 5 M25 R-multiple UI tests, and 20 M34/M36 results-filtering tests; **107** of the 320 are the UI tests in `tests/test_ui/`). (Fresh results verified for this documentation change.) The expanded M3 suite adds symmetric (short) coverage for rules 1, 3, 5, and 6; short stop-loss modifications (rule 2); limit-entry entry-candle protection (rule 7, F1); short SL-before-TP (rule 9) and short take-profit gap fills (rule 10); final-candle and working-exit expiry (rule 13); and closed short / SL / TP realized P&L with commission (rule 14). The M4 metrics suite covers counts/win-rate denominator, breakeven/undefined-ratio cases, profit-factor edges, averages (signed losing average), expectancy, bars-held (including same-bar), drawdown (initial-capital baseline; independent currency and percentage drawdowns; empty/single/flat/monotonic/peak-to-trough), open-position summary and F3 reconciliation (gross unrealized P&L; no synthetic exit), determinism and input immutability, and the invariants. The M10 pass closes the two previously-recorded M3 gaps: the reverse per-field modification combination (stop applied while the take-profit is rejected in the same decision; covered for long and short) and multiple `MODIFY_PROTECTION` decisions in one bar (per-field last-valid-write ordering in list order, plus a rejected later decision retaining an earlier valid staged value). The R-multiple counts and target-reachability analytics are explicitly out of scope for M4 (require M3 record extensions and post-entry excursion data). The M5 suite covers the per-bar drawdown series: exact hand-calculated per-bar values, the initial-capital baseline, latest-peak tie-breaking, empty/single/flat/monotonic curves, non-positive running peaks, determinism, frozen dataclasses, input immutability, and M4 parity (maximum currency/percentage values and first-occurrence trough/peak indices, including duplicate maximum-drawdown values). The M7 suite covers the performance-metrics panel (all `PerformanceReport` fields, `None` → `n/a`, open-position details), the `MetricsConsistencyError` surfacing path, and the drawdown chart frame (M5 parity, initial-capital peak anchor, input-order preservation, and the empty-curve case); it also asserts the accounting summary and the results section ordering are unchanged. The M8 suite covers empty/open-position streams, three sequential trades, positional (not timestamp) pairing on same-bar round trips, entry/exit tags that differ, rejected entries and reversal attempts that add no fill, the engine-generated `2N+1` open position, synthetic trades without fills, per-field trade/fill validation (trade and fill fields, and protection-close exit kinds), malformed and out-of-order streams, the deliberate non-validation of `side`/`slippage`, and purity (deterministic, non-mutating, never reruns). The M9 suite covers the audit frame (all columns and their exact correspondence to the paired source records, hand-computed engine rows), the annotated fills frame (original columns preserved, roles in stream order), same-bar collisions, the labelled open position with no synthetic row, empty results, differing entry/exit tags, linkage-error propagation, read-only determinism, and — through Streamlit `AppTest` — the section placed between Trades and Fills, the in-place fills annotation, the surfaced `TradeFillLinkageError` (from either helper) with the remaining sections still rendering and no stale audit table, the propagation of unrelated exceptions, and the open-position entry with no completed-trade row. The M25 suite covers the read-only R-multiple UI integration: the Trades `r_multiple` column values, an undefined R without an initial stop, the `Mean R` and computable/non-computable panel rows, an undefined mean rendered as `n/a`, and — through Streamlit `AppTest` — the panel rows and the Trades column.

## Constraints

- No hardcoded strategies, BOS/CHoCH/SMC, indicators, CLI, or YAML/JSON strategy language. A GUI is permitted **only** as the user-authorized Streamlit workflow (`app.py`, `src/ui/`); it must not embed trading logic.
- Never fill a market order on the signal candle. Never let strategy APIs see future candles.
- Do not claim the backtest is realistic; document simulation assumptions.
- Do not invent trading rules; ask when a choice materially affects results.
- Keep M3 small; no premature abstractions.
- Do not change M1 loader/validator without approval.
- Do not delete code, tests, docs, or conversation data to save tokens.

## Known limitations

- A clean checkout of `master` is at `983acdc` (Milestones 1–5 committed, plus the initial M6 UI, the M7 metrics & drawdown dashboard, the M8 validated trade-to-fill linkage, the M9 trade-to-fill audit trail, the M10 execution-coverage tests and M13 R-multiple analytics combined into `4227413`, the milestone-status/M6 documentation reconciliation at `ad1e30d`, the M25 R-multiple UI integration at `0dffc7c`, the M25 documentation reconciliation at `2a7a401`, and the M34/M36 read-only results filtering at `983acdc`). The M6 Streamlit workflow is initial; the audit-trail slice of the broader dashboard scope is addressed by M8/M9, and the remainder has no defined specification and requires a supervisor decision.
- `StrategyDecision` / `PositionView` have no quantity; sizing is engine-side (risk-based at fill). Quantity precision is a configured positive step, rounded down (see the approved precision rule).
- `AccountView` does not expose realized/unrealized P&L.
- Lookahead protection is not hostile-code isolation; the UI executes user-supplied strategy code in-process (`exec`) by design.
- Performance metrics (M4) and the per-bar drawdown series (M5) are implemented and surfaced read-only in the UI (M7); the validated trade-to-fill linkage (M8) is surfaced read-only as the trade audit trail (M9). Per-trade R-multiple analytics and their mean/coverage summary are implemented (library M13; surfaced read-only in the UI by M25); the extended ledger and the target-reachability analytics remain deferred.
- `Fill.side` and `Fill.slippage` have no `Trade` counterpart, so the M8 linkage does not validate them; the M9 audit rows therefore omit them.
- The UI assumes the strategy source defines exactly one `Strategy` subclass (or a module-level `strategy` instance), and reads files from `data/raw/` or an uploaded file.
