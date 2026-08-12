#!/usr/bin/env bash
# Runs the FastAPI backend and the Streamlit frontend in one container.
# Streamlit is the public-facing process (Railway/Render only expose $PORT);
# it talks to the backend over localhost.
set -euo pipefail

BACKEND_PORT="${PORT_BACKEND:-8000}"
FRONTEND_PORT="${PORT:-8501}"

export BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"

echo "Starting FastAPI backend on :${BACKEND_PORT}"
uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

# Wait for the backend to answer /health before starting Streamlit.
echo "Waiting for backend to become healthy..."
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" > /dev/null 2>&1; then
    echo "Backend is healthy."
    break
  fi
  sleep 1
done

echo "Starting Streamlit frontend on :${FRONTEND_PORT}"
streamlit run streamlit_app.py \
  --server.port "${FRONTEND_PORT}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false &
FRONTEND_PID=$!

# If either process dies, bring the container down so the platform restarts it.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
