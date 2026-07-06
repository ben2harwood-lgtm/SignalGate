# SignalGate — Path to Live (your own money)

**Scope of this plan:** turning demo-only v1 into an EA that can trade a **live
MetaTrader 5 account that you own, with your own money, for yourself.** No other
person's money, no customers, no paid product. That keeps this an *engineering and
verification* problem with a light legal footprint.

> **The moment anyone else's money touches this** — Nick's followers, a paid seat,
> managing an account that isn't yours — it stops being a personal tool and becomes a
> regulated financial service. That's a different plan with legal counsel at the front.
> Do not let scope drift across that line without stopping. This doc assumes it never does.

## The one rule everything hangs off

**Demo-verified before live. Always. No exceptions.** You never flip demo→live as a
config change. Live is enabled only after the exact code has proven itself, unchanged,
on a demo account for a sustained period, and only behind a deliberate, guarded switch
(Phase 5). The day the guard comes off is the day mistakes cost real money — so the guard
comes off last, on purpose, with everything else already proven.

---

## Where you actually stand today (honest starting line)

I checked the code. Three different states, don't confuse them:

| Component | State | Notes |
|---|---|---|
| Deal-history stop detection (`DEAL_REASON_SL`) | **Written, unverified** | `CommandClosedByStop()` exists (fixes P0-4/5) but has never run on a terminal |
| Retcode gate on every trade op | **Written, unverified** | `ExecutionFilled()` / `RetcodeErrorCode()` in place |
| Netting-account fallback | **Written, unverified** | `g_split_mode` forced false off hedging accounts (P1-14) |
| Broker symbol resolution (suffixes) | **Written, unverified** | `ResolveBrokerSymbol()` |
| Backend transition guards / stale sweep / reset | **Written, tested (demo)** | `_EVENT_ALLOWED_FROM`, `sweep_stale_sent_commands`, reset endpoint |
| EA compiled & run on a real terminal | **Not done** | This is the #1 gate. All the "written, unverified" rows are worth nothing until this passes |
| Atomic command claim (row lock) | **Not built** | No `with_for_update`; concurrent-poll race still open (P2-5). Low risk single-EA, must-fix multi-EA |
| **Risk controls** (daily-loss halt, drawdown, kill switch, exposure caps) | **Not built at all** | Zero of this exists. This is the biggest net-new build and it *only* matters with real money |
| **Risk-based position sizing** | **Not built** | Lots are fixed inputs (`SingleTicketFixedLot` etc.), clamped to broker min/max. No sizing off balance or risk % |
| Live-account handling | **Refuses live** | `IsLiveAccount()` + `DemoOnlyMode` deliberately block real accounts. Enabling live is a careful *addition* (Phase 5), not a deletion |

So the real work is: **verify what's written → build the risk layer that doesn't exist
yet → prove it on demo → then, and only then, a gated micro-size live rollout.**

---

## Phase 0 — Decide the frame (half a day, before any code)

Cheap, and it stops expensive mistakes later.

- [ ] **Confirm your broker allows EAs / automated execution** on your account type.
      Read the account T&Cs. Most retail MT5 brokers allow it; some restrict certain
      strategies. This is the only "legal" check for a personal tool.
- [ ] **Pick the live account and ring-fence it.** A dedicated account funded with an
      amount you are genuinely willing to lose entirely. Not your main savings.
- [ ] **Write down your risk budget in numbers**, because Phase 3 codes to these:
      per-trade risk (e.g. 0.5% of balance), max daily loss (e.g. 2%), max open
      exposure, max concurrent positions. Decide them now, sober, not mid-drawdown.
