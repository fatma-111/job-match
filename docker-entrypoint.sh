#!/usr/bin/env bash
# Runs the FastAPI backend and the Streamlit frontend in one container.
# Streamlit is the public-facing process (Railway/Render only expose $PORT)
# and MUST bind that port immediately so the platform healthcheck passes —
# it talks to the backend over localhost and degrades gracefully in the UI
# if the backend isn't ready yet, so we never gate Streamlit's startup on it.
set -euo pipefail

BACKEND_PORT="${PORT_BACKEND:-8000}"
FRONTEND_PORT="${PORT:-8501}"

# Railway/Render assign $PORT dynamically for the public-facing process.
# If it happens to collide with the backend's port, bump the backend instead
# of letting two processes fight over the same bind.
if [ "${BACKEND_PORT}" = "${FRONTEND_PORT}" ]; then
  BACKEND_PORT=$((FRONTEND_PORT + 1))
  echo "PORT collision detected — moving backend to :${BACKEND_PORT}"
fi

export BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"

echo "Starting FastAPI backend on :${BACKEND_PORT}"
uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

echo "Starting Streamlit frontend on :${FRONTEND_PORT} (binds immediately for the platform healthcheck)"
streamlit run streamlit_app.py \
  --server.port "${FRONTEND_PORT}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false &
FRONTEND_PID=$!

# Log backend readiness in the background purely for visibility — this must
# never block Streamlit's port from being bound.
(
  for _ in $(seq 1 90); do
    if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" > /dev/null 2>&1; then
      echo "Backend is healthy."
      exit 0
    fi
    sleep 2
  done
  echo "Backend still not healthy after 3 minutes — check 'railway logs' for the real error."
) &

# If either main process dies, bring the container down so the platform restarts it.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
