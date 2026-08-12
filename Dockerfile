# Official Playwright image: ships Chromium/Firefox/WebKit and every OS-level
# dependency already installed and version-matched — avoids the apt/OS
# compatibility failures that "python:3.12-slim + playwright install --with-deps"
# hits on newer Debian base images Playwright hasn't added support for yet.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium is already in the base image for this exact Playwright version;
# this is just a safety net in case the pinned pip version drifts.
RUN python -m playwright install chromium

COPY . .
RUN mkdir -p data

# Bake the embedding model into the image at build time (not on the request
# path) so the first search after a deploy doesn't stall on a download.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" || \
    echo "WARNING: could not pre-download embedding model at build time — it will download on first use instead."

ENV PYTHONUNBUFFERED=1 \
    BACKEND_URL=http://localhost:8000 \
    PORT=8000 \
    STREAMLIT_PORT=8501

EXPOSE 8000 8501

# Python entrypoint on purpose (not a shell script): `python entrypoint.py`
# execs the unambiguous, always-correctly-formatted python binary, so this
# file's own line endings/shebang/permission bits can never cause an
# "exec format error" — the class of bug a bash entrypoint is exposed to.
CMD ["python", "/app/entrypoint.py"]
