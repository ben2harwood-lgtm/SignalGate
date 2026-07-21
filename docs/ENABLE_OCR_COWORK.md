# Enable real screenshot OCR — step-by-step for a Cowork agent

**Goal:** switch SignalGate's screenshot reader from the offline "fake" engine to
**real Claude vision**, so the Telegram bot can read a chart/signal screenshot and
extract the SL/TP levels for a human to confirm.

**Important:** the code is already finished and tested. This is a **configuration +
verification** job, not a coding job. The only real change is giving the backend a
funded Anthropic API key and restarting it. Do **not** rewrite the extractor.

---

## What the human must provide (ask for these first)

The agent cannot create accounts or add billing. Before starting, get from the operator:

1. **An Anthropic API key with credit on the account.** ("Ran out of credits" was the
   original blocker — a valid key with a £0 balance still fails.) Key looks like `sk-ant-…`.
2. **Access to the machine that runs the backend** (the VPS, or the local machine) —
   SSH or a terminal on that host.
3. **The Telegram user id** of the person who will send screenshots (the "signal provider").

⚠️ **Handle the key like a password.** Put it only in the server's environment. Never
paste it into chat, never write it into a file that gets committed to git, never print
it in logs. If you ever `echo` it, clear your scrollback afterwards.

---

## Step 1 — Find where the backend runs and how it's configured

On the backend host, identify the deployment style (do all three checks):

```bash
# a) Is it a systemd service?
systemctl list-units --type=service 2>/dev/null | grep -i signal

# b) Is it Docker / compose?
docker ps 2>/dev/null | grep -i signal

# c) Where is the repo + its .env?
ls -la /path/to/SignalGate/.env 2>/dev/null || find / -name '.env' -path '*SignalGate*' 2>/dev/null | head
```

Note which one is in use — you'll set env and restart using that mechanism.
The backend is the FastAPI app `backend/app/main.py` (usually run with
`uvicorn app.main:app`).

---

## Step 2 — Set the environment variables

Add/point these in the backend's environment (its `.env` file, the systemd unit's
`Environment=`/`EnvironmentFile=`, or the compose `environment:` block):

```env
SIGNAL_EXTRACTOR=claude
ANTHROPIC_API_KEY=sk-ant-...the real key...
SIGNAL_EXTRACTOR_MODEL=claude-opus-4-8        # optional; this is already the default
SIGNAL_PROVIDER_TELEGRAM_IDS=<provider telegram id>   # or put the id in ADMIN_TELEGRAM_IDS
```

- `SIGNAL_EXTRACTOR=claude` turns on the real reader (default auto-picks "fake" when no key).
- `SIGNAL_PROVIDER_TELEGRAM_IDS` must include whoever sends screenshots, or the bot
  replies *"Only the signal provider can submit screenshots."*

Confirm the `.env` is **git-ignored** before saving the key into it:

```bash
cd /path/to/SignalGate && git check-ignore .env && echo "OK: .env is ignored"
```

If that prints nothing (i.e. `.env` is NOT ignored), do not put the key there — use the
service manager's env mechanism instead, or add `.env` to `.gitignore` first.

---

## Step 3 — Install dependencies

The vision path needs the `anthropic` SDK and `Pillow` (both already listed in
`backend/requirements.txt`):

```bash
cd /path/to/SignalGate/backend
source .venv/bin/activate 2>/dev/null || python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -c "import anthropic, PIL; print('deps OK', anthropic.__version__, PIL.__version__)"
```

Expected: `deps OK <version> <version>`.

---

## Step 4 — Restart the backend

Use whichever matches Step 1:

```bash
sudo systemctl restart signalgate-backend      # systemd
# or
docker compose up -d --force-recreate backend  # docker compose
# or (manual) stop the old uvicorn and start it again so it re-reads the env
```

Then confirm it's alive:

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","demo_only_mode":true,"admin_paused":false}
```

(Adjust the port if the deployment uses a different one.)

---

## Step 5 — Verify the API key actually works

Run this on the backend host, in the activated venv:

```bash
python -c "import anthropic; anthropic.Anthropic().messages.create(model='claude-opus-4-8', max_tokens=10, messages=[{'role':'user','content':'ping'}]); print('KEY OK')"
```

Interpret the result:

| Output | Meaning | Fix |
|---|---|---|
| `KEY OK` | Key valid and funded | Proceed to Step 6 |
| `authentication_error` / 401 | Wrong or mistyped key | Re-copy the key from console.anthropic.com |
| `credit balance is too low` / billing / 400 | Valid key, no credit | Add credit/billing on the Anthropic account |
| `Connection`/timeout | Host can't reach api.anthropic.com | Check the server's outbound network/firewall |

Do not continue until this prints `KEY OK`.

---

## Step 6 — End-to-end test WITHOUT Telegram (fast, deterministic)

This proves the live server reads an image and returns parser-validated levels.
Run from the backend host (replace the port/provider-id if different):

```bash
# make a tiny test screenshot
python - <<'PY'
from PIL import Image, ImageDraw
im=Image.new("RGB",(1000,640),(14,18,22)); d=ImageDraw.Draw(im)
for i,l in enumerate(["XAUUSD BUY","Entry: Market","SL: 2343","TP1: 2353","TP2: 2358","TP3: 2363"]):
    d.text((40,40+i*80), l, fill=(235,235,235))
