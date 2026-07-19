# Publishing signalgate.co.uk live

Goal: the launch page (with the working waitlist + referral loop) reachable at
**https://signalgate.co.uk** for the public.

## The mental model (two pieces)

1. **Domain — Porkbun.** `signalgate.co.uk` is registered at Porkbun. You use
   Porkbun only to point the domain at a server (a DNS "A record").
2. **Server — your IONOS VPS.** The site *runs* here (it has a live waitlist +
   referral engine, so it needs a server, not just file hosting). This is the box
   Codex was working on.

Publishing = point (1) at (2), with the hardened code running on (2).

> **⚠️ Before it's public — the legal check.** A signals-to-execution service may
> be a regulated activity in the UK, and its promotions may need an FCA-authorised
> approver. Have one hour with a financial-promotions solicitor first. The copy is
> written defensively (demo / forward-test / no advice / no performance claims) to
> make that cheap — but have it before the public can reach the page.

---

## What you need in front of you

- Your **IONOS VPS public IP** (IONOS dashboard → your server → "IPv4"). Looks
  like `82.165.x.x`.
- **SSH access** to it (`ssh root@THAT_IP`, or the login IONOS gave you).
- The site runs the **hardened branch** `claude/signalgate-full-audit-bjh0tk` —
  **not** `main` (main is 21 commits behind and pre-security-hardening).

Everything below is run **on the VPS** except Step 1 (Porkbun, in your browser).

---

## Step 1 — Point the domain at the server (Porkbun, in Chrome)

1. Porkbun → **Domain Management** → `signalgate.co.uk` → **DNS** (the "Details /
   DNS Records" area).
2. **Remove** any default parking records — Porkbun usually adds an `ALIAS`/`URL
   forward` on the root and an `A`/`CNAME` on `www`. Delete those so they don't
   fight your new ones.
3. **Add these two records** (TTL: leave default / 600):
   | Type | Host | Answer / Value |
   |------|------|----------------|
   | A | *(leave blank = the root domain)* | `YOUR_VPS_IP` |
   | A | `www` | `YOUR_VPS_IP` |
4. Save. DNS takes ~5–60 minutes to spread. You can move on to Step 2 meanwhile.

---

## Step 2 — Put the site on the server (IONOS VPS, over SSH)

SSH in, then:

```bash
# 2a. System packages (Caddy gives automatic HTTPS)
sudo apt update && sudo apt install -y python3-venv git caddy unzip

# 2b. Get the HARDENED code onto the box.
#     The repo is private, so the easy path is the same branch ZIP you
#     downloaded on your Mac: upload it, or download it here with a GitHub
#     token. Simplest: on your Mac, upload the folder to the server:
#       (on your Mac)  scp -r ~/SignalGate root@YOUR_VPS_IP:/opt/signalgate
#     OR clone with a GitHub Personal Access Token:
#       git clone https://<TOKEN>@github.com/ben2harwood-lgtm/signalgate.git /opt/signalgate
#       cd /opt/signalgate && git checkout claude/signalgate-full-audit-bjh0tk
cd /opt/signalgate   # wherever the code now lives
```

```bash
# 2c. Run the waitlist site as an always-on service.
sudo tee /etc/systemd/system/signalgate-site.service >/dev/null <<'UNIT'
[Unit]
Description=SignalGate launch site + waitlist
After=network.target

[Service]
WorkingDirectory=/opt/signalgate/site-mockups
ExecStart=/usr/bin/python3 /opt/signalgate/site-mockups/site_server.py
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
UNIT

# waitlist signups are written here; make it writable by the service
sudo mkdir -p /opt/signalgate/site-requests
sudo chown -R www-data:www-data /opt/signalgate/site-requests /opt/signalgate/site-mockups

sudo systemctl daemon-reload
sudo systemctl enable --now signalgate-site
curl -s localhost:8088/launch.html | head -1    # should print the page's first line
```

```bash
# 2d. HTTPS + the domain. Caddy fetches a free certificate automatically once
#     DNS (Step 1) points here and ports 80/443 are open.
sudo tee /etc/caddy/Caddyfile >/dev/null <<'CADDY'
signalgate.co.uk, www.signalgate.co.uk {
    reverse_proxy 127.0.0.1:8088
}
CADDY
sudo systemctl reload caddy
```

Make sure the IONOS firewall (in the IONOS dashboard) allows inbound **80** and
**443**.

---

## Step 3 — Point the launch to the real date

The countdown targets **Sunday 19 July 2026, 10:00 UTC** already. If that's your
go-time, nothing to change. To adjust, edit one line in
`site-mockups/launch.html`:

```js
const OPENS_UTC = "2026-07-19T10:00:00Z";
```

then `sudo systemctl restart signalgate-site`.

---

## Step 4 — Verify it's live

Once DNS has propagated (give it up to an hour):

```bash
curl -sI https://signalgate.co.uk | head -3     # HTTP/2 200, valid TLS
```

Then open **https://signalgate.co.uk** in a browser: the page loads over HTTPS
(padlock), the countdown runs, and a test signup returns a queue position + an
invite link. **Send me the domain once it resolves and I'll verify the whole
thing from here** — TLS, the page, the waitlist, the referral loop, and that
it's the hardened code.

---

## Later (not needed just to publish the site)

The **backend + Telegram bot** (for MetaTrader testers) is a separate deploy on
the same box — `docs/HOSTED_DEPLOYMENT.md` has it, and it MUST use the new
`ADMIN_API_TOKEN` / `BOT_BACKEND_SECRET` secrets or it will refuse to boot. The
launch site above does not need them; it just collects the waitlist.
