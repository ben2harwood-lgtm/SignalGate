# SignalGate — Marketing Deck

A portable, import-ready slide deck built from the marketing plan in
`docs/FABLE_AUDIT_REPORT.md` (§5 offer, §6 copy, §7 site/funnel, §9 roadmap).

**How to use this file:** each slide is separated by `---`. Slide titles are `#`
headings; bullet lines are the on-slide content; the *Speaker notes* block under each
slide is for you, not the audience. This format pastes cleanly into Gamma, Pitch,
Beautiful.ai, Marp, Google Slides (via a Markdown-to-Slides add-on), or Keynote outline.

**Governing rule for every slide (do not break it):** sell *discipline and
auditability*, never coverage or returns. No performance figures — none exist yet.
No profitability claims. Demo-only, and say so.

---

# SignalGate

### Execution discipline and an honest record — for traders who already follow signals

Demo-only v1 · You approve every trade · No live money anywhere in the system

> *Speaker notes:* Open on the promise, not a chart. The category opens on fake equity
> curves — we deliberately don't. One line: "We don't sell you signals or profits. We
> execute the signals you already follow, by a fixed rulebook, and log every step so you
> can check it." Keep the demo-only chip visible; honesty is the brand.

---

# The problem

- Retail traders follow signals but **execute them badly** — late entries, no stop,
  moved stops, oversized, revenge trades, missed exits.
- The result gets blamed on the signal provider even when the *execution* was the failure.
- The whole category "proves" itself with screenshots and equity curves that **can't be
  checked** — the #1 scam pattern.

> *Speaker notes:* This is the wedge. The pain isn't "I need more signals," it's "I don't
> follow the ones I have with any discipline, and I can't trust anyone's track record."
> Providers feel the second half acutely: their followers execute sloppily and it wrecks
> the provider's reputation.

---

# What SignalGate is

- A signal becomes a **structured trade card** in your Telegram.
- **You tap Approve** → it executes on a MetaTrader 5 **demo** account with a **hard stop
  attached** and staged take-profits.
- **You tap Ignore** → nothing happens.
- Every fill, stop move, and close is written to an **audit log you can read**.
- Raw signal text **never touches the broker** — only checked, approved commands do.

> *Speaker notes:* Four verbs: card, approve, execute-on-demo, log. The differentiators
> that are true *today*: mandatory human tap, hard stop always in, one approval = exactly
> one command, full audit trail. That's the moat — an honest core in a dishonest category.

---

# How it works — four steps

1. **Signal in.** Your provider sends the call to the bot — typed, or as a screenshot
   the system reads and shows back to a human for confirmation.
2. **Card out.** A validated, structured card lands in your Telegram with the symbol,
   direction, hard stop, and TP1/TP2/TP3.
3. **You decide.** Tap Approve or Ignore. Approve creates exactly one command; the same
   approval can never fire twice; a missed card expires in 5 minutes as *no trade*.
4. **Executed & logged.** It opens on a demo account with the stop in, stages the
   take-profits, moves the stop by the rulebook, and logs every step.

> *Speaker notes:* Emphasise the safety boundary between step 1 and 2: a deterministic
> parser checks every number; nothing free-text reaches the trading side. "Reads a
> screenshot" is a convenience at ingestion — a human still confirms before anything goes out.

---

# Why this is different — the honest core

- **Hard stop, always.** Every trade opens with a stop. No exceptions.
- **You approve every trade.** Nothing opens without your tap. No auto-copy, no bot
  trading "while you sleep."
- **One tap, one command.** Duplicate taps can't create duplicate trades (enforced in
  the database, not just the UI).
- **A record when it's real.** Every action is logged now; a *published* track record
  comes only when the forward test produces one — with the losing trades included.

> *Speaker notes:* These four are all verifiable and all true today. This slide is the
> antidote to "is this another robot scam?" Note what we DON'T claim: no returns, no
> "verified" record yet, no channel auto-monitoring. Under-claiming is the strategy.

---

# Who it's for

- **Primary (the pilot customer): signal providers** like Nick — people who send calls
  to a following and whose reputation depends on those calls being executed well and
  provable.
- **Secondary: disciplined signal-followers** who want their approved trades executed by
  a rulebook and logged, instead of by their own worst impulses at 2am.

> *Speaker notes:* The strategic correction from the audit: the built product points at
> *providers* (B2B2C), even though the obvious pitch is to followers. Land one provider +
> a handful of their followers first. The provider brings the audience and the signals;
> we give them an asset no competitor has — a timestamped record of their own calls' execution.

---

# What the signal provider (Nick) actually gets

- **Gatekeeper control** — nothing reaches testers unless *he* confirms every number.
- **An independent, timestamped forward-test record of his signals' execution** — an
  asset no screenshot-poster has.
- **Reputation protection** — followers stop executing his calls badly and blaming him.
- **Near-zero admin** — about 2 minutes per signal.

> *Speaker notes:* Lead with what he *gets*, not his task list. His product isn't "please
> send screenshots"; it's "an honest, checkable record of how your calls actually
> perform when executed with discipline." That's the Provider Desk.

---

# The offer ladder

| Tier | Name | Price | Core deliverable |
|---|---|---|---|
| 0 | **Watch It Work** | Free, 15 min | Live walkthrough on their own phone: a real signal → card → they tap Approve → watch the demo execution + ledger fill in real time. *(Works today.)* |
| 1 | **Demo Desk** | Free, 14 days | A seat on hosted infra + their own MT5 **demo** via the EA. Ends with a personal **Discipline Report** — the exported ledger of every card, tap, fill, and stop move. |
| 2 | **Pilot Seat** | Paid, invite-only *(price set only after real proof exists)* | Hosted seat + license, concierge MT5-demo setup, weekly ledger review, priority support, pause anytime. Still demo-only. |
| 3 | **Provider Desk** | Setup fee or rev-share *(later)* | Screenshot-gatekeeper ingestion, multi-tester cards, and an exportable **forward-test ledger of the provider's own signals**. |

