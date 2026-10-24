# SignalGate EA — MetaTrader 5 Setup (DEMO ONLY)

This Expert Advisor connects MetaTrader 5 to the SignalGate backend. It polls
for approved, structured commands and places **demo trades only**.

> ⚠️ **Demo only.** The EA requires a positively identified MT5 DEMO account;
> REAL, CONTEST and unknown modes are refused at startup and each timer cycle.
> Use a dedicated **flat** broker demo account for testing. Any existing open
> position or pending order blocks new command polling, even if its broker
> comment/magic was changed or lost after a restart.

## 1. Compile the exact candidate EA

For release acceptance, prefer the automated evidence harness in `docs/MT5_ACCEPTANCE.md` rather than manually compiling an untracked copy. It binds the compiler receipt to the exact frozen candidate SHA and requires **0 errors / 0 warnings**.

For a normal manual install:

1. Open **MetaEditor** (from MT5: Tools → MetaQuotes Language Editor).
2. In the Navigator, right-click **Experts** → **Open Folder** (this is
   `.../MQL5/Experts`).
3. Copy the candidate `SignalGateEA.mq5` into that `Experts` folder.
4. Back in MetaEditor, open `SignalGateEA.mq5` and press **Compile** (F7).
5. Do not treat the compile as release evidence unless the candidate SHA/source hash and compiler log are retained.

## 2. Allow the backend URL for WebRequest

The EA uses `WebRequest()` to talk to the backend. MT5 blocks this unless the
URL is whitelisted:

1. In MT5: **Tools → Options → Expert Advisors**.
2. Tick **Allow WebRequest for listed URL**.
3. Add: `http://127.0.0.1:8000` (or your `BACKEND_URL`).
4. Click OK.

## 3. Enable algo trading

- Keep the **Algo Trading** toolbar switch OFF while inspecting inputs. Enable
  it only for an independently reviewed, exact-commit build on a positively
  identified **DEMO** account, after the MT5 demo-scenario gate is satisfied.
- `EnableTrading` also defaults to **false**. This per-EA input and the MT5
  toolbar switch are separate; neither bypasses the demo-only guard.

## 4. Attach to a chart

1. Open a **XAUUSD** chart on your **demo** account.
2. Drag **SignalGateEA** from Navigator → Experts onto the chart.
3. In the inputs dialog set at minimum:
   - `BackendURL` = the exact backend URL you whitelisted;
   - `LicenseKey` = **your one-time customer EA licence** in hosted Provider Edition;
   - `EAApiKey` = the server's EA service credential supplied through the approved onboarding channel;
   - `UserID` = local-demo compatibility only (may be empty in hosted mode); hosted ownership is resolved from `LicenseKey`;
   - `DemoOnlyMode` = `true` (leave as-is);
   - `SplitTicketDemoPartialMode` = `true` on a hedging demo account (the EA safely falls back on non-hedging/netting accounts);
   - `EnableTrading` = `false` until independent EA review, exact MetaEditor compile and controlled MT5 broker-DEMO acceptance are complete.
4. Click OK. A smiley face in the top-right of the chart means it is running.

## 5. Inputs reference

| Input | Default | Meaning |
|-------|---------|---------|
| `BackendURL` | `http://127.0.0.1:8000` | SignalGate backend base URL |
| `UserID` | `USER-000001` | Local-demo compatibility id. Hosted mode does not trust this as customer identity. |
| `LicenseKey` | `local-demo` | **Required customer identity credential in hosted mode.** Sent as `X-SG-License-Key`; keep private. |
| `EAApiKey` | `local-demo-ea-key` | EA service credential. Hosted calls require this in addition to the customer licence. |
| `PollIntervalSeconds` | `2` | How often to poll/manage |
| `SingleTicketFixedLot` | `0.01` | Lot for single-ticket fallback mode |
| `SplitTicketDemoPartialMode` | `true` | Open 3 child tickets for 50/25/25 |
| `TP1Lot` / `TP2Lot` / `TP3Lot` | `0.02 / 0.01 / 0.01` | Child lots |
| `MagicNumber` | `440044` | EA position tag |
| `DemoOnlyMode` | `true` | Hard safety; EA won't run if false/live |
| `MaxSpreadPoints` | `500` | Reject if spread above this |
| `MaxSlippagePoints` | `100` | Deviation allowance |
| `EnableTrading` | `false` | **OFF by default.** Per-EA input; explicitly enable only for an accepted demo build. Not an emergency position-flattening switch. |
| `SymbolOverride` | `""` | Force a chart symbol name if broker differs |

## 6. How it trades (split-ticket demo partial mode)

A single 0.01 lot position **cannot** be partially closed 50/25/25 (that needs
0.005 lots, below the 0.01 lot step). So in demo we open **three child
positions** that together emulate partial profit-taking:

- TP1 child: `TP1Lot` (0.02), TP = TP1
- TP2 child: `TP2Lot` (0.01), TP = TP2
- TP3 child: `TP3Lot` (0.01), TP = TP3
- Total demo exposure: ~0.04 lots, all sharing the same initial SL.

