# SignalGate — Hosted Deployment & Customer-Facing EA Changes

How to run the backend + Telegram bot once, centrally, so that each customer
only installs the MetaTrader EA. **Demo-only posture is unchanged.** This is not
legal or financial advice — see the regulation note at the end.

The code already supports this. The new pieces (added in the same change as this
doc) are:

- `REQUIRE_LICENSE` env flag — when `true`, an EA must present a valid, ACTIVE
  customer **license key** to receive commands.
- Per-customer **license keys** (auto-issued on `/start`, or issued/rotated by
  an admin endpoint).
- Admin endpoints to **list / activate / deactivate** customers.
- PostgreSQL support via `DATABASE_URL` (SQLite stays the local default).

Nothing about the trading logic, parser, split-ticket management, ledger or
safety guards changed. Locally, with `REQUIRE_LICENSE=false`, everything behaves
exactly as before.

---

## 1. The shape of the hosted system

```
                    ┌──────────────────────── YOUR SERVER (one VPS) ────────────────────────┐
   Telegram  ◄────► │  Telegram bot  ──►  FastAPI backend  ──►  PostgreSQL                   │
   (your ONE bot)   │                         ▲   ▲                                          │
                    │                Caddy (HTTPS, :443)  ◄──── api.yoursite.com             │
                    └──────────────────────────────▲───────────────────────────────────────┘
                                                    │ HTTPS, license key
                       ┌────────────────────────────┴───────────────┐
                  Customer A's MetaTrader 5 + EA      Customer B's MetaTrader 5 + EA
                  (their broker demo account)         (their broker demo account)
```

You run the bot + backend + database. Each customer runs only MetaTrader with the
EA, pointed at your HTTPS address and carrying their own license key. Trades
happen in each customer's own broker account — you never touch their funds or
broker login.

---

## 2. Server setup (once)

A small Linux VPS (1–2 vCPU, 2 GB RAM) is plenty to start. Steps assume Ubuntu.

### 2a. System packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip postgresql caddy git
```

### 2b. PostgreSQL database + user

```bash
sudo -u postgres psql <<'SQL'
CREATE USER signalgate WITH PASSWORD 'CHANGE_ME_STRONG';
CREATE DATABASE signalgate OWNER signalgate;
SQL
```

### 2c. Get the code and install (hosted requirements include the PG driver)

```bash
cd /opt && sudo git clone <your-repo> signalgate && cd signalgate
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-hosted.txt
python3 -m venv telegram_bot/.venv
telegram_bot/.venv/bin/pip install -r telegram_bot/requirements.txt
```

### 2d. Environment (`/opt/signalgate/.env`)

```env
# --- hosted database & mode ---
DATABASE_URL=postgresql://signalgate:CHANGE_ME_STRONG@localhost:5432/signalgate
REQUIRE_LICENSE=true
DEMO_ONLY_MODE=true

# --- backend ---
BACKEND_BASE_URL=https://api.yoursite.com

# --- your single shared bot + your admin Telegram id(s) ---
TELEGRAM_BOT_TOKEN=your_real_bot_token
ADMIN_TELEGRAM_IDS=your_numeric_telegram_id

# --- shared EA gate key (still required IN ADDITION to per-customer licenses) ---
EA_API_KEY=generate_a_long_random_value

# --- HOSTING HARDENING (REQUIRED in hosted mode; the backend refuses to boot
#     without them). Generate each: python3 -c "import secrets;print(secrets.token_urlsafe(32))"
ADMIN_API_TOKEN=generate_a_long_random_value    # real admin credential (X-Admin-Token)
BOT_BACKEND_SECRET=generate_a_long_random_value  # authenticates the bot to the backend
EXPOSE_DOCS=false                                # hide /docs on the public server
RATE_LIMIT_PER_MINUTE=60

DEFAULT_SIGNAL_EXPIRY_MINUTES=5
SPLIT_TICKET_DEMO_PARTIAL_MODE=true
```

> **Why these exist.** On a public server the old auth was spoofable: admin was
> gated only by a Telegram id (public), and the endpoints the bot proxies
> (approve/reject/register/user-lookup, which returns a customer license key)
> were open. Hardened: `ADMIN_API_TOKEN` is now the only admin credential,
> `BOT_BACKEND_SECRET` gates the bot surface, both compared in constant time,
> and with `REQUIRE_LICENSE=true` the server **refuses to boot** if they (or a
> non-default `EA_API_KEY`) are missing — so you can't accidentally ship an open
> box. `/docs` is hidden, and public endpoints are per-IP rate-limited.

Initialise the database tables:

```bash
backend/.venv/bin/python scripts/init_db.py
```

### 2e. HTTPS reverse proxy (Caddy gives you a free auto-renewing certificate)

`/etc/caddy/Caddyfile`:

```
api.yoursite.com {
    reverse_proxy 127.0.0.1:8000
}
```

Point the DNS `A` record for `api.yoursite.com` at the server, then
`sudo systemctl reload caddy`. Caddy fetches the TLS certificate automatically.

### 2f. Run backend + bot as always-on services

`/etc/systemd/system/signalgate-backend.service`:

```ini
[Unit]
Description=SignalGate backend
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/signalgate/backend
EnvironmentFile=/opt/signalgate/.env
ExecStart=/opt/signalgate/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/signalgate-bot.service`:

```ini
[Unit]
Description=SignalGate Telegram bot
After=network.target signalgate-backend.service

