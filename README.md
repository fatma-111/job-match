# Job Matching Agent

An AI agent that takes your CV, searches Wuzzuf, Bayt, Tanqeeb, Indeed and
LinkedIn in parallel, ranks results by embedding similarity to your CV, and
gives you cover letters, mock interview prep, skill-gap analysis, an
application tracker, job alerts, and a career-coach chatbot.

Built to the spec in `full-project-plan.md`: FastAPI + LangGraph + OpenRouter
(free models) + Playwright + sentence-transformers + SQLAlchemy/SQLite +
Streamlit + APScheduler.

## Run it in 3 commands

```bash
git clone <this-repo>
cd job-agent
./run_local.sh
```

That script creates a venv, installs everything (including Chromium for
Playwright), copies `.env.example` → `.env`, and starts both services:

- API + docs: http://localhost:8000/docs
- UI: http://localhost:8501

On first run it'll start with the LLM features degraded (heuristic CV parsing,
no cover letters/interview prep/career chat) until you add an OpenRouter key —
see **Configuration** below. Job search, matching, ranking, skill gap and the
application tracker all work with zero configuration.

## Configuration

Edit `.env` (created from `.env.example`):

| Variable | Required for | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | Cover letters, mock interviews, career chat, LLM-enhanced CV/skill-gap parsing | Free key at https://openrouter.ai/keys. Everything else works without it. |
| `SMTP_HOST` / `SMTP_FROM_EMAIL` / `SMTP_USERNAME` / `SMTP_PASSWORD` | Job Alerts email delivery | Any SMTP provider (Gmail app password, SendGrid, Resend SMTP, etc). |
| `SCRAPER_PROXY` | Reducing scraper blocking | `http://user:pass@host:port`. Optional. |
| `DATABASE_URL` | — | Defaults to SQLite. Swap for Postgres by changing the connection string only. |

## Deploying

### Docker (any host: Railway, Render, Fly, a VPS)

```bash
docker compose up --build
```

Or build/run the image directly — it serves the API on the port in `PORT_BACKEND`
(default 8000) and the UI on `PORT` (default 8501), both from one container:

```bash
docker build -t job-agent .
docker run -p 8000:8000 -p 8501:8501 --env-file .env job-agent
```

### Railway

1. `railway init` in this folder (uses `railway.json`, which points at the Dockerfile).
2. `railway variables set OPENROUTER_API_KEY=... SMTP_HOST=... SMTP_FROM_EMAIL=...`
3. `railway up`
4. Railway exposes one public port — it maps to Streamlit (see
   `docker-entrypoint.sh`), which talks to the backend over `localhost`.

### Render

1. Push this repo, then "New Web Service" → pick this repo → Render detects
   `render.yaml` and the Dockerfile automatically.
2. Fill in the env vars flagged `sync: false` in the Render dashboard.
3. **Use at least the Standard plan** — the free tier's 512MB RAM is tight
   once Chromium and the embedding model are both loaded.

### Streamlit Community Cloud (frontend only)

Streamlit Cloud can't run Playwright/Chromium, so deploy the FastAPI backend
separately (Railway/Render/a VPS) and point Streamlit Cloud's `BACKEND_URL`
secret at that backend's public URL. Only `streamlit_app.py` and
`requirements.txt` are needed on the Streamlit Cloud side.

## What's implemented vs. what needs your attention

✅ Done and tested (87 automated tests — see below):
- CV upload/parsing (PDF, DOCX, TXT), LLM extraction with a no-key fallback
- LangGraph fan-out/fan-in search across 5 sources, each fully isolated
- Date/salary normalization (English + Arabic), dedup by canonical URL
- Embedding-based ranking with matching/missing skills and an explanation
- Skill Gap Analyzer (single job + frequency-counted aggregate)
- Application tracker with full status history
- Job Alerts: APScheduler + URL-hash diffing + HTML email
- Career Agent: 5 tools, native tool-calling with a context-injection fallback
  for models that don't support it, persistent chat history
- All 18 API endpoints, `/health`, full Streamlit UI (6 tabs)

⚠️ Needs your attention before relying on scraping:
- **Selectors are unverified against live HTML.** Wuzzuf, Bayt, Tanqeeb,
  Indeed and LinkedIn all change their markup periodically. Run one scraper
  standalone first (see below), inspect the page, and update
  `app/scrapers/selectors.json` (copy from `.example`) if cards return empty.
- **Indeed and LinkedIn run aggressive bot detection.** The scraper detects
  the block and reports it as a source error rather than trying to bypass
  it — by design, not a bug. A rotating residential proxy (`SCRAPER_PROXY`)
  helps but isn't guaranteed, and this environment's own network policy
  blocked all five sites during development, so scraping was verified for
  correct *failure handling*, not against live pages.
- SQLite is fine for personal use; see §11 of the plan for the Postgres/Celery
  migration path once you outgrow it.

## Testing one scraper standalone

```python
import asyncio
from app.scrapers.base import BrowserSession
from app.scrapers.wuzzuf import WuzzufScraper

async def main():
    async with BrowserSession() as session:
        jobs = await WuzzufScraper(session).search("python developer", "Cairo", limit=5)
        for j in jobs:
            print(j.title, "|", j.company, "|", j.url)

asyncio.run(main())
```

If it returns nothing, open the URL it built (print `scraper.build_url(...)`)
in a real browser, inspect a job card, and update `selectors.json`.

## Running the tests

```bash
pip install -r requirements.txt
pytest -q
```

87 tests: CV parsing (PDF/DOCX), extraction, embeddings/ranking, date & salary
normalization, dedup, the full LangGraph pipeline including a simulated
partial-scraper-failure scenario, every scraper's URL/selector contract, the
application lifecycle with timeline, alert diffing + email rendering, and
every API endpoint (including graceful degradation when no LLM key is set).

## Project layout

See `full-project-plan.md` §5 — the implemented structure matches it, plus
`app/db.py`, `app/models_db.py`, `app/crud.py`, `app/services/normalize.py`,
`app/services/career_agent.py`, `app/services/notifications.py`, and
`app/scrapers/registry.py`.
