# Message to Send Nick

Hey Nick — your only job is the screenshot flow:

1. Open the SignalGate Telegram bot.
2. Send this command:
   `/provider THE_CODE_I_GIVE_YOU`
3. Then send `/start`.
4. It should say `SignalGate screenshot provider ready.`
5. Send the bot one clear signal screenshot.
6. The bot will read it and show Symbol / BUY or SELL / Entry / SL / TP1 / TP2 / TP3.
7. Check every number.
8. If it is correct, tap **Confirm & Send**.
9. If anything is wrong, tap **Edit** and type the corrected signal, for example:

```text
XAUUSD BUY SL 2343 TP1 2353 TP2 2358 TP3 2363
```

10. If the screenshot is bad, tap **Cancel**.

Important: do not confirm unless the numbers are right. Confirming sends the demo trade card to the testers, but they still have to tap YES before any demo command is created.

Send me this after you test:

```text
/status role says screenshot provider: yes/no
Screenshot gave extracted preview: yes/no
Confirm & Send worked: yes/no
Edit worked if needed: yes/no
Cancel worked if tested: yes/no
Exact error if any:
```
