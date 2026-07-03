@echo off
REM SignalGate - Start Backend (double-click to run). DEMO ONLY.
cd /d "%~dp0"

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created a .env file. Opening it now.
  echo Paste your Telegram bot token and your admin id, SAVE, then run this again.
  notepad ".env"
  pause
  exit /b
)

cd backend
if not exist ".venv\Scripts\uvicorn.exe" (
  echo First-time setup, please wait a minute or two...
  rmdir /s /q .venv 2>nul
  python -m venv .venv
  call .venv\Scripts\activate
  pip install -r requirements.txt
  python ..\scripts\init_db.py
) else (
  call .venv\Scripts\activate
  REM Ensure newly-added dependencies are installed (fast if already present).
  pip install -q -r requirements.txt
)

echo.
echo SignalGate backend is running. Keep this window OPEN. Close it to stop.
echo Health check: http://127.0.0.1:8000/health
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
