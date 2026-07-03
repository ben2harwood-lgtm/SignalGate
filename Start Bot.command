#!/bin/bash
# SignalGate — Start Telegram Bot (double-click to run). DEMO ONLY.
cd "$(dirname "$0")/telegram_bot"

source .venv/bin/activate 2>/dev/null
if ! python -c "import telegram" >/dev/null 2>&1; then
  echo "First-time setup (this takes a minute)..."
  rm -rf .venv
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
fi

echo ""
echo "SignalGate Telegram bot is running. Keep this window OPEN. Close it to stop."
echo "Now message your bot on Telegram: /start  then  /status"
python run_bot.py
