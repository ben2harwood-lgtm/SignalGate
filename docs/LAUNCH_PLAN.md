# SignalGate — Launch Plan (Sunday)
### The simple version: get signups → get shares → get referrals

This is the distilled, do-it-this-week version of the full growth plan
(`docs/GROWTH_MARKETING_PLAN.md`). One goal for launch: **fill the founding
waitlist and make it spread itself.** Everything below is executable by one
person and holds the honesty line the whole brand is built on.

> **⚠️ READ FIRST — legal.** The launch research surfaced a material risk: a
> service that turns signals into executed trades may itself be a **regulated
> activity** in the UK (arranging/dealing/advising), and an unauthorised firm's
> financial promotions may need approval by an FCA-authorised person (s21 FSMA).
> Demo-only reduces but doesn't automatically remove this. **Get one hour of UK
> financial-promotions legal advice before the site goes public.** The site copy
> is already written defensively (demo / forward-test / execution tool, no
> advice, no profit claims) to make that conversation cheap — but have it.

---

## 1. The offer (one sentence)

**Founding access to SignalGate — the first 100 members of the public
forward-test, free, demo-only, and you keep your own audit record.** Refer
friends to move up the line and earn the founding badge. No cash, no points —
just earlier access. (Cash referral rewards are a UK compliance problem;
access/status rewards are not. This is deliberate.)

Why "founding member" works here: the cap is **real** — one operator can only
onboard so many people transparently — so the scarcity is honest, which is the
whole point of the brand.

---

## 2. The mechanic (already built)

The launch page (`site-mockups/launch.html`) does this automatically:

1. One-field email → instant status page showing **your position, your referral
   count, and your personal invite link** (the Robinhood loop).
2. **Referring moves you up.** Position is ranked by referrals first, join-time
   second — so a friend who joins through your link genuinely puts you ahead of
   people who joined earlier but referred no-one. Real, not invented.
3. **First 100 = founding members**, shown with a badge and a progress bar.
4. Every number is the true number. The count only shows once it's meaningful
   (25+), and it can never be inflated by resubmits.

Your only job is to get people to the page and give them a reason to share it.

---

## 3. Launch week sequence

**Thu–Sat (pre-flight):**
- Get the legal sign-off above.
- Host the site (see `docs/HOSTED_DEPLOYMENT.md` / the launch page can go on any
  static host; the waitlist needs the small `site_server.py` or an equivalent
  endpoint running).
- Set `OPENS_UTC` in `launch.html` to the real Sunday time (already
  `2026-07-19T10:00:00Z` — adjust if needed).
- Seed the list yourself + 3–5 people you know, so day-one visitors don't land
  on an empty page. (The count stays hidden below 25, so this is just so the
  first sharers have a position to show off.)
- Line up **Nick's announcement** — he is the single biggest launch lever.

**Sunday (launch):**
- **Nick posts to his own group first** (warmest audience, highest convert).
  Draft below.
- You post the launch across your channels within the same hour (below).
- Personally DM the 10 warmest prospects the direct link.

**Sunday+7 (momentum):**
- Post the **first week's forward-test record** (wins and losses) — this is the
  content engine and the proof the whole page promises. Nothing spreads the
  honesty brand like the first real losing week published on purpose.
- Thank + spotlight the top referrers (with permission). Social proof + fuel.

---

## 4. Exactly what to post (copy you can paste)

**Nick → his group (the money post):**
> I've started forward-testing my own signals through an independent tool for
> the next few weeks — every call carded, executed by a fixed rulebook with a
> hard stop, and logged to a record you'll be able to check. Wins *and* losses,
> published. First 100 founding testers get in free (demo accounts). Here's the
> link — refer a mate and you move up the queue: [YOUR-REF-LINK]

**You → X / FinTwit:**
> Building the opposite of a signal-scam: a tool that turns a signal into a
> one-tap trade card, executes it on a demo account with a hard stop, and
> publishes the record — losing trades included. No track record yet. That's the
> point — watch it build, live. Founding access (first 100): [LINK]

**You → Reddit (r/Forex, r/Daytrading) — no link-drop, comment-led:**
> Post a genuine "why signal followers lose on execution, not signals" writeup;
> mention you're running a public forward-test that publishes losses; link only
> if asked / in profile. Reddit punishes promotion and rewards receipts.

**Share prompt on the page itself** (already there): the invite link + "every
friend who joins moves you up."

---

## 5. Channels, ranked for a solo founder

1. **Nick's group** — warmest, highest-converting. The launch lives or dies here.
2. **The referral loop** — your existing signups are the channel; make sharing
   effortless (done: one-tap copy link + a real reason to share).
3. **X / FinTwit** — build-in-public + the weekly record drop.
4. **Reddit / ForexFactory** — receipts and a public journal thread, never a pitch.
5. **Direct DMs** — the 10–20 warmest people, by hand. Unscalable, essential at 0→50.

Skip paid ads entirely for launch (premature, hostile finance-ad terrain, and a
trust-inversion brand buying hype ads contradicts itself).

---

## 6. What makes it spread (the levers, named)

- **Endowment + status:** people share to protect *their* position and badge —
  they're defending something they own.
- **Honest scarcity:** a real cap (100) creates real urgency without a fake clock.
- **Costly signalling:** publishing losses is the shareable thing nobody else in
  the category will do — every share plants "demand receipts."
- **Provider loop:** each provider onboarded brings a whole audience (B2B2C).
  After launch, recruiting provider #2 and #3 is the highest-leverage growth act.

---

## 7. Measure only these

- Reservations/day and **source** (which channel moved).
- **Referral rate** = signups that came via a ref link (target the fintech
  benchmark ~30%+).
- Share rate of the invite link (are people actually copying it).
- Week-1 → week-2 return (once the forward-test digests start).

If referral rate is low after launch, the *reward* framing is off (re-test the
"move up the line" message), not the traffic.

---

## 8. The hard "don't", for launch specifically

No cash/bonus referrals (UK inducement risk). No fake counts or countdowns
(the code won't let you anyway). No performance or profit claims. No
testimonials before real, consented ones exist. No paid shoutouts in
signal-selling groups. One fake anything and the only unclaimed position in the
category — verifiable honesty — is gone.
