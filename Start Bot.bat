@echo off
REM SignalGate - Start Telegram Bot (double-click to run). DEMO ONLY.
cd /d "%~dp0telegram_bot"

if not exist ".venv\Scripts\python.exe" (
  echo First-time setup, please wait a minute...
  python -m venv .venv
  call .venv\Scripts\activate
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate
)

echo.
echo SignalGate Telegram bot is running. Keep this window OPEN. Close it to stop.
echo Now message your bot on Telegram: /start  then  /status
python run_bot.py
