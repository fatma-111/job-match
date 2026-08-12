FROM python:3.12-slim

# System deps for Playwright/Chromium + build tools for a couple of wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates curl \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
    libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 \
    libxrandr2 xdg-utils libu2f-udev libvulkan1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install only the Chromium browser (not the full Playwright test suite).
RUN python -m playwright install --with-deps chromium

COPY . .
RUN mkdir -p data

ENV PYTHONUNBUFFERED=1 \
    BACKEND_URL=http://localhost:8000 \
    PORT=8000 \
    STREAMLIT_PORT=8501

EXPOSE 8000 8501

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

CMD ["/app/docker-entrypoint.sh"]
