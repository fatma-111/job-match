# Official Playwright image: ships Chromium/Firefox/WebKit and every OS-level
# dependency already installed and version-matched — avoids the apt/OS
# compatibility failures that "python:3.12-slim + playwright install --with-deps"
# hits on newer Debian base images Playwright hasn't added support for yet.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# The base image ships Python 3.12 already; curl is needed by the entrypoint's
# backend-health check loop.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

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

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

CMD ["/app/docker-entrypoint.sh"]