im.save("/tmp/sg_test_chart.png"); print("wrote /tmp/sg_test_chart.png")
PY

# upload it exactly like the bot does (use the provider's telegram id in the header)
curl -s -H "X-Admin-Id:<provider telegram id>" \
     -F "file=@/tmp/sg_test_chart.png;type=image/png" \
     http://127.0.0.1:8000/signals/extract
```

Expected: JSON with `"engine":"claude"`, `"readable":true`, and the read levels
(`symbol`, `direction`, `initial_stop_loss`, `tp1`…). If `readable` is `false`, read the
`notes` field — it contains the exact reason (see troubleshooting).

> Note: this is a hand-drawn text image, so any modern read should get it. Real accuracy
> on **annotated charts** is what matters — test those in Step 7 with genuine screenshots.

---

## Step 7 — End-to-end test IN Telegram (the real thing)

1. Make sure the Telegram bot is running (`telegram_bot/run_bot.py`, with
   `TELEGRAM_BOT_TOKEN` set and pointed at the backend's `BACKEND_BASE_URL`).
2. From the **provider's** Telegram account, send a chart screenshot to the bot.
   - Send it as a **File** (📎 → File), *not* a photo — Telegram compresses photos and
     blurs the tiny price-scale digits, which is the #1 cause of misread levels.
3. The bot replies with a preview: the symbol, direction, SL and each TP it read, plus a
   confidence and a "Price scale read: …" note.
4. Check the numbers against the chart. Tap **Confirm & Send** to broadcast, **Edit** to
   correct by typing the signal, or **Cancel**.
5. Confirm should produce a trade card broadcast to registered testers.

---

## Troubleshooting — the bot tells you the exact error

The extractor puts the real failure reason straight into the preview's **notes** line in
the chat, so you rarely have to guess:

| What the bot/notes says | Cause | Fix |
|---|---|---|
| "Only the signal provider can submit screenshots." | Sender not in provider ids | Add their id to `SIGNAL_PROVIDER_TELEGRAM_IDS`, restart |
| `Vision API error 401` | Bad key | Re-check `ANTHROPIC_API_KEY` |
| `credit balance is too low` (400) | No credit | Add billing on the Anthropic account |
| `ANTHROPIC_API_KEY not set on the server` | Env not loaded | Key not in the backend's env, or backend not restarted |
| engine shows `fake` | Still on the offline reader | `SIGNAL_EXTRACTOR=claude` not set, or backend not restarted |
| Levels misread on a chart | Photo compression | Resend as a **File**; the built-in upscaling + axis crop then have full-res digits |

To watch what the backend recorded for each read:

```bash
# every extraction writes an audit row (engine, readable, confidence, parser_status)
# check the DB or the backend logs for SIGNAL_IMAGE_EXTRACTED events
journalctl -u signalgate-backend -n 50 --no-pager   # systemd
# or: docker compose logs --tail=50 backend
```

---

## Safety / guardrails (do not change these)

- Vision only ever produces the **one-line signal text a human would type**; the
  deterministic parser (`backend/app/parser.py`) remains the sole authority on validity
  (SL on the correct side, TP ordering). Vision never bypasses it.
- The bot **always** shows the extracted numbers for the provider to confirm before
  anything is broadcast. Nothing auto-sends from an image.
- Demo-only stays on. Do not add live trading as part of this task.

---

## Rollback

If anything goes wrong and you need the bot working offline again immediately, set:

```env
SIGNAL_EXTRACTOR=fake
```
and restart. The bot then returns a canned valid signal for the preview flow (clearly
labelled "no real OCR performed") — useful for demos, not for real charts.

---

## Definition of done

- `KEY OK` from Step 5.
- Step 6 returns `"engine":"claude"`, `"readable":true` with correct levels.
- In Telegram, a real chart screenshot (sent as a File) produces a preview whose SL/TP
  match the chart, and **Confirm** broadcasts a trade card.
- The key lives only in the server env and is not in any committed file.
