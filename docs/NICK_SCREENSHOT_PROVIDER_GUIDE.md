# SignalGate Screenshot Provider Guide for Nick

Your job is only this:

1. Send a signal screenshot to the Telegram bot.
2. Check what the bot extracted.
3. Confirm, edit, or cancel.
4. If you confirm, the bot sends the demo trade card to the registered testers.

You do not need admin access. You do not need to run MetaTrader. You do not need
to run the simulator. You are only the screenshot-to-signal gatekeeper.

## What Ben Must Set Up First

Ben either gives you a provider invite command:

```text
/provider some-private-code
```

or adds your numeric Telegram id to `.env`:

```env
SIGNAL_PROVIDER_TELEGRAM_IDS=your_numeric_telegram_id
```

Do not put your id in `ADMIN_TELEGRAM_IDS` unless Ben wants you to have admin
controls like pause, resume, and logs.

The backend also needs real screenshot extraction enabled:

```env
SIGNAL_EXTRACTOR=claude
ANTHROPIC_API_KEY=sk-ant-...
```

After changing `.env`, Ben must restart both:

- the backend
- the Telegram bot

## Getting Access

The easiest way is the invite code.

1. Open the SignalGate bot in Telegram.
2. Send:
   ```text
   /provider THE_CODE_BEN_GAVE_YOU
   ```
3. The bot should reply that you are a screenshot provider.
4. Send `/start`.

If your access is set correctly, the bot should say:

```text
SignalGate screenshot provider ready.
```

If Ben did not give you an invite code, send `/status` and send him the numeric
Telegram id it shows. He can add that id manually.

## Your Normal Workflow

### 1. Check status

Send:

```text
/status
```

You want to see:

```text
Role: screenshot provider
Backend reachable: yes
Demo only mode: true
Admin paused: false
```

If the role says `tester`, Ben has not added your id to
`SIGNAL_PROVIDER_TELEGRAM_IDS` yet.

### 2. Send the screenshot

Send one screenshot to the bot.

**Send it as a File, not a photo.** In Telegram tap the 📎 attachment icon and
choose **File**, then pick the screenshot. A normal "photo" upload gets
compressed by Telegram and the small price numbers on the chart's right-hand
scale become blurry — that is the #1 cause of misread levels. A File keeps the
full resolution. (The reader also zooms into the price scale automatically,
but starting from a sharp image is always better.)

Best screenshot format:

- Symbol visible, for example `EURUSD`, `GBPJPY`, or `XAUUSD`.
- Direction visible, for example `BUY`, `SELL`, `LONG`, or `SHORT`.
- Stop loss visible as text, for example `SL 1.0850`.
- At least TP1 visible as text, for example `TP1 1.0950`.
- TP2 and TP3 visible if the signal has them.
- The right-hand price scale unobstructed (no watermark/panel covering it).
- Avoid blurry/cropped screenshots.

Important: the reader is told not to invent numbers from chart-line positions.
If a level does not have a written price label, it may reject or ask for an edit.
The preview's notes now include a "Price scale read:" list showing every number
the reader saw on the axis — glance at it to check nothing was misread.

### 3. Review the extracted preview

The bot replies with something like:

```text
Read from your screenshot:

"XAUUSD BUY ENTRY 2348 SL 2343 TP1 2353 TP2 2358 TP3 2363"

Symbol: XAUUSD
Direction: BUY
Entry: Market
SL: 2343.00
TP1: 2353.00
TP2: 2358.00
TP3: 2363.00

Reader confidence: HIGH

Passes safety checks. Confirm to send to testers, or Edit to fix.
```

Read every number. Do not skim.

### 4. Choose one button

Tap **Confirm & Send** only when every field is correct.

Expected result:

```text
Signal SIG-... created and card sent to N tester(s).
```

That means the trade card has gone out to the registered testers. They still
must tap YES before any demo command is created.

Tap **Edit** if any value is wrong.

The bot will ask you to type the corrected signal manually, for example:

```text
XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363
```

After you send the corrected text, the bot runs the normal parser and sends the
trade card only if the corrected signal is valid.

Tap **Cancel** if the screenshot is not usable.

Expected result:

```text
Cancelled. Nothing was sent.
```

## What Happens After You Confirm

After confirmation:

1. Backend creates a validated signal.
2. The bot sends the trade card to active testers.
3. A tester taps YES or NO.
4. YES creates exactly one backend command.
5. The simulator or MT5 demo EA receives the command.
6. Execution and management events are logged.

You do not need to manage those later steps unless Ben asks you to watch them.

## What You Should Not Have Access To

As a screenshot provider, you should not be able to use:

```text
/pause
/resume
/users
/lastsignals
/lastcommands
/testsignal
```

Those are admin controls. If one of them works for you, tell Ben your id is in
the wrong env variable.

## Quick Test Checklist

Send this back to Ben after testing:

```text
/start says screenshot provider ready: yes/no
/status says Role: screenshot provider: yes/no
Screenshot upload returns extracted preview: yes/no
Confirm & Send creates Signal SIG-...: yes/no
Card sent to tester count is above 0: yes/no
Edit flow works if extraction is wrong: yes/no
Cancel says nothing was sent: yes/no
Any exact error message:
```

## Common Problems

### The bot says "Only the signal provider can submit screenshots"

Use the provider invite code Ben gave you:

```text
/provider THE_CODE
```

If that does not work, Ben needs to add your numeric Telegram id to:

```env
SIGNAL_PROVIDER_TELEGRAM_IDS=
```

Then restart backend and bot.

### The bot cannot read the screenshot

- Resend it **as a File** (📎 → File) instead of a photo — compression is the
  usual culprit.
- Try a cleaner screenshot. Make sure the price numbers are written on the
  image, not only implied by chart lines.
- Check the right-hand price scale isn't covered by a watermark or panel.

### The preview is wrong

Tap **Edit** and type the corrected signal. Do not confirm a wrong extraction.

### Confirm says parser rejected

The extracted or edited text failed safety checks. Common causes:

- Missing SL.
- Missing TP1.
- BUY signal has SL above TP.
- SELL signal has SL below TP.
- TP order is impossible.

Use Edit and type the corrected signal, or Cancel.
