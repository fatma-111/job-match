"""Starts the FastAPI backend and Streamlit frontend together.

Python instead of a shell script on purpose: launching via `python entrypoint.py`
means the OS execs the (unambiguous, always-correctly-formatted) python binary,
not this file — so Windows line endings, missing +x bits, or shebang quirks
in this file can never cause an "exec format error" again.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request


def watch_backend_health(port: str) -> None:
    """Purely informational — logs when the backend becomes reachable.
    Never blocks or delays the frontend from binding its port."""
    url = f"http://127.0.0.1:{port}/health"
    for _ in range(90):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    print("Backend is healthy.", flush=True)
                    return
        except Exception:  # noqa: BLE001 - not up yet, keep polling
            pass
        time.sleep(2)
    print(
        "Backend still not healthy after 3 minutes — check the logs above for the real error.",
        flush=True,
    )


def main() -> None:
    backend_port = os.environ.get("PORT_BACKEND", "8000")
    frontend_port = os.environ.get("PORT", "8501")

    # Railway/Render assign $PORT dynamically for the public-facing process.
    # If it collides with the backend's port, move the backend instead of
    # letting two processes fight over the same bind.
    if backend_port == frontend_port:
        backend_port = str(int(frontend_port) + 1)
        print(f"PORT collision detected — moving backend to :{backend_port}", flush=True)

    os.environ["BACKEND_URL"] = f"http://127.0.0.1:{backend_port}"

    print(f"Starting FastAPI backend on :{backend_port}", flush=True)
    backend = subprocess.Popen(
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", backend_port]
    )

    # Streamlit binds its port immediately regardless of backend readiness —
    # this is what makes the platform healthcheck (which hits this port) pass
    # quickly. The UI already handles "backend not reachable yet" gracefully.
    print(f"Starting Streamlit frontend on :{frontend_port}", flush=True)
    frontend = subprocess.Popen(
        [
            "streamlit", "run", "streamlit_app.py",
            "--server.port", frontend_port,
            "--server.address", "0.0.0.0",
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ]
    )

    threading.Thread(target=watch_backend_health, args=(backend_port,), daemon=True).start()

    # If either process dies, bring the whole container down so the platform
    # restarts it, instead of running half-broken forever.
    try:
        while True:
            if backend.poll() is not None:
                print(f"Backend exited with code {backend.returncode}.", flush=True)
                frontend.terminate()
                sys.exit(backend.returncode or 1)
            if frontend.poll() is not None:
                print(f"Frontend exited with code {frontend.returncode}.", flush=True)
                backend.terminate()
                sys.exit(frontend.returncode or 1)
            time.sleep(1)
    except KeyboardInterrupt:
        backend.terminate()
        frontend.terminate()


if __name__ == "__main__":
    main()
