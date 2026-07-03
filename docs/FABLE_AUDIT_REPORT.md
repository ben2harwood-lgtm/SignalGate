# SignalGate — Fable Full Audit Report

*Prepared by an 8-expert panel + adversarial code auditor + completeness critic, with a
separate adversarial verification pass on every checkable claim. Repo audited at branch
`claude/signalgate-full-audit-bjh0tk`, commit history `91cabef` + `bf8c8b9`. Date: 2026-07-03
(Friday of the US July-4 weekend — FX/metals markets close tonight; this matters, see P0-5/P2-10).*

**Method & confidence.** The backend was booted in-process and its test suite run (50/50 pass);
`/health` returns `demo_only_mode:true`. The static demo site was served and probed live. Nine
domain reviewers produced 96 findings; the 77 that assert checkable facts (P0–P2) were each handed
to an independent skeptic instructed to *refute* them against the code. Result: **73 CONFIRMED, 4
PARTIAL, 0 REFUTED.** A completeness critic then swept for gaps and added 7 verified findings. Where
a verifier corrected a detail, the correction is folded in below (most notably: the parser is **not
gold-only** — it accepts a 3-symbol whitelist XAUUSD/BTCUSD/ETHUSD; two experts mis-stated this and
it is corrected throughout).

MQL5 could not be compiled here (no MetaTrader on Linux), the live Telegram bot could not be run (no
token), the Claude vision engine could not be exercised (no API key), and Postgres mode was not
tested (suite runs SQLite). Findings touching those four are rigorous static review and are marked
where runtime confirmation is still owed.

This report is deliberately three separate things, per the brief: **(1)** a review of what exists
(§2, §3), **(2)** an audit of risks (§4), and **(3)** an improvement plan (§5–§9). They are not merged.

---

## 1. Executive Summary

**Overall verdict: the engine is real and honest; the storefront lies about it, and the ledger — the
one asset the whole product is built to produce — can currently record a losing trade as a winner.**
SignalGate is a genuinely differentiated prototype in a category full of scams: raw Telegram text
never reaches MetaTrader, every trade opens with a hard stop, one YES creates exactly one command
(DB-enforced, survives 6 concurrent taps), and every state change is audit-logged. Fifty automated
tests pass. That honest core is the moat, and it is worth protecting above everything else. But the
work is not ready to show a prospect or a tester, for three specific reasons.

- **What is genuinely strong:** the deterministic parser boundary, one-command-per-approval
  idempotency (`models.py:78-80` unique constraint, confirmed under concurrency), expiry + admin-pause
  guards with passing tests, three independent demo-only enforcement layers (config, backend payload,
  EA `OnInit` refusal), a working Python simulator, and a marketing site that is unusually honest for
  the category (SAMPLE labels everywhere, no fake prices, no fabricated testimonials, loss-framed FAQ).