[Service]
WorkingDirectory=/opt/signalgate/telegram_bot
EnvironmentFile=/opt/signalgate/.env
ExecStart=/opt/signalgate/telegram_bot/.venv/bin/python run_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now signalgate-backend signalgate-bot
curl https://api.yoursite.com/health     # {"status":"ok","demo_only_mode":true,...}
```

> Note: behind Caddy the backend binds `127.0.0.1` (not `0.0.0.0`) — only Caddy
> needs to reach it, and Caddy is what faces the internet over HTTPS.

### 2g. Nightly database backup (cron)

```bash
echo '0 3 * * * postgres pg_dump signalgate | gzip > /var/backups/signalgate-$(date +\%F).sql.gz' \
  | sudo tee /etc/cron.d/signalgate-backup
```

---

## 3. Customer lifecycle (the license workflow)

1. **Customer messages your bot** `/start`. They are registered and a license
   key (`SG-XXXX-XXXX-XXXX`) is auto-issued. `/status` shows it back to them.
2. **(Optional) You issue or rotate a key manually** — e.g. after payment
   clears:
   ```bash
   curl -X POST https://api.yoursite.com/admin/users/<telegram_id>/issue_license \
        -H "X-Admin-Id: <your_admin_id>"
   # -> {"license_key":"SG-AB12-CD34-EF56", ...}
   ```
3. **Customer pastes the key into their EA** (next section) and starts trading on
   their demo account.
4. **Suspend / restore access** (subscription lapsed, refund, abuse):
   ```bash
   curl -X POST .../admin/users/<telegram_id>/deactivate -H "X-Admin-Id: <id>"
   curl -X POST .../admin/users/<telegram_id>/activate   -H "X-Admin-Id: <id>"
   ```
   A deactivated customer's EA simply receives no commands — cleanly, with no
   error to chase.
5. **See everyone**: `GET /admin/users` lists each customer's status + key.

---

## 4. Customer-facing EA changes

The EA already sends its license key on every poll
(`/commands/pending?user_id=...&license_key=...`), so **no recompile is required
for the protocol** — only the input values the customer sets when they attach the
EA to a chart.

| EA input | Local/demo value (today) | Hosted value (what the customer sets) |
|---|---|---|
| `BackendURL` | `http://127.0.0.1:8000` | `https://api.yoursite.com` |
| `LicenseKey` | `local-demo` (placeholder) | **their** `SG-XXXX-XXXX-XXXX` key |
| `UserID` | `USER-000001` | leave as-is / ignored (license is authoritative in hosted mode) |
| `EAApiKey` | `local-demo-ea-key` | the shared `EA_API_KEY` you set on the server |
| `DemoOnlyMode` | `true` | `true` (keep it true) |

And the one MetaTrader setting that always trips people up:

- **Tools → Options → Expert Advisors → Allow WebRequest for listed URL**, and
  add `https://api.yoursite.com`. (HTTPS works with MT5 WebRequest; just whitelist
  the exact address.)

In hosted mode (`REQUIRE_LICENSE=true`) the backend identifies the customer by
the license key and ignores `UserID`, so two customers can run the same EA build
and only their keys differ. If a key is wrong, missing, or deactivated, the EA
receives no command (rather than someone else's) — that is the multi-tenant
safety boundary.

### What you ship each customer

- The compiled `SignalGateEA.ex5` (so they don't need MetaEditor), or the
  `.mq5` if you want them to compile.
- A one-page card: their license key, your `api.yoursite.com` address, the shared
  EA key, and the WebRequest-whitelist step.

> Practical reality to disclose up front: to catch signals while away from their
> PC, a customer's MetaTrader must run 24/7 — usually on a small MT5 VPS
> (~$8–15/month) they provide. That cost is theirs, not yours, but be honest
> about it when selling.

---

## 5. Security checklist before charging anyone

- `DEMO_ONLY_MODE=true` everywhere; do not build a live path for the first market.
- Strong, unique `EA_API_KEY` and database password; never commit `.env`.
- HTTPS only (Caddy handles certs); the backend itself stays bound to localhost.
- Rotate a customer's license (`issue_license`) if it leaks; deactivate on abuse.
- Keep nightly DB backups and test a restore once.
- Consider per-IP rate limiting at Caddy if you grow.

## 6. Regulation note (read before taking payment)

Selling a tool that places trades — even demo-by-default — can trigger
financial-promotion and licensing obligations that vary a lot by country and by
who your customers are. Get a lawyer to review before you take money. Keep all
language honest ("demo", "forward testing", "execution tracking"); make no
profitability claims anywhere in the product, bot, or marketing.
