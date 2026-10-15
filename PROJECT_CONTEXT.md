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
| 2 Strategy interface | Complete in **working tree**, not committed | `src/strategy/`, `tests/test_strategy/` |
| 3 Execution engine | Complete in **working tree**, not committed | `src/execution/`, `tests/test_execution/` |
| 4 Metrics layer | Implemented in **working tree**, not committed | `src/metrics/`, `tests/test_metrics/`; read-only, derived from M3 records |
| 5 Extended ledger | Deferred | M3 `Trade`/`Fill`/`EquityPoint` records already form the ledger |
| 6 Streamlit UI | Initial workflow implemented in **working tree** (user-authorized) | `app.py`, `src/ui/`, `tests/test_ui/` |

README is user-facing and `PROJECT_CONTEXT.md` is implementation memory; README was updated for M3/M6 under prior user authorization (M3 marked complete; M6 described as an initial workflow).

## Git (do not stage or commit unless asked)

- Branch: `master` at `7ad7715` (“feat: strategy interface, execution engine, and Streamlit UI (M2/M3/M6)”). M2/M3/M6 were committed from `c46e62b`; the M1 commit `c46e62b` is intact.
- Uncommitted: M4 metrics layer — `src/metrics/`, `tests/test_metrics/`, plus this `PROJECT_CONTEXT.md` update.
- Preserve all committed work and the uncommitted M4 layer. Do not rewrite loader/validator behavior, existing strategy models, or M3 execution without an identified need and approval.

Baseline tests: `.\.venv\Scripts\python.exe -m pytest tests -q` → **185 passed** (150 pre-M4 + 35 M4 metrics). (Verified by running the full suite during the M4 implementation pass.)

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
- **Not yet decided (Phase B plumbing; no trading rule):** the concrete **configuration/API shape** — where and how the risk budget, the per-instrument **positive step**, initial capital, and cost parameters are supplied and validated (config object vs. explicit arguments, field names, types, and validation errors). This is implementation plumbing only and does not change any approved simulation semantics.

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

**Status:** Orientation rules 1–3, 5, 6, and 7 above are approved and recorded as written. **Rule 4 (take-profit modification) was amended by explicit user decision** (see rule 4): take-profit modifications are validated against the **entry fill price**, while stop-loss modifications remain validated against the **current market mark**. All rule-level orientation questions are resolved and none remain open. The M3 engine is **implemented in the working tree** (`src/execution/`, not committed), and the Rule 4 amendment **is reflected in code and covered by tests**.

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

Out of scope, explicitly deferred: R-multiple counts (require M3 to retain the entry stop/risk level) and target-reachability analytics (require post-entry excursion / MFE-MAE data); also MFE/MAE, Sharpe, annualization, risk-free inputs, and exposure. No UI integration in this milestone.

## Current work and next actions

Current: **M4 metrics layer implemented** in `src/metrics/` (see "Milestone 4 — implemented metrics contract"); it is read-only and derived from M3 records. **M3 engine implemented** in `src/execution/` (approved rules, defaults A–E, per-field protection-modification rejection; Rule 4 correction applied — take-profit modifications are validated against the entry fill price and stop-loss modifications against the current market mark). **M6 initial UI implemented** in `app.py` + `src/ui/`. The principal approved paths and the rule 4 amendment are covered by `tests/test_execution/`, the M4 contract by `tests/test_metrics/`, and the M6 workflow by `tests/test_ui/`; coverage is deliberately not exhaustive (remaining known gaps are noted under "Verification" below). Full suite: **185 passed**.

Engine API: `run_backtest(strategy, df, EngineConfig(initial_capital, risk_fraction XOR risk_absolute, quantity_step, commission_per_fill, slippage_fraction)) -> BacktestResult`. `strategy.on_start()` runs before the loop and `on_finish()` after it. A structural validation failure raises `StrategyValidationError` and aborts the run; state-incompatible decisions are recorded and the run continues.