- **What is not ready:** the site makes present-tense verification claims for a record that does not
  exist; the MT5 EA infers trade outcomes from position *counts* and never emits `STOP_LOSS_HIT`, so a
  stop-out (or this weekend's closed market) is written to the ledger as a full TP3 win; a solo admin
  tester literally cannot register and taps YES into an infinite loop; and every prospect's submitted
  PII is world-readable over plain HTTP on the live demo site.

- **Biggest sales blocker:** the hero promises execution "even when you're not watching" and step 1
  claims SignalGate "reads your channel the moment it lands" — both contradicted by the product's own
  mechanics (mandatory tap, 5-minute expiry, no channel listener exists). For a brand whose entire
  pitch is honesty, the page fails its own test in the first screen.

- **Biggest trust blocker:** unqualified "independently reconciled / read-only audited record" claims
  (FAQ, nav chip, a fabricated "VL" verifier seal) for verification that does not exist — the exact
  "fake proof" pattern the page's own copy attacks — plus a sample record dated **two months into the
  future** ("Nov 2025 – Aug 2026").

- **Biggest technical blocker:** ledger integrity. The EA's count-based management (`SignalGateEA.mq5:342-396`)
  plus `CTrade::Buy` return-value-as-fill (`:266-283`) plus the backend's guard-free state machine
  (`crud.py:683-685`) mean the performance ledger — the product's core artifact — can be silently wrong.

- **Best next move:** do **not** build hosting, pricing, or more site design yet. In order: (1) fix the
  ~10 small P0 correctness/PII/registration bugs (most are S-effort, days of work); (2) rewrite the four
  false site claims to what is actually true and provable *today*; (3) **start a defined 60–90 day demo
  forward-test now**, exporting the real ledger weekly. The proof cannot be written or bought — only
  accumulated — and every week without it delays the only thing that makes the page sellable.

**Show to prospects now? No. Use with testers now? Not until the P0 registration + ledger + PII fixes
land — the simulator path is fine today. Highest-leverage next week: P0 fixes + start the forward-test.**

---

## 2. Built vs Not Built

Status legend: **Built** · **Partial** · **Not built / outside v1 scope** · **Claimed-not-substantiated** · **Needs runtime verification**

| Area | Status | Evidence | Notes |
|---|---|---|---|
| Backend API (14 spec routes) | Built | All present: `routes/health.py:16`, `users.py:14`, `signals.py:87/126/135/146`, `commands.py:86/107/120/160`, `admin.py:24/34/103`, `ea.py:16`. 50/50 tests pass. | Extras beyond spec: `POST /signals/extract`, `GET /signals/recipients`, licensing endpoints. |
| Deterministic parser + aliases | Built | `parser.py`: symbol aliases, BUY/SELL, SL/TP normalization, directional sanity + TP ordering; 12 tests incl. the 10 required. | **Not gold-only** — whitelist is XAUUSD **+ BTCUSD + ETHUSD** (`parser.py:17-26`). Rejection msg `:98` stale ("expected GOLD/XAU/XAUUSD"). No test covers BTC/ETH. |
| Approval idempotency + unique constraint | Built | `UniqueConstraint('signal_id','user_id')` `models.py:78-80`; first-decision-wins both ways; verified holding under 6 concurrent YES. | App logic + DB backstop; correct layering. |
| Signal & command expiry | Built | `crud.py:315-320`, `404-412`, `561-566`; tests pass. | Lazy (checked on access), not swept. Expiries never touch the ledger (see P1-10). |
| Admin pause | Built | `admin.py:24-41`, `crud.py:384-392`; 2 tests. | YES-during-pause permanently consumes the decision + later lies "Already approved" (P2-2). |
| EA / admin / provider auth | Built (weak, admitted) | `security.py:18-52`; tests. Docstring: "not production-grade auth." | Header-ID = password; EA key not constant-time; empty key fails **open** (P2-8). Fine on localhost, not hosted. |
| audit_logs | Built | `models.py:210-218`, `add_audit` on every lifecycle event. | DB-only; no admin/bot surface to read it. |
| Performance ledger | Built | `ledger.py` full lifecycle; 5 tests; R marked approximate. | Integrity holes: EXPIRED/BREAKEVEN unreachable; bare FULLY_CLOSED force-labelled TP3_HIT (P1-10). |
| Telegram bot (9+ commands) | Built | All registered `bot.py:33-45`; handlers in `handlers.py`. | `/users` shows count only; `/lastcommands` shows counts not commands; `/status` hardcodes "Registered: yes". **Zero tests** (P1-9). |
| Trade card + YES/NO callbacks | Built | `keyboards.py:9-20/76-117`; `on_decision` maps all 6 spec outcomes +4; broadcasts to all active testers. | README `:136-137` stale (claims admin-only broadcast; code broadcasts to all). |
| MT5 EA | Partial | 745 lines; demo guard, split-ticket, management, in-memory idempotency, JSON extraction, heartbeat all present. | No client-side expiry check; count-based management mislabels stop-outs; no retcode gate; no netting check (P0-4/5, P1-14/15/16). **Runtime unverified.** |
| Python simulator | Built | Clear "SIMULATOR ONLY" banner; polls, acks, posts full happy-path lifecycle; 2 tests. | Only plays the **win** scenario — no stop-out mode anywhere in the repo (P1-8). |
| Test suite | Built | 9 files, 50/50 pass; exceeds spec minimum. | No bot tests; no losing-trade path; no concurrency tests. |
| Docs set | Built | All 6 spec docs + 6 extras + README + install guide. | README `:41` denies AI parsing that now exists; several stale claims. |
| Windows/Mac launchers | Built | `Start Backend/Bot.bat/.command`: auto-create `.env`, venv, pip, init_db, run. | `.bat` files lack `pause` (silent failures, P1-20); Mac `.command` venv detection bug (P2-29). Bind `0.0.0.0` while docs say `127.0.0.1`. |
| Screenshot/vision extraction | Built (**exceeds spec**) | `vision_extractor.py` (Claude vision, temp 0, strict JSON) + `FakeExtractor`; `/signals/extract` is preview-only; human Confirm gates broadcast; 8 tests. | Contradicts CLAUDE.md constraint 19 ("no AI parsing") — but gating is genuinely strong. README must own it. Live engine unverified (no key). |
| Licensing / hosted mode | Built (delivery only) | `crud.py:174-242`, REQUIRE_LICENSE; 6 tests incl. deactivated-customer. | Scopes **polling** per tenant but **not** execution/management reporting — cross-tenant write possible (P1-3/7). |
| Hosted deployment | Partial (docs only) | Postgres URL normalization + `requirements-hosted.txt` exist and are honest plans. | No server exists; Postgres path never exercised. Correctly outside v1 scope. |
| Demo site (3 mockups) | Built (local) | site-1/2/3 HTML; site-2 is primary (`site_server.py:70`); form → `demo-requests.jsonl`. | No deploy, no real CRM/email — correctly outside v1. |
| "Independently reconciled / read-only verified record" | **Claimed-not-substantiated** | site-2 `:353/:506/:556/:560/:700`; nav chip site-3 `:315`; "VL" seal. No broker feed, verifier, or record exists in repo. | The one true claim-vs-reality gap. Fix = generate a real pack from `performance_ledger`, or reword to future tense. |
| Automatic channel ingestion | **Not built / claimed** | site `:409` "reads it the moment it lands"; `bot.py:33-57` has no `channel_post` handler. | Legitimate roadmap item; must not be claimed as present. |
| Live trading / auto-copy / payments / dashboard / trailing stops / real pricing / operator identity | Not built / outside v1 scope | Correctly absent; demo-only enforced in 3 layers. | Keep out. Live remains a separate, legal-reviewed future decision. |
| `direction-*.html` drafts | Built (leftovers) | 6 tracked HTML files; only `site_server.py:70` names site-2 as canonical. | Archive/delete before sharing the repo. |

---

## 3. Expert Findings

Each expert's blunt verdict, top findings, and where their full rewrites/artifacts live (§5–§8).

### Expert 1 — Product Strategist
**Verdict:** A genuinely differentiated wedge (execution discipline + auditable ledger for signal
followers, in a category drowning in scams), and the engineering honesty is a real asset — but the
site's two headline claims are contradicted by the actual mechanism, and the centerpiece proof has no
plan to be generated. *The product is closer to sellable than the messaging is to honest — exactly
backwards for a brand whose whole pitch is honesty.*
**Top findings:** hero "not watching" contradiction (P0-8); step-1 channel ingestion not built (P0-9);
whitelist-vs-"any signal" gap (P1-23); no forward-test plan for the record (P1-25); two ICPs conflated
— the built product points at **providers**, the site sells to **followers** (P1-26).
**Fix direction:** reframe hero to the discipline promise; make the signal *provider* the primary pilot
customer (B2B2C); start the forward-test now. Positioning + pilot spec in §5.

### Expert 2 — Offer Architect
**Verdict:** The honest core is differentiated, but the site sells a different product than the repo
contains, and the pricing section has plan cards but **no offer** — nothing a buyer would pay for is
defined, and the one real prospective partner (Nick) is handed a task list with zero stated benefit.
**Top findings:** FAQ "independently reconciled" as fact (P0-6); undefined offer ladder + live tease +
"Cancel anytime" with nothing to cancel (P2-22); no provider offer for Nick (P2-23); undisclosed
MT5-always-on VPS cost (P2-26).
**Fix direction:** a real 4-rung ladder valued on hosting + concierge + reporting; a provider desk whose
product is a forward-test record of the provider's own signals. Full ladder in §5.

### Expert 3 — Conversion Copywriter
**Verdict:** Structurally strong (the risk language beats the category norm, the anti-scam framing is
the right wedge) but it leaks credibility in exactly the places a scam-wary trader checks: present-tense
verification claims nothing substantiates, a hero promise its own FAQ contradicts, a channel-ingestion
claim the bot can't fulfil, and a CTA funnel with no contact channel anywhere.
**Top findings:** unqualified verification copy (P0-3); away-from-screen hero (P1-11); "reads it the
moment it lands" (P1-12); dead-end funnel, no contact route (P1-13); future-dated record (P2-12);
orphaned "VL" seal (P2-15).
**Fix direction:** full rewrites of hero, CTA, pricing, proof, FAQ, and risk microcopy — all in §6.

### Expert 4 — UX/CRO Lead
**Verdict:** Unusually honest and well-crafted for a mockup, but as a conversion machine it has one
structural trap and one credibility trap. Structural: the form only delivers leads on the bundled
localhost server — hosted anywhere real, every lead dies silently in the visitor's own `localStorage`
behind a success-styled panel. Credibility: it asserts a verified record that doesn't exist, dated into
the future, and **never once shows the actual product** (zero images, no trade-card visual).
**Top findings:** silent lead loss (P0-11); show the product (P1-33); verification tense (P1-31);
future-dated record (P1-32); mobile nav vanishes ≤860px (P2-41); no OG/meta/favicon (P2-43).
**Fix direction:** top-10 fixes, above-the-fold diagnosis, submit-path trace, and analytics events in §7.

### Expert 5 — Backend Safety Engineer
**Verdict:** The happy-path rails are real (demo-only propagates end-to-end, idempotency is
DB-backed, expiry + pause enforced, the vision extractor genuinely re-parses everything). But the
backend **trusts everything that reaches it**: approve/reject have zero auth, the EA reporting surface
has no state machine or ownership check, and the parser silently mis-reads comma-grouped numbers into
absurd stops and marks them VALID. *Safe on 127.0.0.1 today; not safe on the planned VPS or in front of
testers without the P0/P1 fixes.*
**Top findings:** parser number handling (P0-1); unauthenticated approve/reject (P1-1); guard-free EA
reporting (P1-2); shared-key cross-tenant writes (P1-3); stuck SENT_TO_EA (P2-1).
**Fix direction:** PASS/FAIL control table + 12 named tests to add — reproduced in §8.

### Expert 6 — Trading Systems / MT5 Engineer
**Verdict (readiness 4/10):** An honest, well-commented skeleton with the right safety bones
(live-account refusal, hard SL on every order, structured-input-only), but its trade-management layer
is not trustworthy: it infers TP hits from position counts, never emits `STOP_LOSS_HIT`, and treats
`CTrade::Buy`'s bool as a fill — so a stop-out or a market-closed rejection gets written to the ledger
as TP1/TP2/TP3 wins. *This directly violates the project's own "do not fake profitability" rule.*
**Top findings:** stop-outs recorded as wins (P0-4); rejections reported as success (P0-5); netting
accounts break split-ticket (P1-14); restart orphans trades / stuck commands (P1-15); LIMIT executed as
market (P1-16).
**Fix direction:** deal-history close detection, retcode gates, hedging check, file-backed state, ticket
tracking — failure-mode table and top-5 in §8.

### Expert 7 — Trust, Risk & Compliance
**Verdict:** The most honestly-written copy in the signals category (loss-framed FAQ, SAMPLE markers, no
testimonials, no profit promises) — but it commits the exact sin it accuses competitors of in three
places, and the project's own `SAFETY_RULES.md` now misstates the system ("No AI parsing") after a
Claude vision extractor was wired in. *For a product whose pitch is "every claim checkable," a safety
rulebook contradicted by its own code is the most corrosive defect.*
**Top findings:** unqualified verification claims (P0-10); AI-parsing doc contradiction (P1-29); no
privacy notice on a form collecting PII (P1-30); regulatory placeholder dropped from the served page
(P2-36); anonymous "real person stands behind these calls" (P2-37).
**Fix direction:** claims-to-remove list with replacement language, draft disclaimers, ranked trust
assets, and compliance red flags (verified-in-copy vs unverified-jurisdictional) in §6/§7.

### Expert 8 — Onboarding & Operations
**Verdict:** The docs are unusually good for a prototype, but the happy path is broken at its center: a
solo admin who follows READ ME FIRST exactly **can never register**, so tapping YES dead-ends in an
unescapable "Send /start first" loop. Around it sit silent-failure traps (Windows windows that vanish on
error, /start reporting success while the backend is down, EA UserID guesswork).
**Top findings:** admin can't register (P0-7); invisible Windows failures (P1-20); /start lies when
backend down (P1-21); UserID never shown (P1-22); two divergent onboarding paths (P2-28).
**Fix direction:** onboarding map with per-step failure probabilities, better checklist, 3 copy-paste
support scripts, and an automation order in §8. Realistic time-to-first-card: 35–55 min; first MT5 trade:
90+ min Windows, 2–4 h Mac/Parallels.

### Expert 9 — Adversarial Code Auditor
**Verdict:** The invariants that were *explicitly designed* hold up under attack (the unique constraint
survives 6 concurrent YES, expiry/pause/parser gates fire before command creation, demo-only defaults are
pervasive). But the surrounding machinery is soft: the live site leaks every prospect's PII via a plain
GET (confirmed), the parser accepts `2e3`/`2,343`/`0`/`-5` as VALID stops (confirmed), the command state
machine has no transition guards so terminal trades reopen and never-executed commands jump to
FULLY_CLOSED (confirmed), and hosted-mode reporting allows cross-customer ledger tampering.
**Top findings:** world-readable PII (P0-2); parser domain checks (P0-1/P1-4); guard-free state machine
(P1-5); unauthenticated approve (P1-6); shared-key ownership gap (P1-7); double-delivery under concurrent
polls (P2-5).
**Fix direction:** 10-item quick-win hardening list + command-status state machine with holes marked, in §8.

---

## 4. Severity-Ranked Audit Findings

**Distribution:** 11 × P0 · 33 × P1 · 44 × P2 · 15 × P3. Verification on P0–P2 verifiable claims:
**73 CONFIRMED, 4 PARTIAL, 0 REFUTED.** Every finding below carries file:line or a run command as
evidence; PARTIAL entries note the verifier's correction.

### P0 — Must fix before showing any prospect or tester

| # | Area | Finding & evidence | Why it matters | Fix | Owner · Effort · Impact |
|---|---|---|---|---|---|
| P0-1 | Parser | Comma/scientific/negative/zero stops pass as VALID. Probe: `parse_signal("XAUUSD BUY SL 2,343 TP1 2353")` → `SL=2.0 VALID`; `"SL 2e3"`→2.0; `"SL -2343"`→VALID. `parser.py:53` `_NUM` regex, no domain check. | The parser is the single boundary between free text and MetaTrader. A gold BUY with SL=2 instead of 2343 is the exact mis-parse the product promises to prevent. | Reject tokens with `e`/`,`; require price>0; add plausibility check (`|SL−TP1| > 20%` of TP1 → reject). Add 4 probe tests. | Backend · S · High |
| P0-2 | Site / PII | `site_server.py:20` serves the whole dir; POST appends to `demo-requests.jsonl` **inside it**. Live: `curl .../demo-requests.jsonl` → 200 dumping prior emails. | Any prospect who submits the form can download every other prospect's contact details. Live data breach on the page shown this weekend. | Write jsonl outside web root; 404 any `.jsonl`/non-allowlisted GET; validate email. | Backend · S · High |
| P0-3 | Proof copy | Unqualified verification as fact: FAQ `:700` "the full record… is independently reconciled"; `:556` "read-only feed — we can't delete the bad trades"; `:496` "Read-only, audited record" ✓. Modal itself admits it's "a demo verification pack rather than a public third-party report" `:765`. | This is the "fake verification" pattern the page's own contrast table condemns. A skeptic who clicks the modal reclassifies the operator as the thing the page claims not to be. | Future/conditional tense until a real read-only record exists. Delete "is independently reconciled." Rewrite in §6. | Copy · S · High |
| P0-4 | MT5 / ledger | Stop-outs recorded as wins. `SignalGateEA.mq5:342-396` infers TP hits from open-child **count**, no price/deal-reason check; `STOP_LOSS_HIT` appears **nowhere** in 745 lines (grep=0), though README `:80` claims it. `ledger.py:141-147` maps TP*_CLOSE→positive-R wins. | A losing trade is booked as a full TP3 winner. Violates CLAUDE.md "Do not fake profitability." Fastest way to destroy credibility with the first tester. | Read `DEAL_REASON` (SL vs TP) from `HistoryDealSelect`; emit `STOP_LOSS_HIT` on SL close; track children by position ticket, not counts. | MT5 · M · High |
| P0-5 | MT5 / execution | `trade.Buy()` bool treated as fill (`:266-283`,`:315-336`); `ResultRetcode()` never compared to `TRADE_RETCODE_DONE` on success path. On a rejected/closed-market order, EA reports SUCCESS, ticket 0, price 0 → count=0 → fake full lifecycle. **This weekend's closed market triggers exactly this.** | The most likely weekend first-run produces a fabricated successful trade in the ledger + a false "Demo trade OPENED" Telegram message. | Require `ResultRetcode()==TRADE_RETCODE_DONE` (handle `DONE_PARTIAL`); map `MARKET_CLOSED`(10018) to a distinct error. | MT5 · S · High |
| P0-6 | Site claims | Same as P0-3 from the offer lens: FAQ `:700` asserts independent reconciliation while the record carries a SAMPLE banner. | One skeptical prospect collapses the entire trust architecture. | Reword to "logged in an audit ledger you can inspect; independent reconciliation is planned." | Offer/Copy · S · High |
| P0-7 | Onboarding | Solo admin can never register. `handlers.py:76` branches on `is_signal_provider(id)` (TRUE for all admins, `config.py:33-39`); provider branch never calls `/register_user`. Probe: approve with admin id → `USER_NOT_FOUND`. Tapping YES → "Send /start first" forever. | Kills the exact demo in READ ME FIRST/DEMO_SCRIPT for the most common setup (one person = admin + tester). Also breaks Nick. | In `start()`, always call `/register_user` (idempotent), then layer the role greeting; include the returned `USER-xxxxxx` id. | Bot · S · High |
| P0-8 | Positioning | Hero `:344` "executed properly — even when you're not watching" vs mandatory tap + 5-min expiry (`:468`,`:720` "a missed card is simply no trade"). While you're asleep/driving, the product does nothing — by design. | Buyer finds the contradiction inside the same page → reads as bait-and-switch. Fatal for an honesty brand. | Reframe hero to the discipline promise the copy deck already has. Sell "missed card = no trade" as a guardrail. **Do not** solve with auto-copy. | Copy · S · High |
| P0-9 | Site claims | Step 1 `:409` "SignalGate reads it the moment it lands" — no channel listener exists (`bot.py:51-57` = commands + provider uploads only). | "Claimed but not substantiated" on the most load-bearing section. First prospect asking "how do I connect my channel?" exposes it. | Rewrite: "Your provider sends the signal (text or screenshot); SignalGate structures it and cards it to you." | Copy · S · High |
| P0-10 | Compliance | All 3 sites assert independent verification as present fact in unmarked places (FAQ `:700`, nav chip site-3 `:315` "INDEPENDENTLY AUDITED", seal "Verifier Labs · SG-VL-2026-08"). No verifier/feed/record exists. | The page's whole differentiation is "we don't do fake proof." A fabricated verification seal *is* that. | Future-tense the FAQ; delete the nav chip; keep the seal only as an explicitly-labelled design placeholder, never before a prospect. | Compliance · S · High |
| P0-11 | Lead capture | Form POSTs to relative `/api/demo-requests`, which exists only on `site_server.py` (127.0.0.1:8088). On any real host, `saveRequest()` returns false but the green success panel + reference still render (`:811-824`,`:921-927`). | The moment the URL is sent to a real prospect, 100% of leads are dropped with no error and no operator notification. | Wire to a real endpoint (FastAPI/Formspree/email); render a visibly distinct error state on POST failure. | UX · S · High |

### P1 — Must fix before pilot users

*Backend / auth / integrity (all CONFIRMED unless noted):*
- **P1-1 / P1-6** — `POST /signals/{id}/approve` & `/reject` have **no auth** and trust `telegram_user_id` from the body (`routes/signals.py:135-154`). Probe: approve with no headers → 200 APPROVED. On the planned VPS, one curl forges any tester's YES. → Require a shared bot-secret header (`compare_digest`). *(S)*
- **P1-2** — EA reporting has **no state machine** (`crud.py:596-698`): execution accepted on a never-sent (PENDING) command; duplicate executions accepted; `OPENED` after `FULLY_CLOSED` resurrects the command. All three reproduced via TestClient. → Allowed-transition guards + idempotent execution. *(M)*
- **P1-3 / P1-7** — Single shared `EA_API_KEY`; execution/management endpoints never check command ownership (`commands.py:120-178`). Probe: post to USER-000002's command with the shared key → 200. Hosted = cross-tenant ledger tampering. → Resolve EA user, 403 unless `command.user_id` matches. *(M)*
- **P1-4** — Parser domain gap, code-auditor's angle on P0-1 (`parser.py:53`): `2e3`/`0`/`-5`/`2,343` all VALID. *(S)*
- **P1-5** — `record_management_event` applies `_EVENT_TO_COMMAND_STATUS` unconditionally (`crud.py:683-685`): terminal states reopen; PENDING jumps to FULLY_CLOSED. → Legal-transition table; audit `ILLEGAL_TRANSITION`, don't mutate. *(M)*
- **P1-8** — **The losing-trade path has zero coverage anywhere.** No test and no simulator mode exercises `STOP_LOSS_HIT`/`STOPPED_OUT`/`FAILED_MANAGEMENT` (grep=0 in tests/ and simulator/). The product sells "losses included" but the loss code has never run. → Add a `--scenario stop-out` simulator mode + pytest asserting `STOPPED_OUT`, `r_result == -1.0`. *(S)*
- **P1-9** — 532-line `handlers.py` has **zero tests** and already drifts: `/status` hardcodes "Registered: yes" (`:104`) regardless of backend truth; `/users` shows count only; `/lastcommands` shows counts. → Make `/status` query the backend + show the USER id; add pytest-asyncio bot tests. *(M)*
- **P1-10** — Ledger integrity: `EXPIRED`/`BREAKEVEN` statuses never written; expiries never call the ledger; any `FULLY_CLOSED` without a prior TP event is **force-labelled TP3_HIT** (`ledger.py:183-188`). Systematically flatters results. → `on_expired()`; map bare close to neutral; set BREAKEVEN when SL-hit follows breakeven move. *(M)*

*MT5 (all CONFIRMED, static review):*
- **P1-14** — Netting accounts break split-ticket: `ACCOUNT_MARGIN_MODE` never read (grep=0); 3 same-direction children merge into one 0.04 position → instant false TP1 + invalid BE move. → Force single-ticket fallback on netting; document hedging requirement. *(S)*
- **P1-15** — All EA state in-memory (`:46-62`): restart orphans open trades (no re-adoption) and strands commands in `SENT_TO_EA` with **no admin reset endpoint** (grep=0). → File-backed state + `POST /admin/commands/{id}/reset`. *(M)*
- **P1-16** — LIMIT commands executed as market. Parser emits `entry_type=LIMIT`/`entry_price` (verified), EA never reads them (grep=0), always `trade.Buy` at market. Silent divergence from the approved card. → Reject LIMIT in EA (`UNSUPPORTED_ENTRY_TYPE`) or implement pending orders. *(S)*

*Site / offer / trust:*
- **P1-11 / P1-18 / P1-27(PARTIAL)** — Hero sells away-from-screen execution the 5-min-expiry model refuses. *Verifier correction:* the expiry **is** disclosed mid-page (Guardrail 05 `:468`, already using the right "Late is no trade" framing) and the hero chip `:343` says "you approve every trade" — so this is "hero framing contradicts a mechanism disclosed twice below," arguably P2. Fix stands for the hero/problem sections. *(S)*
- **P1-12 / P1-17 / P1-28** — "Reads it the moment it lands" channel-ingestion claim, not built (multiple experts). *(S)*
- **P1-13** — CTA funnel dead-ends: no mailto/Telegram/contact anywhere (grep). → Add one real contact line to success panel, aside, footer. *(S)*
- **P1-19** — Free plan lists "the verified record" as an inclusion + "read-only feed" objection line; neither exists. → Swap for "full audit ledger of your own demo trades, exportable." *(S)*
- **P1-23 (PARTIAL)** — Whitelist-vs-"any signal" gap. *Verifier correction:* not gold-only — BTC/ETH also parse VALID; FX/indices reject. Disclosure should say "XAUUSD/BTCUSD/ETHUSD in v1," and `parser.py:98`'s stale message should be fixed. *(S)*
- **P1-24 / P1-29** — README `:41` + `SAFETY_RULES.md:26` deny AI parsing while `vision_extractor.py` ships a Claude engine. → Amend to describe the gate (AI transcribes; deterministic parser is sole authority; human confirms). *(S)*
- **P1-25** — The centerpiece proof has **no generation plan** in any strategy doc, though the product *is* the record-generating machine. → Start a 60–90 day forward-test now; top priority ahead of hosting/pricing. *(M)*
- **P1-26 (judgment)** — Two ICPs conflated: built product is provider-led, site sells to followers. Provider-led is also the better GTM (one provider brings N followers). → Make the provider the primary pilot customer. *(M)*
- **P1-20 / P1-21 / P1-22** — Onboarding: `.bat` launchers lack `pause` (silent failures); `/start` says "registered" even when backend down; UserID never shown to tester (wrong guess → EA polls forever silently). → `pause` + python/​.env guards; check register response; surface the USER id. *(all S)*
- **P1-30** — Form collects name/email/Telegram with no privacy notice, controller, or contact; consent covers trading risk only. GDPR duties apply on first real submission. → Two-sentence privacy note + footer link. *(S)*
- **P1-31 / P1-32 / P1-33** — Verification tense (`:353/:506/:560`); record dated into the **future** ("Nov 2025 – Aug 2026", today is 2026-07-03); product never shown (zero `<img>`, no trade-card visual). → Reword; shift sample window into the past; add an HTML trade-card mock + audit-log strip. *(S/S/M)*

### P2 — Important for conversion, trust, reliability (44 findings, grouped)

- **Backend reliability:** stuck `SENT_TO_EA` with no reset/timeout (P2-1, P2-6); YES-during-pause consumes the decision + later lies "Already approved" (P2-2); `COUNT(*)+1` PK generation + check-then-insert → concurrent 500s / Postgres collisions (P2-3, P2-7); concurrent EA polls hand the same command to multiple EAs — no row lock (P2-5, 4 threads all got CMD-000002); header-ID auth + non-constant-time key compare (P2-4, *PARTIAL: probe used a non-configured id; correct demo is the configured admin id → 200 with no other credential*); **empty `EA_API_KEY` fails open** — every EA endpoint accepts no key (P2-8, live-probed).
- **MT5 robustness:** child tracking via broker-mutable comments + deal-ticket confusion (P2-16); no stops-level check, one-shot BE-move failure leaves full risk (P2-17); README lists error codes the EA never emits + slippage hardcoded 0 + wrong reported lot on partial signals (P2-18); EA stops polling while managing → second signal expires unserved, user never told (P2-19); broker symbol suffixes (XAUUSD.a) fail with no documented diagnosis (P2-20); fire-and-forget reports — a failed WebRequest loses the event permanently (P2-21).
- **Offer / copy:** no offer ladder + live tease + "Cancel anytime" (P2-22); no provider benefit for Nick (P2-23); README AI contradiction (P2-24); "20 min" setup vs 45-min guide (P2-25, P2-39); undisclosed VPS cost (P2-26); whitelist scope undisclosed (P2-27, *PARTIAL — BTC/ETH corrected in*); future-dated record (P2-12); anonymous "real person" (P2-13, P2-37); pay-language with no payments (P2-14); orphaned "VL" seal (P2-15).
- **UX / CRO:** client/server validation disagree, server accepts junk incl. `<script>` (P2-40, stored-XSS seed for a future admin view); mobile nav vanishes ≤860px (P2-41); no in-flight submit state → duplicate leads + colliding references (P2-42); no OG/meta/favicon → blank Telegram unfurl (P2-43); hero leads with a sample equity curve, not the product (P2-44, judgment).
- **Product / retention:** tester's own record has no user-facing surface (P2-32, `/myrecord` would fix); problem copy sells position-sizing v1 lacks (P2-33); undefined pilot behind "Request Pilot" (P2-34); 5-min expiry may starve the usage loop — measure, don't guess (P2-35, judgment).
- **Docs / ops:** stale/self-contradictory `CODEX_HANDOFF.md`/`AGENTS.md` (P2-9, *misled two of this panel's own experts about parser scope*); weekend/market-closed guidance absent from DEMO_SCRIPT + MT5 README, and EA default `MaxSpreadPoints=500` blocks the BTCUSD workaround (P2-10); site server publicly serves internal strategy docs + drafts + its own source, and depends on Google Fonts (P2-11); two divergent onboarding paths (P2-28); Mac launcher venv-detection bug pip-installs to system Python (P2-29); screenshot extraction DOA with shipped `.env` defaults, main guide never mentions `ANTHROPIC_API_KEY` (P2-30); Mac+Parallels highest-abandonment segment (P2-31, judgment); regulatory placeholder dropped from the served page (P2-36); "Demo-only until you say otherwise" implies a live switch v1 refuses (P2-38).

### P3 — Polish (15 findings, summary)
Guardrail 06 "Pause anything, instantly" implies user-level pause (admin-only); no post-submit follow-up promise; zero funnel instrumentation; license keys travel as GET query params (logged); Telegram notifications sent synchronously inside EA handlers (stalls poll loop); `-1.0R` recorded even when SL was moved to breakeven/TP1; small doc contradictions (Python 3.9 vs 3.10); launchers bind `0.0.0.0` with `--reload` + default shared key (fine for a home LAN, state it); site-1 "LIVE PIPELINE" + invented "t+1.2s" latency; committed `.audit/panel-partial-results.json` working data. Two P3s are *positive confirmations* recorded for the panel: the **vision extractor safety claim is VERIFIED** (preview-only, always re-parsed, human-confirmed), and the **MT5 demo-guard + JSON extractor + simulator parity are sound**.

---

## 5. Offer Improvement Plan

**How to make the offer more valuable:** stop selling signals or coverage; sell **hosting + concierge
onboarding + an auditable execution record**. The buyer never pays for a signal or an expected profit —
they pay to have their own approved trades executed by the rulebook and logged in a record they (and, for
providers, their followers) can check.

**The offer ladder (named tiers):**

| Tier | Name | Price | Who | Core deliverable |
|---|---|---|---|---|
| 0 | **Watch It Work** | Free, 15-min session | Any curious prospect | Operator-hosted live walkthrough: a real signal becomes a card, they tap Approve on their own phone, watch the demo execution + ledger fill in real time. Needs only Telegram. *(Works today — it's how Nick onboards.)* |
| 1 | **Demo Desk** | Free, 14 days | Signal-followers ready to test | A seat on operator-hosted infra + their own MT5 **demo** via the EA. Ends with a personal **Discipline Report**: exported ledger of every card, tap, fill, TP/SL move. |
| 2 | **Pilot Seat** | Paid, invite-only *(price set only after §5 trust assets exist)* | Demo Desk graduates | Hosted seat + license key, concierge MT5-demo + optional VPS setup (~$10/mo third-party, disclosed), weekly 20-min ledger review, priority support, pause-anytime. Still demo-only. |
| 3 | **Provider Desk** | Private setup fee or rev-share (later) | Signal providers (Nick) | Screenshot-gatekeeper ingestion, multi-tester cards, and a **timestamped forward-test ledger of the provider's own signals**, exportable — the honest performance proof no screenshot-poster has. |

- **Free demo should include:** the full pipeline on a demo account (live cards, one-tap approvals, staged
  TPs, hard stop) **and the audit ledger of the tester's own demo trades** — not "the verified record"
  (which doesn't exist). The live audit trail filling in is the spectacle; no category competitor shows it.
- **Paid pilot should include:** hosted backend + shared bot (no Python/BotFather/terminals), a personal
  license key, guided MT5-demo + VPS setup, the weekly ledger review, a direct line, and "leave anytime,
  keep your export." Explicitly excluded in writing: live trading, auto-copy, profit expectations.
- **Signal-provider offer (Nick) — lead with what he gets, not his task list:** (1) gatekeeper control —
  nothing reaches testers unless he confirms every number; (2) an independent, timestamped forward-test
  record of his signals' *execution* — an asset no competitor has; (3) reputation protection — followers
  stop executing his calls badly and blaming him; (4) zero admin burden (~2 min/signal).
- **Proof required before charging a cent:** a real forward-test record (1–3 months of actual demo trades
  from the ledger, losses included, replacing every SAMPLE figure); a genuine read-only verification path
  (MT5 investor password) *or* the "read-only" copy is deleted; a named operator + contact + honest
  regulatory line; hosted deployment live with 2–3 testers onboarded end-to-end; one hour of
  financial-promotions counsel; working request fulfillment (form → real inbox); written cancel/refund terms.
- **Remove from the offer (weakens it):** "…is independently reconciled" (`:700`); "read-only feed"
  (`:556`); "the verified record" as a demo inclusion (`:587`); "even when you're not watching" (`:344`);
  "reads it the moment it lands" (`:409`); "about 20 minutes" (`:717`); "before any live discussion"
  (`:593`); "Cancel anytime" (`:603`); **the sample equity curve in the hero** (`:358-382`) — a made-up
  performance chart as the opening image is the category's #1 scam pattern, even labelled SAMPLE.
- **Most sellable first package:** **"Watch It Work" → "Demo Desk"**, run for *one provider (Nick) + 3–5 of
  his real followers*, 8 weeks, with a single goal: **produce the first real demo execution record.** Free,
  but *defined* — who, duration, what they get, what you measure, exit criteria. Free is fine; undefined is not.

---

## 6. Copy Improvement Plan

Governing rule: **sell discipline and auditability, never coverage or returns.** Full rewrites below;
all quotes are verbatim from `site-2-editorial-transparency.html`.

**Hero — before** (`:344-345`): *"The signals you follow, executed properly — even when you're not
watching."* → **after:**
> **Chip:** Demo-only v1 · You approve every trade · No live money anywhere in the system
> **H1:** The signals you follow, executed by a fixed rulebook — *hard stop in, every step logged.*
> **Subhead:** SignalGate turns a signal into a structured trade card in your Telegram. Tap **Approve**
> and it executes on a MetaTrader 5 **demo** account with a hard stop and staged take-profits, then logs
> every fill, stop move, and close. Tap **Ignore** and nothing happens. Raw signal text never touches
> your broker — only checked, approved commands do.

**Primary + secondary CTA — before** (`:346-350`) "Start on a demo account / Nothing at risk" → **after:**
Primary **"Request a demo setup"**, secondary **"See the four steps →"**, microcopy: *"Demo account only.
No card, no payment exists in v1. You'll hear back from a real person on Telegram or email — or message
**@[HANDLE]** directly."* (Fixes the page's worst funnel leak: there is no contact channel anywhere today.)

**Pricing/offer — before** (`:582-603`) "Pay only when it's earned your trust / Cancel anytime" → **after:**
"Everything is free while SignalGate is in demo. Here's what access looks like." Then Demo (Free — full
pipeline + audit log of *your own* demo trades), Pilot (By invite — guided one-to-one setup), Signal desk
(For providers — your calls in, testers get cards, you get the command log + ledger). Reassurance: *"There
is no paid plan yet and no checkout on this site. When pricing exists it will be printed here plainly."*

**Proof/verification — before** (`:506/:556/:560/:700`) → **after** (the honest, stronger version):
> **What we can prove today — and what we can't yet.** We can show you, live: a signal becoming a card,
> your tap becoming exactly one command, a demo execution with the stop attached, the take-profit stages
> firing, and every step written to an audit log you can read. **We cannot yet show you a track record.**
> SignalGate is in forward-testing on demo accounts; no performance figures exist, so we publish none. The
> chart below is an *illustration of what the published record will look like* — including the drawdown and
> the losing months — not data. When the forward test produces a record, it publishes here with the account
> identifier, the date range, every losing trade, and a read-only way to check it that doesn't depend on our
> word. Until then, anything on this page that sounds like a track record isn't one.

Also: delete the "VL" seal; retitle the chart "Illustration — not a record. Sample data only"; **shift the
sample window fully into the past** (current "Nov 2025 – Aug 2026" includes future months); change the
contrast-table row "Read-only, audited record" → "Full audit log of every action — record published when
it's real."

**FAQ (rewritten highlights):** *"What happens while I'm asleep? Honestly: nothing. Cards wait 5 minutes,
then expire. A missed card is no trade — on purpose."* · *"Can I lose money? Yes. Most retail traders lose
money; a tool doesn't change that. v1 is demo-only."* · *"Is a robot trading for me? No — nothing opens
without your tap, everything opens with a stop, and the same approval can never fire twice."* · *"Where do
signals come from? Your provider sends them to the bot — typed or as a screenshot the system reads and shows
back for confirmation. It does not auto-monitor channels; that's roadmap, not this page."* · *"Why did one
tap open three positions? Demo split-ticket mode: 0.02 + 0.01 + 0.01 lots so profits stage 50/25/25 — a
single 0.01 lot can't be partially closed."*

**Risk microcopy (persistent band):** *"Trading carries risk of loss, and most retail traders lose money.
SignalGate v1 runs on demo accounts only and is execution tooling, not financial advice — you approve every
trade yourself. No performance figures are published because none exist yet; illustrations on this page are
labelled sample data. Where leverage applies on live accounts, losses can exceed deposits."*

**Required disclaimers to draft in (compliance):** demo/hypothetical-performance disclaimer (to accompany
the record once real); no-advice/no-recommendation; signal-source independence; approval-window caveat near
the hero; a form privacy notice naming the data controller. *Jurisdiction analysis is an unverified
assumption — get one hour of financial-promotions counsel before any paid tier or live language ships. A
demo-only, no-fee pilot is the safest posture; keep it.*

---

## 7. Site & Funnel Improvement Plan

- **Above the fold:** replace the "Verified equity" sample chart with an HTML mock of the **real Telegram
  trade card** (format exists in `keyboards.py`) + a 3-line audit-log strip (`OPENED → TP1_CLOSE_SUCCESS →
  SL_MOVE_BREAKEVEN_SUCCESS`). Reorder the three trust anchors to lead with the *true* claims (hard stop →
  you approve → record-when-real), not "independently reconciled."
- **CTA:** keep the clean 7-CTA → `#demo-request` pattern; rename "Start on a demo account" → "Request demo
  access" (it prepares a request, it doesn't start now); add `scroll-margin-top` under the sticky nav; demote
  "Copy latest request" into the success panel.
- **Form:** wire POST to a real endpoint with a true error state on failure (P0-11); disable the button
  during fetch; mint the reference server-side (or add a random suffix) to stop collisions; whitelist keys,
  validate email/plan, drop unknown fields, cap lengths (P2-40).
- **Trust/proof:** the §6 verification rewrite; delete the seal; fix the future date; add the trade-card
  visual; add a privacy note + footer contact.
- **Mobile:** add a hamburger at ≤860px (all nav links currently vanish); check `.perf-stats` wrap at 360px;
  add `env(safe-area-inset-bottom)` to the toast; self-host the two fonts (P2-11) so the page doesn't fall
  back offline and doesn't leak visitor IPs to Google.
- **Analytics to add:** `page_view` (with variant id — the point of having 3 files), `cta_click{source}`,
  `section_view` (IntersectionObserver on how/safety/record/pricing/faq), `proof_modal_open`, `form_start`,
  `form_validation_error{field}`, `form_submit_ok`, `form_submit_failed` (production P0-11 detector). Cookieless.
- **After submission:** state *who* responds and *roughly when*, on the success panel and in "What happens
  next"; deliver the lead to a real inbox.
- **Still a mockup (keep out of scope, but be honest on the page):** real pricing, checkout, CRM/email
  follow-up, customer dashboard, third-party performance feed. Also: move `direction-*.html` drafts and the
  internal `.md` strategy docs out of the served directory before sharing (P2-11).

---

## 8. Code & Product Improvement Plan

Sequenced by gate. Each item cites its finding.

**Before showing prospects (P0s — days of work, mostly S-effort):**
- Parser domain checks + tests (P0-1/P1-4). · Move `demo-requests.jsonl` out of web root + block `.jsonl`
  GET (P0-2). · Always-register in `start()` + return the USER id (P0-7). · EA: retcode gate on every trade
  op + `STOP_LOSS_HIT` via deal-reason (P0-4/P0-5) — protects ledger integrity. · Site copy: the four false
  claims → true tense (P0-3/6/8/9/10). · Wire the form to a real endpoint with an honest error state (P0-11).

**Before pilot testers (P1s):**
- Backend: bot-secret auth on approve/reject (P1-1/6); transition guards + idempotent execution reporting
  (P1-2/5); per-tenant scoping of EA writes (P1-3/7); ledger `on_expired()` + stop force-labelling bare
  closes as TP3 (P1-10). · Tests: add the 12 named in the safety table below, especially the **losing-trade
  path** (P1-8) and the first **bot tests** (P1-9). · MT5: hedging-mode check + single-ticket fallback
  (P1-14); file-backed state + `/admin/commands/{id}/reset` (P1-15); reject LIMIT (P1-16). · Onboarding:
  `pause` + guards in launchers (P1-20); check `/register` response (P1-21); surface the USER id (P1-22).
  · Site: privacy note (P1-30); show the product + fix the future date (P1-31/32/33). · Docs: fix README +
  `SAFETY_RULES.md` AI-parsing lines (P1-24/29); start the forward-test (P1-25).

**Before paid users:**
- Auth rebuild: random `ADMIN_API_TOKEN` (`compare_digest`) replacing header-ID auth; reject empty
  `EA_API_KEY` — currently fails open (P2-8); license key out of query strings (P3). · UUID/sequence PKs
  (COUNT+1 collides on Postgres, P2-3/7). · Atomic command claim (`UPDATE … WHERE status='PENDING' RETURNING`)
  to stop double-delivery (P2-5); stale-`SENT_TO_EA` sweep/requeue (P2-1/6). · Truthful pause-blocked message
  (P2-2). · `/myrecord` bot command + weekly digest (P2-32). · Written cancel/refund terms; financial-
  promotions review.

**Before hosted/public launch:**
- TLS everywhere (base URL is plain HTTP today); notification offload to `BackgroundTasks` (P3); harden
  `site_server.py` (whitelist paths, self-host fonts, P2-11); exercise the Postgres path (never tested);
  full auth model, not incremental hardening.

**Safety control PASS/FAIL (backend), with the tests to add:**

| Control | Verdict | Test to add |
|---|---|---|
| Demo-only end-to-end | PASS | — |
| Raw text never reaches MT5 | PASS | `test_extract_never_creates_signal_row` |
| Duplicate YES blocked | PASS (caveat: concurrent loser gets 500) | `test_concurrent_double_yes_returns_duplicate_not_500` |
| Signal/command expiry | PASS | — |
| Admin pause blocks commands | PARTIAL (misleading post-resume message) | `test_yes_during_pause_then_resume_message_is_truthful` |
| Parser safety | **FAIL** | `test_parser_rejects_comma_grouped_numbers`, `_nonpositive_prices`, `_implausible_sl_distance` |
| Approve/reject auth | **FAIL** | `test_approve_requires_bot_auth` |
| EA report integrity | **FAIL** | `test_execution_rejected_unless_sent_to_ea`, `_duplicate_execution_report_is_idempotent`, `_stale_open_event_cannot_reopen_closed_command` |
| EA write ownership | **FAIL** | `test_execution_report_scoped_to_owning_license` |
| SENT_TO_EA recovery | **FAIL** | `test_stuck_sent_to_ea_times_out_and_notifies` |
| Vision extractor gate | PASS | (regression lock above) |

**Command state machine — holes to close:** `PENDING → SENT_TO_EA` has no row lock (concurrent polls all win
— HOLE A); `SENT_TO_EA` has no timeout/requeue (orphan forever — HOLE B); management events apply
unconditionally so terminal states reopen and PENDING jumps to FULLY_CLOSED (HOLES C/D/E). Add transition
guards + atomic claim + staleness sweep.

**MT5 top-5 next improvements:** (1) deal-history close detection (`DEAL_REASON_SL` vs `_TP`) — the single
change that protects ledger integrity; (2) retcode gate on every op, map `MARKET_CLOSED`/`NO_MONEY`/
`INVALID_STOPS`; (3) hedging-mode check with single-ticket fallback; (4) file-backed state + backend reset
endpoint; (5) ticket-based child tracking + a report retry queue so a failed WebRequest never silently loses
a lifecycle event. **Do not** add any live-account path, auto-approval, or weaken the `OnInit` demo refusal.

---

## 9. 30 / 60 / 90-Day Roadmap

**Days 0–30 — make the demo + pilot onboarding trustworthy; start the proof.**
- Land all 11 P0s (parser, PII, registration, EA retcode + STOP_LOSS_HIT, the four site claims, form
  endpoint). · Fix README/`SAFETY_RULES.md` AI-parsing contradiction; refresh `CODEX_HANDOFF.md`/`AGENTS.md`.
  · Add the losing-trade simulator scenario + its tests, and the first bot tests. · Add the weekend/market-
  closed note to DEMO_SCRIPT + MT5 README (relevant *this weekend*). · **Kick off the 60–90 day demo
  forward-test** with a fixed rulebook, every Nick signal carded, ledger exported weekly — this is the
  highest-priority workstream, ahead of hosting/pricing/site polish.

**Days 30–60 — run supervised demo pilots; package the paid pilot.**
- Onboard 1 provider + 3–5 followers on the "Watch It Work → Demo Desk" package. · Ship `/myrecord` + weekly
  ledger digest (retention loop). · Land the P1 backend integrity + auth-lite fixes and the MT5 hedging/state/
  LIMIT fixes so a real EA tester's ledger is trustworthy. · Write the one-page pilot definition (who/duration/
  deliverables/success criteria/exit). · Instrument card-sent → decision rate to test the 5-min-expiry
  concern with data.

**Days 60–90 — decide whether to expand; add production infra only if evidence supports it.**
- Publish the first *real* demo verification pack from the ledger, replacing every SAMPLE figure. · Only if
  the pilot produces a credible record + willing-to-pay providers: build the hosted deployment (TLS, real
  auth token, per-tenant EA scoping, UUID PKs, Postgres exercised) and stand up the Pilot Seat with written
  terms + one hour of counsel. · Symbol-whitelist expansion (config-driven) as the first post-pilot feature.
  · **Live trading stays a separate, deliberate, legally-reviewed decision — not on this roadmap.**

---

## 10. Final Recommendation

**Show to prospects now? No.** The page fails its own honesty test in the first screen (hero + step 1) and
carries fabricated verification claims plus a future-dated record — the exact patterns it accuses
competitors of. These are all copy fixes; do them first, they're cheap.

**Use with testers now? Not on MT5 yet.** A solo tester can't even register (P0-7), and if they got past
that, a weekend market-closed order or any stop-out would be written to the ledger as a win (P0-4/5) — the
worst possible first impression for a product whose entire value is an honest record. **The simulator path
is safe to demo today** and should be the tester gate until the EA fixes land.

**What must be fixed first (in order):** (1) the ~10 small P0 correctness/PII/registration bugs; (2) the EA
retcode gate + real `STOP_LOSS_HIT` so the ledger can't lie; (3) the four false site claims rewritten to what
is true and provable today.

**Highest-leverage next week:** ship the P0 fixes **and start the demo forward-test.** Everything sellable
about SignalGate depends on one asset it does not yet have — a real, losses-included execution record — and
that asset can only be *accumulated*. The product is already the machine that produces it. Turn it on.

*SignalGate does not need to look like a finished SaaS company. It needs to become a credible, demo-first
pilot a trader can understand, trust, and safely test. It is closer than the messaging suggests — the honest
engine is real. Make the storefront tell the truth about it, and start building the proof.*