> *Speaker notes:* The offer is **hosting + concierge onboarding + an auditable record** —
> never a signal or an expected profit. "Watch It Work → Demo Desk" is the first sellable
> package: run it for one provider + 3–5 of his followers, 8 weeks, to produce the first
> real demo execution record. Free is fine; *undefined* is not — who, how long, what they get.

---

# The messaging — say this, not that

- **Say:** "The signals you follow, executed by a fixed rulebook — hard stop in, every
  step logged." **Not:** "executed properly, even when you're not watching." *(There's a
  mandatory tap and a 5-minute expiry — don't contradict the product.)*
- **Say:** "We can show you the pipeline live and the audit log of your own demo trades."
  **Not:** "independently reconciled / read-only verified record." *(That doesn't exist yet.)*
- **Say:** "Most retail traders lose money; a tool doesn't change that. v1 is demo-only."
  **Not:** anything that sounds like a return.
- **Say:** "No performance figures are published because none exist yet." **Not:** a
  sample equity curve as the hero image.

> *Speaker notes:* The brand's whole pitch is honesty, so the copy has to pass its own
> test in the first screen. Every "say" here is provable today; every "not" is a claim the
> product can't back. When pricing exists, it gets printed plainly — not teased.

---

# Proof — what we can show, and what we can't (yet)

- **We can show you, live:** a signal becoming a card, your tap becoming exactly one
  command, a demo execution with the stop attached, the take-profit stages firing, and
  every step written to a readable audit log.
- **We can't show you yet:** a track record. SignalGate is in forward-testing on demo;
  no performance figures exist, so we publish none.
- **When the record is real,** it publishes with the account identifier, the date range,
  **every losing trade**, and a way to check it that doesn't depend on our word.

> *Speaker notes:* This honest framing is *stronger* than a fake curve for a scam-wary
> audience — it's the thing competitors can't say. Any illustration on the site is
> labelled "sample data — not a record," dated in the past, and shows the drawdown. The
> live audit trail filling in during the demo is the real proof asset.

---

# The site & funnel — what changes

- **Above the fold:** replace the sample equity chart with a mock of the **real Telegram
  trade card** + a 3-line audit-log strip (`OPENED → TP1_CLOSE_SUCCESS →
  SL_MOVE_BREAKEVEN_SUCCESS`). Show the product; lead with the *true* claims.
- **One CTA, one job:** "Request a demo setup" → a real form to a real inbox, with an
  honest error state and a stated "a real person replies on Telegram/email."
- **Fix the credibility leaks:** delete the fake verifier seal; remove the future-dated
  record; add a contact channel (there is none today); add a privacy note.
- **Mobile + trust basics:** working nav under 860px, self-hosted fonts, favicon/meta.

> *Speaker notes:* The current mockup's biggest funnel leak is that there's no way to
> contact anyone, and its biggest credibility leak is asserting a verified record that
> doesn't exist, dated into the future. Both are cheap copy/markup fixes — do them before
> showing the page to anyone.

---

# Roadmap — 30 / 60 / 90 days

- **0–30 · Make the demo trustworthy; start the proof.** Land the correctness/PII/
  registration fixes; rewrite the false site claims to what's true today; **kick off the
  60–90 day demo forward-test** — every provider signal carded, ledger exported weekly.
  *(This is the highest-priority workstream, ahead of hosting and site polish.)*
- **30–60 · Run supervised demo pilots; package the paid tier.** Onboard 1 provider +
  3–5 followers on "Watch It Work → Demo Desk." Ship a personal record command + weekly
  digest. Write the one-page pilot definition (who / duration / deliverables / exit).
- **60–90 · Decide whether to expand.** Publish the first *real* verification pack from
  the ledger. Build hosted infra + paid Pilot Seat **only if** the pilot produced a
  credible record and willing-to-pay providers.

> *Speaker notes:* The proof can't be written or bought — only accumulated. Every week
> without the forward-test running is a week the paid offer can't be honest. Live trading
> is deliberately **not** on this roadmap — it stays a separate, legally-reviewed decision.

---

# The ask / next step

- Run **"Watch It Work"** with Nick and 3–5 of his real followers.
- 8 weeks, demo-only, one goal: **produce the first real demo execution record.**
- Free, but defined — who, how long, what they get, what we measure, when it ends.

> *Speaker notes:* Close on the concrete first move, not a pricing conversation. The
> deliverable of the pilot is the record itself — the asset that makes everything after
> it sellable. End where the deck started: we sell discipline and an honest record, not
> coverage or returns.

---

# Appendix — the guardrails (internal; don't ship claims that break these)

- **Demo-only v1.** No live account, no auto-copy, no payments, no dashboard in scope.
- **No performance/profitability claims.** No published figures until a real record exists.
- **No fake proof.** No fabricated testimonials, seals, reconciliation, or future-dated
  records. Illustrations are labelled sample data and dated in the past.
- **Honest language only:** "demo," "forward testing," "ledger," "execution discipline,"
  "risk-controlled." Get one hour of financial-promotions counsel before any paid tier or
  live language ships.

> *Speaker notes:* Keep this slide out of the customer deck — it's the checklist for
> whoever edits the copy downstream. If a slide anywhere makes a claim that breaks one of
> these four rules, cut the claim, not the rule.
