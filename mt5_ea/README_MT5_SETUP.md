# SignalGate EA — MetaTrader 5 Setup (DEMO ONLY)

This Expert Advisor connects MetaTrader 5 to the SignalGate backend. It polls
for approved, structured commands and places **demo trades only**.

> ⚠️ **Demo only.** The EA refuses to run on a live account. v1 has no live
> trading support by design. Use a broker **demo** account.

## 1. Install the EA

1. Open **MetaEditor** (from MT5: Tools → MetaQuotes Language Editor).
2. In the Navigator, right-click **Experts** → **Open Folder** (this is
   `.../MQL5/Experts`).
3. Copy `SignalGateEA.mq5` into that `Experts` folder.
4. Back in MetaEditor, open `SignalGateEA.mq5` and press **Compile** (F7).
   It should compile with 0 errors. A compiled `SignalGateEA.ex5` appears.

## 2. Allow the backend URL for WebRequest

The EA uses `WebRequest()` to talk to the backend. MT5 blocks this unless the
URL is whitelisted:

1. In MT5: **Tools → Options → Expert Advisors**.
2. Tick **Allow WebRequest for listed URL**.
3. Add: `http://127.0.0.1:8000` (or your `BACKEND_URL`).
4. Click OK.

## 3. Enable algo trading

- Click the **Algo Trading** toolbar button so it is green/enabled.

## 4. Attach to a chart

1. Open a **XAUUSD** chart on your **demo** account.
2. Drag **SignalGateEA** from Navigator → Experts onto the chart.
3. In the inputs dialog set at minimum:
   - `BackendURL` = `http://127.0.0.1:8000`
   - `UserID` = your SignalGate user id (e.g. `USER-000001`)
   - `EAApiKey` = the `EA_API_KEY` from your backend `.env`
   - `DemoOnlyMode` = `true` (leave as-is)
   - `SplitTicketDemoPartialMode` = `true` (default for v1)
4. Click OK. A smiley face in the top-right of the chart means it is running.

## 5. Inputs reference

| Input | Default | Meaning |
|-------|---------|---------|
| `BackendURL` | `http://127.0.0.1:8000` | SignalGate backend base URL |
| `UserID` | `USER-000001` | SignalGate user id to poll commands for |
| `LicenseKey` | `local-demo` | Optional license key (passthrough) |
| `EAApiKey` | `local-demo-ea-key` | Must match backend `EA_API_KEY` |
| `PollIntervalSeconds` | `2` | How often to poll/manage |
| `SingleTicketFixedLot` | `0.01` | Lot for single-ticket fallback mode |
| `SplitTicketDemoPartialMode` | `true` | Open 3 child tickets for 50/25/25 |
| `TP1Lot` / `TP2Lot` / `TP3Lot` | `0.02 / 0.01 / 0.01` | Child lots |
| `MagicNumber` | `440044` | EA position tag |
| `DemoOnlyMode` | `true` | Hard safety; EA won't run if false/live |
| `MaxSpreadPoints` | `500` | Reject if spread above this |
| `MaxSlippagePoints` | `100` | Deviation allowance |
| `EnableTrading` | `true` | Master on/off |
| `SymbolOverride` | `""` | Force a chart symbol name if broker differs |

## 6. How it trades (split-ticket demo partial mode)

A single 0.01 lot position **cannot** be partially closed 50/25/25 (that needs
0.005 lots, below the 0.01 lot step). So in demo we open **three child
positions** that together emulate partial profit-taking:

- TP1 child: `TP1Lot` (0.02), TP = TP1
- TP2 child: `TP2Lot` (0.01), TP = TP2
- TP3 child: `TP3Lot` (0.01), TP = TP3
- Total demo exposure: ~0.04 lots, all sharing the same initial SL.

Management:
- When the TP1 child closes → report `TP1_CLOSE_SUCCESS`, move remaining child
  SLs to **breakeven** (open price).
- When the TP2 child closes → report `TP2_CLOSE_SUCCESS`, move TP3 child SL to
  **TP1**.
- When the TP3 child closes → report `TP3_CLOSE_SUCCESS` then `FULLY_CLOSED`.
- If price hits SL on remaining tickets → `STOP_LOSS_HIT`.

Set `SplitTicketDemoPartialMode = false` to use single-ticket fallback (one
0.01 lot, full close at the final TP, no impossible partials).

## 7. Known MQL5 limitations

- **No standard JSON library.** MQL5 ships none. This EA includes a small,
  deterministic extractor (`JsonGet*`) tuned to the **exact** backend command
  shape. It is not a general JSON parser; if the backend payload shape changes,
  update those helpers. No external/unbundled libraries are required.
- **Demo/live detection** relies on `ACCOUNT_TRADE_MODE`. Most brokers report
  this correctly, but if a broker misreports it, keep `DemoOnlyMode = true`
  and only attach to a known demo account.
- TP-hit detection is inferred from child positions closing (broker-side TP),
  which is robust for the demo split-ticket design.

## 8. Error codes the EA reports

`COMMAND_EXPIRED`, `SYMBOL_NOT_FOUND`, `SPREAD_TOO_HIGH`,
`PRICE_MOVED_TOO_FAR`, `INVALID_STOP_LOSS`, `INVALID_TAKE_PROFIT`,
`LOT_SIZE_INVALID`, `MARGIN_INSUFFICIENT`, `TRADING_DISABLED`,
`ORDER_SEND_FAILED`, `DUPLICATE_COMMAND`, `DEMO_ONLY_VIOLATION`,
`WEBREQUEST_FAILED`, `JSON_PARSE_FAILED`.

## 9. Testing without MetaTrader

If you don't have MT5 installed, use the Python **EA simulator** instead — it
exercises the identical backend endpoints. See the root `README.md`.
