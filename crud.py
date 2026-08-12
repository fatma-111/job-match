"""Database access helpers shared by the API, scheduler and career agent."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_db import (
    AlertSubscription,
    Application,
    ApplicationEvent,
    ApplicationStatus,
    CV,
    CareerChatMessage,
    CareerChatSession,
    SearchResultCache,
    SeenJob,
    SkillGapReport,
)
from app.schemas import CVProfile, Job


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (json.JSONDecodeError, TypeError):
        return default


# --------------------------------------------------------------------------
# CVs
# --------------------------------------------------------------------------
def create_cv(
    db: Session, raw_text: str, profile: CVProfile, filename: str, parse_method: str
) -> CV:
    cv = CV(
        filename=filename,
        raw_text=raw_text,
        skills_json=json.dumps(profile.skills, ensure_ascii=False),
        job_titles_json=json.dumps(profile.job_titles, ensure_ascii=False),
        experience_json=json.dumps(profile.experience, ensure_ascii=False),
        education_json=json.dumps(profile.education, ensure_ascii=False),
        technologies_json=json.dumps(profile.technologies, ensure_ascii=False),
        certifications_json=json.dumps(profile.certifications, ensure_ascii=False),
        years_experience=profile.years_experience,
        summary=profile.summary,
        parse_method=parse_method,
    )
    db.add(cv)
    db.commit()
    db.refresh(cv)
    return cv


def get_cv(db: Session, cv_id: str) -> Optional[CV]:
    return db.get(CV, cv_id)


def list_cvs(db: Session, limit: int = 50) -> List[CV]:
    return list(db.scalars(select(CV).order_by(CV.uploaded_at.desc()).limit(limit)))


def cv_to_profile(cv: CV) -> CVProfile:
    return CVProfile(
        skills=_loads(cv.skills_json, []),
        job_titles=_loads(cv.job_titles_json, []),
        experience=_loads(cv.experience_json, []),
        education=_loads(cv.education_json, []),
        technologies=_loads(cv.technologies_json, []),
        certifications=_loads(cv.certifications_json, []),
        years_experience=cv.years_experience or 0.0,
        summary=cv.summary or "",
    )


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
def create_application(db: Session, data: Dict[str, Any]) -> Application:
    status = data.get("status") or ApplicationStatus.saved.value
    app_row = Application(
        cv_id=data["cv_id"],
        job_title=data.get("job_title", ""),
        company=data.get("company", ""),
        job_url=data.get("job_url", ""),
        location=data.get("location", ""),
        source=data.get("source", ""),
        match_score=float(data.get("match_score") or 0.0),
        status=status,
        notes=data.get("notes", ""),
        next_action_date=data.get("next_action_date"),
        applied_date=(
            datetime.now(timezone.utc) if status == ApplicationStatus.applied.value else None
        ),
    )
    db.add(app_row)
    db.flush()
    db.add(
        ApplicationEvent(
            application_id=app_row.id,
            old_status="",
            new_status=status,
            note="Application created",
        )
    )
    db.commit()
    db.refresh(app_row)
    return app_row


def get_application(db: Session, app_id: str) -> Optional[Application]:
    return db.get(Application, app_id)


def list_applications(
    db: Session, cv_id: Optional[str] = None, status: Optional[str] = None
) -> List[Application]:
    stmt = select(Application)
    if cv_id:
        stmt = stmt.where(Application.cv_id == cv_id)
    if status:
        stmt = stmt.where(Application.status == status)
    return list(db.scalars(stmt.order_by(Application.updated_at.desc())))


def update_application(
    db: Session, app_row: Application, changes: Dict[str, Any]
) -> Application:
    """Applies changes; a status transition always records an event."""
    new_status = changes.get("status")
    old_status = app_row.status

    for field in ("notes", "next_action_date", "job_title", "company"):
        if changes.get(field) is not None:
            setattr(app_row, field, changes[field])

    if new_status and new_status != old_status:
        app_row.status = new_status
        if new_status == ApplicationStatus.applied.value and not app_row.applied_date:
            app_row.applied_date = datetime.now(timezone.utc)
        db.add(
            ApplicationEvent(
                application_id=app_row.id,
                old_status=old_status,
                new_status=new_status,
                note=changes.get("event_note") or f"Status changed: {old_status} → {new_status}",
            )
        )
    elif changes.get("event_note"):
        db.add(
            ApplicationEvent(
                application_id=app_row.id,
                old_status=old_status,
                new_status=old_status,
                note=changes["event_note"],
            )
        )

    app_row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app_row)
    return app_row


def delete_application(db: Session, app_row: Application) -> None:
    db.delete(app_row)
    db.commit()


def application_stats(db: Session, cv_id: str) -> Dict[str, Any]:
    rows = list_applications(db, cv_id=cv_id)
    by_status: Dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    interviewing = [
        {"company": r.company, "job_title": r.job_title}
        for r in rows
        if r.status == ApplicationStatus.interviewing.value
    ]
    return {
        "total": len(rows),
        "by_status": by_status,
        "interviewing_with": interviewing,
        "offers": by_status.get("offer", 0),
        "recent": [
            {"job_title": r.job_title, "company": r.company, "status": r.status}
            for r in rows[:5]
        ],
    }


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
def create_alert(db: Session, data: Dict[str, Any]) -> AlertSubscription:
    alert = AlertSubscription(
        cv_id=data["cv_id"],
        name=data.get("name", "My alert"),
        filters_json=json.dumps(data.get("filters") or {}, default=str),
        channel=data.get("channel", "email"),
        destination=data.get("destination", ""),
        is_active=bool(data.get("is_active", True)),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def get_alert(db: Session, alert_id: str) -> Optional[AlertSubscription]:
    return db.get(AlertSubscription, alert_id)


def list_alerts(db: Session, cv_id: Optional[str] = None) -> List[AlertSubscription]:
    stmt = select(AlertSubscription)
    if cv_id:
        stmt = stmt.where(AlertSubscription.cv_id == cv_id)
    return list(db.scalars(stmt.order_by(AlertSubscription.created_at.desc())))


def list_active_alerts(db: Session) -> List[AlertSubscription]:
    return list(
        db.scalars(select(AlertSubscription).where(AlertSubscription.is_active.is_(True)))
    )


def update_alert(db: Session, alert: AlertSubscription, changes: Dict[str, Any]) -> AlertSubscription:
    if changes.get("is_active") is not None:
        alert.is_active = bool(changes["is_active"])
    if changes.get("name") is not None:
        alert.name = changes["name"]
    if changes.get("destination") is not None:
        alert.destination = str(changes["destination"])
    if changes.get("filters") is not None:
        alert.filters_json = json.dumps(changes["filters"], default=str)
    db.commit()
    db.refresh(alert)
    return alert


def delete_alert(db: Session, alert: AlertSubscription) -> None:
    db.delete(alert)
    db.commit()


def alert_to_dict(alert: AlertSubscription) -> Dict[str, Any]:
    return {
        "id": alert.id,
        "cv_id": alert.cv_id,
        "name": alert.name,
        "channel": alert.channel,
        "destination": alert.destination,
        "is_active": alert.is_active,
        "filters": _loads(alert.filters_json, {}),
        "last_run_at": alert.last_run_at,
        "last_error": alert.last_error or "",
        "created_at": alert.created_at,
    }


# --------------------------------------------------------------------------
# Seen jobs (alert diffing)
# --------------------------------------------------------------------------
def filter_unseen_jobs(db: Session, alert_id: str, jobs: List[Job]) -> List[Job]:
    from app.services.normalize import url_hash

    known = {
        row.job_url_hash
        for row in db.scalars(select(SeenJob).where(SeenJob.alert_id == alert_id))
    }
    fresh: List[Job] = []
    for job in jobs:
        digest = url_hash(job.url) if job.url else job.id
        if digest in known:
            continue
        known.add(digest)
        fresh.append(job)
    return fresh


def mark_jobs_seen(db: Session, alert_id: str, jobs: List[Job]) -> int:
    from app.services.normalize import url_hash

    added = 0
    for job in jobs:
        digest = url_hash(job.url) if job.url else job.id
        exists = db.scalar(
            select(SeenJob).where(
                SeenJob.alert_id == alert_id, SeenJob.job_url_hash == digest
            )
        )
        if exists:
            continue
        db.add(
            SeenJob(
                alert_id=alert_id,
                job_url_hash=digest,
                job_title=job.title[:500],
                company=job.company[:300],
            )
        )
        added += 1
    db.commit()
    return added


# --------------------------------------------------------------------------
# Search cache / skill gap reports / chat
# --------------------------------------------------------------------------
def save_search_results(
    db: Session, cv_id: str, task_id: str, query: Dict[str, Any], jobs: List[Job], errors: List[Any]
) -> SearchResultCache:
    row = SearchResultCache(
        cv_id=cv_id,
        task_id=task_id,
        query_json=json.dumps(query, default=str),
        results_json=json.dumps([j.model_dump(mode="json") for j in jobs], ensure_ascii=False),
        errors_json=json.dumps(
            [e.model_dump(mode="json") if hasattr(e, "model_dump") else str(e) for e in errors],
            ensure_ascii=False,
        ),
        total_found=len(jobs),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_search_results(db: Session, cv_id: str) -> List[Job]:
    row = db.scalars(
        select(SearchResultCache)
        .where(SearchResultCache.cv_id == cv_id)
        .order_by(SearchResultCache.created_at.desc())
        .limit(1)
    ).first()
    if not row:
        return []
    return [Job(**item) for item in _loads(row.results_json, [])]


def save_skill_gap_report(db: Session, cv_id: str, payload: Dict[str, Any], is_aggregate: bool = False) -> SkillGapReport:
    report = SkillGapReport(
        cv_id=cv_id,
        job_url=payload.get("job_url", ""),
        job_title=payload.get("job_title", ""),
        missing_skills_json=json.dumps(payload.get("missing_skills", []), ensure_ascii=False),
        matching_skills_json=json.dumps(payload.get("matching_skills", []), ensure_ascii=False),
        gap_score=float(payload.get("gap_score") or payload.get("average_gap_score") or 0.0),
        explanation=payload.get("explanation") or payload.get("summary") or "",
        is_aggregate=is_aggregate,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def latest_skill_gap(db: Session, cv_id: str, aggregate: bool = True) -> Optional[Dict[str, Any]]:
    row = db.scalars(
        select(SkillGapReport)
        .where(SkillGapReport.cv_id == cv_id, SkillGapReport.is_aggregate.is_(aggregate))
        .order_by(SkillGapReport.created_at.desc())
        .limit(1)
    ).first()
    return _loads(row.payload_json, {}) if row else None


def get_or_create_chat_session(db: Session, cv_id: str, session_id: str) -> CareerChatSession:
    row = db.scalars(
        select(CareerChatSession).where(
            CareerChatSession.cv_id == cv_id, CareerChatSession.session_id == session_id
        )
    ).first()
    if row:
        return row
    row = CareerChatSession(cv_id=cv_id, session_id=session_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_chat_message(
    db: Session, session_row: CareerChatSession, role: str, content: str, tools: Optional[List[str]] = None
) -> CareerChatMessage:
    msg = CareerChatMessage(
        session_id=session_row.id,
        role=role,
        content=content,
        tools_used_json=json.dumps(tools or [], ensure_ascii=False),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_chat_history(db: Session, session_row: CareerChatSession, limit: int = 20) -> List[CareerChatMessage]:
    rows = list(
        db.scalars(
            select(CareerChatMessage)
            .where(CareerChatMessage.session_id == session_row.id)
            .order_by(CareerChatMessage.created_at.desc())
            .limit(limit)
        )
    )
    return list(reversed(rows))