Implementation interpretations recorded (these restate the approved rules, they introduce no new trading rules):
- Protection-modification fields are validated **per field**: the stop-loss against the request-candle close (the "current market mark", rule 2), and the take-profit against the **entry fill price** (rule 4). A wrong-side field is rejected and keeps its prior level, while a valid sibling field in the same decision is applied.
- `MODIFY_PROTECTION` is staged and becomes active at the start of the next candle (rule 8); stop-loss validation uses the mark at the request candle, and take-profit validation uses the entry fill price (rule 4, amended).
- `BacktestResult.unfilled_orders` records working orders that expire unfilled at end of data (rule 13); an open position at end of data is left open and marked at the final close (default E).
- **Entry-candle protection scope (approved convention, F1):** protection is evaluated against the **full entry candle** for both market and limit entries. OHLC bars cannot distinguish movement before vs. after a limit fill within the same candle, so a limit entry's stop or target may be triggered by a price the candle reached before the fill. This is the approved, deterministic convention (rule 7 read as "the entry candle as a whole"); see `test_limit_entry_protection_uses_full_entry_candle_range`.
- **P&L convention (approved, F3):** `BacktestResult.unrealized_pnl` is **gross** — `qty * (close - entry)` long, `qty * (entry - close)` short — and does not deduct the open position's entry commission, whereas equity-based `total_pnl` / `final_equity` already reflect commissions actually charged at execution. Therefore `realized_pnl + unrealized_pnl` can differ from `total_pnl` by the open trade's entry commission; this is intended, not a defect.

Remaining / deferred: M4 metrics layer has been implemented (read-only, derived from M3 records; see above). M5 extended ledger remains deferred. The UI is a single-page Streamlit workflow; README was updated for M3/M6 under prior user authorization.

Running the UI: from the repository root, `.\.venv\Scripts\python.exe -m streamlit run app.py` (or `streamlit run app.py`). Place datasets in `data/raw/` or upload them in the app.

Verification: `.\.venv\Scripts\python.exe -m pytest tests -q` → **185 passed** (150 original + 35 M4 metrics). The expanded M3 suite adds symmetric (short) coverage for rules 1, 3, 5, and 6; short stop-loss modifications (rule 2); limit-entry entry-candle protection (rule 7, F1); short SL-before-TP (rule 9) and short take-profit gap fills (rule 10); final-candle and working-exit expiry (rule 13); and closed short / SL / TP realized P&L with commission (rule 14). The M4 metrics suite covers counts/win-rate denominator, breakeven/undefined-ratio cases, profit-factor edges, averages (signed losing average), expectancy, bars-held (including same-bar), drawdown (initial-capital baseline; independent currency and percentage drawdowns; empty/single/flat/monotonic/peak-to-trough), open-position summary and F3 reconciliation (gross unrealized P&L; no synthetic exit), determinism and input immutability, and the invariants. Remaining known gaps (not blocked, intentionally left): the reverse per-field modification combination (stop applied while the take-profit is rejected in the same decision) and multiple `MODIFY_PROTECTION` decisions in one bar. The R-multiple counts and target-reachability analytics are explicitly out of scope for M4 (require M3 record extensions and post-entry excursion data).

## Constraints

- No hardcoded strategies, BOS/CHoCH/SMC, indicators, CLI, or YAML/JSON strategy language. A GUI is permitted **only** as the user-authorized Streamlit workflow (`app.py`, `src/ui/`); it must not embed trading logic.
- Never fill a market order on the signal candle. Never let strategy APIs see future candles.
- Do not claim the backtest is realistic; document simulation assumptions.
- Do not invent trading rules; ask when a choice materially affects results.
- Keep M3 small; no premature abstractions.
- Do not change M1 loader/validator without approval.
- Do not delete code, tests, docs, or conversation data to save tokens.

## Known limitations

- M2/M3/M6 are uncommitted; a clean checkout of `master` has the data layer only.
- `StrategyDecision` / `PositionView` have no quantity; sizing is engine-side (risk-based at fill). Quantity precision is a configured positive step, rounded down (see the approved precision rule).
- `AccountView` does not expose realized/unrealized P&L.
- Lookahead protection is not hostile-code isolation; the UI executes user-supplied strategy code in-process (`exec`) by design.
- Performance metrics are minimal (accounting summary + equity curve); the full trade ledger/metrics milestones are deferred.
- The UI assumes the strategy source defines exactly one `Strategy` subclass (or a module-level `strategy` instance), and reads files from `data/raw/` or an uploaded file.
