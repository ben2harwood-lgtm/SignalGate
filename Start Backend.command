#!/bin/bash
# SignalGate — Start Backend (double-click to run). DEMO ONLY.
cd "$(dirname "$0")"

# First run: create .env from the template and let the user fill it in.
if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo "Created a .env file. Opening it now."
  echo "Paste your Telegram bot token and your admin id, SAVE, then double-click this again."
  open -e ".env"
  read -p "Press Return to close this window..."
  exit 0
fi

cd backend
source .venv/bin/activate 2>/dev/null
if ! command -v uvicorn >/dev/null 2>&1; then
  echo "First-time setup (this takes a minute or two)..."
  rm -rf .venv
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  python ../scripts/init_db.py
else
  # Ensure newly-added dependencies are installed (fast if already present).
  pip install -q -r requirements.txt
fi

echo ""
echo "SignalGate backend is running. Keep this window OPEN. Close it to stop."
echo "Health check: http://127.0.0.1:8000/health"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
