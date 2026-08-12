#!/usr/bin/env bash
# One-command local run: creates a venv, installs deps, installs Chromium,
# and starts both the API and the UI.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  python3 -m venv venv
fi
source venv/bin/activate

pip install --upgrade pip -q
pip install -r requirements.txt
playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your OPENROUTER_API_KEY / SMTP settings, then re-run."
fi

mkdir -p data

echo "Starting FastAPI on http://localhost:8000 (docs at /docs)"
uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

sleep 3
echo "Starting Streamlit on http://localhost:8501"
BACKEND_URL=http://localhost:8000 streamlit run streamlit_app.py