- [ ] **Confirm hedging vs netting** on the account — it changes whether split-ticket or
      single-ticket mode runs (the EA already detects this, but know which you're on).
- [ ] **Accept the record-keeping is yours:** live P&L is taxable and reportable; the
      ledger helps but it's your responsibility.

**Gate to Phase 1:** broker permits automation, dedicated funded account chosen, risk
numbers written down.

---

## Phase 1 — Verify the execution engine on demo (the #1 gate)

Everything marked "written, unverified" above has to actually work on a MetaTrader
terminal. Nothing else in this plan matters until this passes.

- [ ] **Compile the EA** in MetaEditor; resolve every warning, not just errors.
      (`docs/CODEX_MT5_COMPILE_AND_TEST.md` is the paste-ready harness — if Codex is
      stuck here, this is where to unblock it, and it's the honest thing it *should* be
      helping with.)
- [ ] **Run it on a demo account** wired to your backend, and drive real cards through it.
- [ ] **Verify each safety path actually fires — observe it, don't assume:**
  - [ ] A winning trade walks OPEN → TP1 → SL→BE → TP2 → SL→TP1 → TP3 → FULLY_CLOSED,
        and the ledger matches.
  - [ ] **A stop-out is recorded as `STOP_LOSS_HIT`, not a TP win** (P0-4/5). Force it:
        set a tight stop and let price take it. This is *the* correctness test — the
        whole product is an honest record, and this is the line where it used to lie.
  - [ ] A rejected order (bad stops / market closed / no money) is reported as a failure
        with the right error code, and the ledger shows FAILED — not a phantom open.
  - [ ] Real fill price and slippage are captured from the deal, not guessed.
  - [ ] Netting fallback: on a netting demo account it runs single-ticket and the ledger
        stays correct (no phantom TP hits from merged positions).
  - [ ] Restart the terminal mid-trade → EA re-attaches to existing positions and does
        **not** double-open (needs Phase 2 file-backed state to fully pass).
  - [ ] Broker symbol suffixes resolve (e.g. `EURUSD.r`).
- [ ] **Soak it for at least 2–4 weeks of demo trading**, including a weekend (market
      closed) and a news spike, watching for divergence between EA state and broker state.

**Gate to Phase 2:** every checkbox above observed passing on demo, over weeks, unchanged.
A stop-out logged as a win here = stop, do not proceed.

---

## Phase 2 — Backend & EA integrity hardening

Real money raises the cost of every silent failure. Close the gaps that are "fine on
localhost demo" but not "fine with money on the line."

- [ ] **File-backed EA idempotency state** (survives EA/terminal restart) + a **report
      retry queue** so a failed WebRequest never silently loses a lifecycle event
      (MT5 top-5 #4/#5). Without this, a restart can double-trade or lose a stop event.
- [ ] **Reconciliation loop:** the EA periodically compares *actual broker positions*
      against what the backend believes, and alerts on any divergence. This is your
      early-warning system for "the two sides disagree about a live position."
- [ ] **Atomic command claim** (`UPDATE … WHERE status='PENDING' RETURNING`, or row lock)
      so a command can't be double-delivered (P2-5). Lower priority if you run exactly one
      EA; still worth doing.
- [ ] **TLS + real auth** *only if the backend is reachable beyond localhost.* If backend,
      terminal, and you are all on one machine/VPS behind a firewall, plain localhost HTTP
      is acceptable for a personal tool. If it crosses a network, add TLS and replace the
      header-ID/API-key auth with real tokens (`compare_digest`) first (P1-1, P2-8).
- [ ] **Stale `SENT_TO_EA` sweep** is already in the backend — confirm it's wired into the
      live poll path and tune the timeout for your poll interval.

**Gate to Phase 3:** restart-safety and reconciliation demonstrated on demo; no lost or
duplicated events across a forced restart.

---

## Phase 3 — The risk layer (the biggest net-new build)

**None of this exists yet, and it's the part that only matters because it's real money.**
Build it, and test every limit by deliberately tripping it on demo.

- [ ] **Risk-based position sizing.** Replace fixed lots with size computed from account
      balance, your per-trade risk %, and the stop distance — then clamp to broker
      min/max/step (the EA already has `NormalizeLot`). A fixed 0.01 on a live account is
      either trivially small or, on a tight stop, more risk than you think.
- [ ] **Per-trade max-risk cap.** Refuse any command whose implied risk exceeds your
      ceiling, and report it rather than trading it.
- [ ] **Daily-loss circuit breaker.** Track realised loss for the session; when it hits
      your limit, **stop opening new trades** and alert. Auto-halt, not willpower.
- [ ] **Drawdown / max-exposure caps.** Max concurrent open risk and max total exposure;
      refuse new commands past the cap.
- [ ] **A kill switch you can hit from your phone.** One action that halts new trading
      immediately (an admin flag the EA checks every poll — `admin_paused` already exists
      as the backbone; extend it to a hard "flatten/stop" you trust). Test it under load.
- [ ] **Margin pre-check** before every order (some of this is in the retcode mapping;
      make it explicit and reported).
- [ ] **Event guards:** explicit handling of weekend/market-closed, requotes, partial
      fills, and gap-through-stop (slippage past the stop) — each reported honestly, none
      silently swallowed.

**Gate to Phase 4:** every limit above provably halts/refuses on demo when tripped, and
the kill switch works from your phone within one poll interval.

---

## Phase 4 — Forward-test to a record you actually trust

You skip the *regulatory* proof requirement here (it's your own money), but you should
**not** skip the "do I actually trust this engine" proof.

- [ ] **Run the full stack on demo for 60–90 days** with the fixed rulebook, every signal
      carded, ledger exported weekly — losses included. This is already the top item on
      your 30/60/90 roadmap; it does double duty here.
- [ ] **Review the ledger honestly:** are stops labelled right, are R-values sane, does
      the record match what the terminal actually did? If the record and the terminal ever
      disagree, you are not ready — that disagreement *is* the failure mode that hurts with
      real money.
- [ ] **Only proceed if the engine's record is boringly correct** for weeks. Profitability
      is not the bar here (demo P&L predicts little); *correctness of the record* is.

**Gate to Phase 5:** weeks of ledger that reconciles exactly with terminal history, zero
mislabelled outcomes, all risk limits observed firing.

---

## Phase 5 — Controlled live enablement

The demo guard (`IsLiveAccount()` + `DemoOnlyMode`) currently refuses real accounts. You
**do not delete it.** You add a deliberate, loud, gated live path around it.

- [ ] **Design the switch as an explicit opt-in, not a default.** A new input
      (e.g. `EnableLiveTrading=false` default) that must be set *and* acknowledged. Keep
      `DemoOnlyMode` meaningful: live requires `DemoOnlyMode=false` **and**
      `EnableLiveTrading=true` **and** the account actually being the ring-fenced one.
- [ ] **Keep every other guard.** Retcode gate, stop detection, risk limits, kill switch —
      all still on. Live changes *where* orders go, nothing about the safety logic.
- [ ] **Go live at the smallest size the broker allows**, on the ring-fenced account, with
      per-trade risk near the floor. The goal of first-live is not profit — it's proving
      the *live* fill/slippage/stop behaviour matches what demo showed.
- [ ] **Watch every trade, manually, for the first stretch.** Sit with it. Confirm the
      first live stop-out is recorded correctly (live spreads/slippage differ from demo —
      this is exactly where demo-verified code can still surprise you).
- [ ] **Verify the kill switch on the live account** before you stop watching it.

**Gate to Phase 6:** a run of live trades at micro size, each reconciling with the ledger,
first live stop-out correctly recorded, kill switch confirmed live.

---

## Phase 6 — Scale-up discipline

- [ ] Increase size in **small, deliberate steps**, only after each step runs clean for a
      set period. No jumps.
- [ ] Keep the risk limits proportional as balance grows — re-derive, don't eyeball.
- [ ] Re-run the reconciliation review weekly. The record staying honest is the whole point.
- [ ] Any code change resets you to demo verification for the changed path. No hot-patching
      logic on a live EA.

---

## Ongoing (from Phase 5 onward, forever)

- **Hosting:** run the terminal + backend on a reliable VPS (24/5 uptime, auto-reconnect).
  A live EA that silently disconnects is a live position you can't see.
- **Monitoring & alerts:** trade failures, disconnects, and EA↔broker divergence should
  ping your phone, not sit in a log.
- **Incident plan:** know, in advance, exactly what you do when a live trade misbehaves —
  including the kill switch and how to flatten manually in the terminal.
- **Backups:** DB + EA state backed up; you can reconstruct the ledger.

---

## What stays out of scope (holds the line)

- **Anyone else's money.** Crossing this triggers the regulated-service path — stop and
  get legal advice first (see the fork at the top).
- **Auto-approval / removing the human tap.** The tap is a safety feature, not friction.
- **Trailing stops, new order types, channel auto-ingestion** — separate features, each
  demo-verified before it ever runs live.

---

## Realistic shape

This is **months, not a weekend** — most of it in Phases 1, 3, and 4 (verification, the
risk layer, and the soak). The code you can write quickly; the *proof* is what takes time,
and the proof is the point. The single highest-value next action is **Phase 1: compile and
verify the EA on a demo account** — it converts three "written, unverified" safety features
into real ones and tells you the true state of the engine. If Codex is stuck, that's the
task to unblock, and helping finish *that* is completely legitimate — it's demo work.

Everything here keeps the same discipline the demo has: verified before trusted, honest
record above all, and the guard removed last and deliberately — never as a shortcut.