Management (pending independent review and real demo-broker validation):
- TP-stage success requires the **assigned child's** original opening deal and
  position identifier, and full-volume TP exit history. A child count or an
  earlier child's TP exit cannot establish another milestone.
- Following verified TP1/TP2 exits, remaining stops target breakeven/TP1.
  The volume-weighted broker entry stays unchanged for execution reporting, but
  protective SL prices are rounded to the broker's `SYMBOL_TRADE_TICK_SIZE`
  (BUY down, SELL up) before submitting a stop request. A rounded target still
  requires broker `DONE` and matching current-position SL readback; broker
  rejections/unknowns remain failures and are not automatically retried.
- TP3 is credited only for its own broker TP exit and proven earlier milestones.
  Manual or unknown full closes are never fabricated as TP successes.
- `STOP_LOSS_HIT` uses the **latest matching broker exit**, not an earlier SL.
  When distinct final exits share a broker millisecond but report conflicting
  reasons, stop-out attribution fails closed rather than sorting by deal ticket.
  `FULLY_CLOSED` then records closure without asserting a verified stop reason.
- These are source changes awaiting MetaEditor and actual broker-demo proof.

Set `SplitTicketDemoPartialMode = false` to use single-ticket fallback (one
0.01 lot, full close at the final TP, no impossible partials).

## 7. Known MQL5 limitations

- **No standard JSON library.** MQL5 ships none. This EA includes a small,
  deterministic extractor (`JsonGet*`) tuned to the **exact** backend command
  shape. It is not a general JSON parser; if the backend payload shape changes,
  update those helpers. No external/unbundled libraries are required.
- **Positive DEMO detection** requires `ACCOUNT_TRADE_MODE_DEMO` at startup
  and every timer cycle. REAL, CONTEST and unknown values fail closed. A broker
  that misreports its account mode is an unresolved external dependency; verify
  the terminal account independently before any controlled broker-demo tests.
- **Flat account prerequisite:** when no command is actively managed in memory,
  fresh polling is blocked by *any* open position or pending order, regardless
  of symbol, position comment or magic. This conservative demo-only isolation
  catches broker-mutated/orphan positions after restart but also blocks new
  commands while unrelated/manual positions exist. It cannot prove orphan
  identity or reconstruct management state; broker-demo S8 remains `NOT_RUN`.
- Broker history, position identifiers and live stop-loss readbacks can be
  unavailable or incomplete. Stage/SL checks must fail closed in these cases.
  Test rejected modifications, manual partial/final closes and broker-modified
  comments on a controlled **demo** terminal before accepting the candidate.
- `EnableTrading = false` pauses timer processing, including management and
  reconciliation; it **does not flatten positions** or cancel broker-side
  stops/targets. Check positions and manage them separately before pausing.
- **Pre-order acknowledgement uncertainty:** before sending `/commands/{id}/received`,
  the EA writes `SignalGate_ack_abort.txt` under that terminal's MQL5 Files
  folder, binding the claimed command to the broker-DEMO login/server, backend
  URL, user ID and magic number (never storing licences/API secrets).
  If acknowledgement fails or its HTTP outcome is unknown, the EA sends **no
  broker order** and blocks all further polling. It retries only the *same*
  `FAILED / ACK_RECEIPT_UNCONFIRMED` execution receipt, at most every 30
  seconds, until the backend confirms it. The journal survives terminal
  restarts; mismatched/unreadable journals cause startup refusal. Recovery
  runs even with `EnableTrading=false`; it will not claim "no execution"
  while the DEMO account has any position or pending order. Do not delete a
  stuck journal merely to turn trading on: inspect broker history, backend
  receipts and the account/terminal binding, then involve the coordinator.
  This is a **fail-closed pre-order transport correction**, not proof of
  reliable broker execution or an automatic re-offer/ACK retry. It cannot
  eliminate every crash window between positive acknowledgement, journal
  clearance and broker submission; ambiguous outcomes still require real
  demo-broker reconciliation and independent review.

## 8. Error codes the EA reports

`COMMAND_EXPIRED`, `SYMBOL_NOT_FOUND`, `SPREAD_TOO_HIGH`,
`PRICE_MOVED_TOO_FAR`, `INVALID_STOP_LOSS`, `INVALID_TAKE_PROFIT`,
`LOT_SIZE_INVALID`, `MARGIN_INSUFFICIENT`, `TRADING_DISABLED`,
`ORDER_SEND_FAILED`, `DUPLICATE_COMMAND`, `DEMO_ONLY_VIOLATION`,
`WEBREQUEST_FAILED`, `JSON_PARSE_FAILED`.

## 9. Hosted Provider Edition identity

In hosted mode the EA sends the customer licence in the `X-SG-License-Key` header on command polling and callbacks. The backend resolves the customer from that licence and re-checks command ownership before execution/reconciliation reports are accepted.

The `UserID` query parameter remains only for backwards-compatible local-demo operation; it is not an authentication boundary in hosted mode.

Never put the customer licence in a URL, screenshot, issue, shared log or public evidence bundle.

## 10. Testing without MetaTrader

If you don't have MT5 installed, use the Python **EA simulator** instead — it
exercises the identical backend endpoints. See the root `README.md`.
