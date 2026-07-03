# SignalGate — What a Sellable ("Hosted") Version Would Take

*Plain-English plan. Demo-only posture preserved throughout. Not legal or financial advice.*

## The one idea behind all of this

Right now, **every customer runs the whole engine on their own computer**: Python, the
backend server, the Telegram bot, plus MetaTrader. That's why setup feels heavy — because
it is. It's the right shape for a prototype and for *your* testing, but it's the wrong shape
for paying customers.

The fix is to move the heavy parts to **one server that you run**, so the customer is left
with only the single piece that genuinely *has* to live on their machine: the MetaTrader EA
that talks to *their* broker account.

```
   TODAY (local)                          HOSTED (sellable)
   ─────────────                          ─────────────────
   Customer PC:                           YOUR server (one, for everyone):
     • Python                               • Backend + database
     • Backend server                       • Telegram bot (one shared bot)
     • Telegram bot
     • MetaTrader + EA                     Customer PC:
                                             • MetaTrader + EA   ← that's it
```

That single change is what turns "a developer tool" into "a product a normal trader can use."

## What the customer's setup shrinks to

Today the customer has to: install Python → create their own Telegram bot → run two server
windows → install MetaTrader → compile and configure the EA → whitelist a local address. Six
fiddly steps, several of them developer-grade.

In the hosted version it becomes:

1. Buy → receive a **license key** and a link to **your** Telegram bot.
2. Open Telegram, tap **Start** on your bot (this links their account — no BotFather, no token).
3. Install MetaTrader 5 and open a **demo** account (most already have MT5).
4. Drop in the EA, paste their license key, tick the one settings box, attach to a chart.

No Python. No terminal. No bot creation. No servers. That's competitive with how every other
EA/signal product on the market onboards people.

## What runs where, and what it costs

You'd run everything central on one small Linux server (a "VPS"). Realistic monthly cost,
based on current 2026 pricing:

| Piece | Where | Rough cost |
|---|---|---|
| Backend + bot + database | One Linux VPS (Hetzner / DigitalOcean) | ~$5–10 / month |
| Domain name (e.g. `api.yoursite.com`) | Any registrar | ~$10–15 / year |
| HTTPS certificate | Let's Encrypt | Free (automatic) |
| The Telegram bot | Telegram | Free |

So you're looking at roughly **$10–15/month all-in** to start, and a single small box
comfortably serves dozens to low-hundreds of customers before you'd need to size up.

One honest catch worth naming up front: for a customer to *catch signals while they're away
from their PC*, their **MetaTrader** needs to be running 24/7 — which usually means the
customer also wants a small "forex VPS" for MT5 (commonly ~$8–15/month from MT5-specialist
hosts, and MetaTrader itself offers built-in hosting around $12–15/month). That's normal in
this market and not something you host — but it's a real cost/friction point for the customer,
so it belongs in your sales honesty.

## What changes in the code (it's less than you'd fear)

The entire trading brain — signal parsing, the YES/NO trade card, one-tap approval, the single
safe command, the split-ticket partial-profit logic, the take-profit/stop-loss management, the
ledger, all the safety guards — **stays exactly as it is.** You already proved that loop works
end to end on a real demo account. The hosted work is almost entirely *relocation and
hardening*, not rewriting the product. Concretely:

- **Database:** swap SQLite for PostgreSQL so many customers can be served at once. SQLAlchemy
  (already used) supports this by changing one connection string plus a driver — small change,
  not a rewrite.
- **Put it behind HTTPS:** today the EA talks to `http://127.0.0.1`. Hosted, it talks to
  `https://api.yoursite.com`. This needs a "reverse proxy" (Caddy does it with automatic free
  certificates) in front of the backend. The EA already supports `https` requests; you change
  its URL setting and whitelist that one address.
- **Make it multi-customer (the real work):** the database already has `users`, `status`, and
  `license_key` fields, so the bones are there. What's needed is to (a) issue a license key per
  customer, (b) tie each EA's key to that customer on every request, and (c) let you
  activate/deactivate a customer. This is the main piece of genuinely new logic.
- **One shared bot:** instead of each customer making a bot, you create *one* bot; customers
  just message it. Their Telegram `Start` links their account to their license.
- **Run it as a service + back it up:** the backend and bot run as always-on background
  services on the VPS (auto-restart on reboot/crash), with a nightly database backup. Standard,
  well-trodden setup.

## What I would deliberately NOT do (and why)

- **Keep trades in the customer's own broker account.** The EA runs on *their* MetaTrader, so
  trades happen in *their* account and you never touch their broker login or their money. Keep
  it that way — it's both safer and far cleaner regulation-wise than ever handling funds.
- **Stay demo-only for the first market test.** Flipping to real money is a much bigger safety
  and legal step, not a settings change. Prove demand and reliability on demo first.
- **No profitability claims, anywhere.** Honest language only: "demo", "forward testing",
  "execution tracking", "risk-controlled". This protects you.

## Two flags before you spend money on this

1. **Regulation.** Selling a tool that places trades — even demo-by-default — can trigger
   financial-promotion and licensing rules that vary a lot by country and by who your customers
   are. I'm not a lawyer; get one to look before you take payment. This is the single biggest
   non-technical risk.
2. **Support load.** The moment people pay, "it won't connect" becomes your problem at all
   hours. The hosted model actually *helps* here (the hard parts are on your one server, which
   you control and can see logs for), but budget time for customer hand-holding on the MT5 step,
   which stays on their side.

## Suggested order if you decide to go for it

1. Stand up one VPS, a domain, and HTTPS; deploy the existing backend + bot unchanged.
2. Switch the database to PostgreSQL.
3. Add license keys + per-customer activation (the main new code).
4. Point the EA at the hosted HTTPS address; ship a customer EA that only needs a license key.
5. Onboard 2–3 friendly demo testers end to end before charging anyone.
6. Only then: pricing, payment, and the legal review above.

---

*Bottom line: you've already built and proven the hard part. Going sellable is mostly moving
the engine to one server you control and adding customer accounts — not rebuilding the product.
The terminal disappears for the customer because they stop running the engine at all.*
