# Ben Next Stage Checklist

Use this to make Nick's setup as close to frictionless as possible.

## 1. Choose Nick's invite code

Edit `.env`:

```env
SIGNAL_PROVIDER_INVITE_CODE=choose-a-simple-private-code
```

Example:

```env
SIGNAL_PROVIDER_INVITE_CODE=nick-signal-2026
```

Do not put the code in the repo or the shared zip.

## 2. Enable real screenshot reading

For real screenshots, `.env` must use Claude extraction:

```env
SIGNAL_EXTRACTOR=claude
ANTHROPIC_API_KEY=your_real_anthropic_key
```

Use `SIGNAL_EXTRACTOR=fake` only to test the plumbing. Fake mode always returns
the canned XAUUSD example and does not read the actual screenshot.

## 3. Restart services

Restart the backend and bot after changing `.env`.

Backend:

```bash
cd /Users/benharwood/Desktop/signalgate/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Bot:

```bash
cd /Users/benharwood/Desktop/signalgate/telegram_bot
source .venv/bin/activate
python run_bot.py
```

## 4. Send Nick the short message

Copy the text from:

```text
docs/MESSAGE_TO_NICK.md
```

Replace `THE_CODE_I_GIVE_YOU` with the invite code.

## 5. What success looks like

Nick sends:

```text
/provider your-code
/start
```

Then he sends a screenshot.

Expected bot flow:

```text
Reading your screenshot...
Read from your screenshot:
Symbol: XAUUSD
Direction: BUY/SELL
SL: ...
TP1: ...
[Confirm & Send] [Edit] [Cancel]
```

If Nick taps Confirm, the bot replies:

```text
Signal SIG-... created and card sent to N tester(s).
```

That is the handoff point. Testers still need to tap YES before the EA/simulator
gets a command.
