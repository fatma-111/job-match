"""APScheduler job-alert runner.

Every ALERT_INTERVAL_HOURS: for each active subscription run the saved search,
diff against seen_jobs by URL hash, persist new jobs and email them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import crud
from app.config import settings
from app.db import session_scope
from app.schemas import Job, SearchFilters
from app.services.notifications import EmailNotConfigured, send_job_alert_email

logger = logging.getLogger(__name__)

scheduler: Optional[AsyncIOScheduler] = None


async def run_search_and_diff(alert_id: str) -> Dict[str, Any]:
    """Run one subscription's search and return the newly-seen jobs."""
    from app.agents.graph import run_job_search

    with session_scope() as db:
        alert = crud.get_alert(db, alert_id)
        if alert is None:
            return {"error": "alert not found", "new_jobs": []}
        cv = crud.get_cv(db, alert.cv_id)
        if cv is None:
            return {"error": "cv not found", "new_jobs": []}
        # Read every attribute we need *inside* the session — the ORM objects
        # become detached as soon as the context manager exits.
        profile = crud.cv_to_profile(cv)
        cv_text = cv.raw_text
        cv_key = cv.id
        alert_name = alert.name
        destination = alert.destination
        try:
            filters = SearchFilters(**crud._loads(alert.filters_json, {}))
        except Exception:  # noqa: BLE001
            filters = SearchFilters()

    result = await run_job_search(profile, filters, cv_text=cv_text, cv_id=cv_key)
    jobs: List[Job] = result.get("jobs") or []
    errors = result.get("errors") or []

    with session_scope() as db:
        alert = crud.get_alert(db, alert_id)
        if alert is None:
            return {"error": "alert deleted mid-run", "new_jobs": []}
        new_jobs = crud.filter_unseen_jobs(db, alert_id, jobs)
        crud.mark_jobs_seen(db, alert_id, new_jobs)
        alert.last_run_at = datetime.now(timezone.utc)
        alert.last_error = "; ".join(f"{e.source}: {e.error_type}" for e in errors)[:500]
        db.commit()

    return {
        "alert_name": alert_name,
        "destination": destination,
        "new_jobs": new_jobs,
        "total_found": len(jobs),
        "errors": errors,
    }


async def run_alert(alert_id: str, send_email: bool = True) -> Dict[str, Any]:
    outcome = await run_search_and_diff(alert_id)
    new_jobs = outcome.get("new_jobs") or []
    outcome["emailed"] = False
    if new_jobs and send_email and outcome.get("destination"):
        try:
            await send_job_alert_email(
                outcome["destination"], outcome.get("alert_name", "Job alert"), new_jobs
            )
            outcome["emailed"] = True
        except EmailNotConfigured as exc:
            logger.warning("Alert %s: %s", alert_id, exc)
            outcome["email_error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("Alert %s email failed: %s", alert_id, exc)
            outcome["email_error"] = str(exc)[:300]
    return outcome


async def run_all_alerts() -> Dict[str, Any]:
    """Scheduled entry point — never raises, so the scheduler keeps running."""
    logger.info("Running scheduled job alerts")
    summary: Dict[str, Any] = {"ran": 0, "emailed": 0, "failed": 0}
    try:
        with session_scope() as db:
            alert_ids = [a.id for a in crud.list_active_alerts(db)]
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not load alerts: %s", exc)
        return summary

    for alert_id in alert_ids:
        try:
            outcome = await run_alert(alert_id)
            summary["ran"] += 1
            if outcome.get("emailed"):
                summary["emailed"] += 1
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            logger.exception("Alert %s failed: %s", alert_id, exc)
    logger.info("Alert run finished: %s", summary)
    return summary


def start_scheduler() -> Optional[AsyncIOScheduler]:
    global scheduler
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled by config")
        return None
    if scheduler and scheduler.running:
        return scheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_all_alerts,
        "interval",
        hours=settings.alert_interval_hours,
        id="run_all_alerts",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Scheduler started (every %sh)", settings.alert_interval_hours)
    return scheduler


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    scheduler = None


def scheduler_status() -> str:
    if not settings.scheduler_enabled:
        return "disabled"
    if scheduler and scheduler.running:
        return f"running (every {settings.alert_interval_hours}h)"
    return "stopped"
