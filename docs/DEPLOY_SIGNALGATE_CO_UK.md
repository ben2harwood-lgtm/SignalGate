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

---

# Hand this to Codex (paste the block between the markers)

Give this to a computer-control agent that has (a) SSH access to your IONOS VPS
and (b) control of the Chrome window logged into Porkbun. It does the whole
publish and reports back.

------------------------------------ PROMPT ------------------------------------

## Role & mission
You control this Mac's browser (logged into Porkbun) and have SSH to an IONOS
Ubuntu VPS. Mission: **publish the SignalGate launch site live at
https://signalgate.co.uk** with working HTTPS and a working waitlist, then
verify and report. Work autonomously; stop and ask only on a hard blocker (no
SSH access, VPS unreachable, or DNS you cannot edit).

## Rules
- Deploy the **hardened branch `claude/signalgate-full-audit-bjh0tk`**, NEVER
  `main` (main is pre-security-hardening).
- Do not enable the backend/bot or any live-trading path — publish only the
  static launch site + its waitlist (`site-mockups/`).
- Do not invent data. Report exactly what happened, including any failures.

## Facts
- Domain: `signalgate.co.uk` at **Porkbun** (edit DNS in the open Chrome tab).
- Server: the **IONOS VPS** (get its public IPv4 from the IONOS dashboard if you
  don't have it; confirm you can `ssh` in).
- The launch site is `site-mockups/launch.html` served by
  `site-mockups/site_server.py` on `127.0.0.1:8088` (waitlist + referral engine).

## Steps
1. **Get the VPS IP** and confirm SSH works (`ssh root@IP 'echo ok'`).
2. **On the VPS**, install packages: `apt update && apt install -y python3-venv git caddy unzip`.
3. **Get the hardened code onto the VPS** at `/opt/signalgate` (branch
   `claude/signalgate-full-audit-bjh0tk`). Use a GitHub token clone, or download
   the branch ZIP and upload it. Verify `site-mockups/site_server.py` is present.
4. **Run the site as a service** (systemd unit `signalgate-site`) exactly as in
   the "Step 2c" block of this runbook; ensure `/opt/signalgate/site-requests` is
   writable by the service user. Confirm `curl -s localhost:8088/launch.html`
   returns the page.
5. **HTTPS + domain**: write the Caddyfile from "Step 2d" (reverse_proxy to
   `127.0.0.1:8088` for `signalgate.co.uk, www.signalgate.co.uk`) and reload Caddy.
6. **Open the IONOS firewall** for inbound TCP **80** and **443**.
7. **Porkbun DNS** (in Chrome): remove default parking/URL-forward records; add
   `A @ -> VPS_IP` and `A www -> VPS_IP`. Save.
8. **Wait for DNS + certificate** (retry for up to ~30–60 min):
   `curl -sI https://signalgate.co.uk` should return `HTTP/2 200` with valid TLS.
9. **Functional check**: load the page; confirm the countdown renders and a test
   POST to `/api/waitlist` returns a queue position + a referral link. Remove any
   test signup you created from `site-requests/waitlist.jsonl` afterward.

## Report back
The VPS IP, the code branch + commit deployed, the DNS records set, the TLS/HTTP
status of https://signalgate.co.uk, the waitlist test result, and any step that
failed with its exact error.

---------------------------------- END PROMPT ----------------------------------

---

## Later (not needed just to publish the site)

The **backend + Telegram bot** (for MetaTrader testers) is a separate deploy on
the same box — `docs/HOSTED_DEPLOYMENT.md` has it, and it MUST use the new
`ADMIN_API_TOKEN` / `BOT_BACKEND_SECRET` secrets or it will refuse to boot. The
launch site above does not need them; it just collects the waitlist.
