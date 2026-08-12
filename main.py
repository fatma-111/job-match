"""FastAPI application — every endpoint from the project plan."""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.db import get_db, init_db, session_scope
from app.schemas import (
    AggregateSkillGapRequest,
    AggregateSkillGapResponse,
    AlertCreate,
    AlertOut,
    AlertUpdate,
    ApplicationCreate,
    ApplicationOut,
    ApplicationTimeline,
    ApplicationUpdate,
    CareerChatRequest,
    CareerChatResponse,
    CoverLetterRequest,
    CoverLetterResponse,
    CVUploadResponse,
    HealthResponse,
    Job,
    MockInterviewRequest,
    MockInterviewResponse,
    SearchRequest,
    SearchStatusResponse,
    SearchTaskResponse,
    SkillGapRequest,
    SkillGapResponse,
    TaskStatus,
)
from app.services.llm_client import LLMUnavailable
from app.services.matching import CVParseError, embedding_service, extract_cv_profile, extract_cv_text
from app.services.task_store import task_store

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.services.scheduler import shutdown_scheduler, start_scheduler

    try:
        start_scheduler()
    except Exception as exc:  # noqa: BLE001 - never block startup
        logger.error("Scheduler failed to start: %s", exc)
    yield
    shutdown_scheduler()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="AI job matching agent: CV parsing, multi-source search, ranking, "
    "skill gap, application tracking, alerts and a career chatbot.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

P = settings.api_prefix


@app.exception_handler(CVParseError)
async def _cv_parse_handler(request, exc: CVParseError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc), "error_type": "cv_parse_error"},
    )


@app.exception_handler(LLMUnavailable)
async def _llm_handler(request, exc: LLMUnavailable):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc), "error_type": "llm_unavailable"},
    )


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    from app.services.scheduler import scheduler_status

    db_state = "ok"
    try:
        with session_scope() as db:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_state = f"error: {exc}"[:120]

    return HealthResponse(
        status="ok" if db_state == "ok" else "degraded",
        version="1.0.0",
        database=db_state,
        llm_configured=settings.llm_enabled,
        embeddings=embedding_service.backend,
        scheduler=scheduler_status(),
        smtp_configured=settings.smtp_configured,
        time=datetime.now(timezone.utc),
    )


@app.get("/", tags=["system"])
async def root() -> Dict[str, Any]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/health",
        "api_prefix": P,
    }


# --------------------------------------------------------------------------
# CV
# --------------------------------------------------------------------------
@app.post(f"{P}/cv/upload", response_model=CVUploadResponse, tags=["cv"])
async def upload_cv(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> CVUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data)//1024} KB). Limit is {MAX_UPLOAD_BYTES//1024//1024} MB.",
        )

    text = extract_cv_text(data, file.filename)  # raises CVParseError -> 422
    profile, method = await extract_cv_profile(text)
    cv = crud.create_cv(db, text, profile, file.filename, method)

    return CVUploadResponse(
        cv_id=cv.id,
        filename=cv.filename,
        characters=len(text),
        parse_method=method,
        profile=profile,
    )


@app.get(f"{P}/cv/{{cv_id}}", tags=["cv"])
async def get_cv_endpoint(cv_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    cv = crud.get_cv(db, cv_id)
    if cv is None:
        raise HTTPException(status_code=404, detail=f"CV '{cv_id}' not found.")
    return {
        "cv_id": cv.id,
        "filename": cv.filename,
        "uploaded_at": cv.uploaded_at,
        "parse_method": cv.parse_method,
        "profile": crud.cv_to_profile(cv).model_dump(),
    }


@app.get(f"{P}/cvs", tags=["cv"])
async def list_cvs_endpoint(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return [
        {
            "cv_id": cv.id,
            "filename": cv.filename,
            "uploaded_at": cv.uploaded_at,
            "skills": crud.cv_to_profile(cv).skills[:8],
        }
        for cv in crud.list_cvs(db)
    ]


# --------------------------------------------------------------------------
# Job search (async task)
# --------------------------------------------------------------------------
async def _run_search_task(task_id: str, cv_id: str, filters_payload: Dict[str, Any]) -> None:
    from app.agents.graph import run_job_search
    from app.schemas import SearchFilters

    await task_store.update(task_id, status=TaskStatus.running, progress="starting")
    try:
        with session_scope() as db:
            cv = crud.get_cv(db, cv_id)
            if cv is None:
                await task_store.update(
                    task_id, status=TaskStatus.failed, error=f"CV '{cv_id}' not found."
                )
                return
            profile = crud.cv_to_profile(cv)
            cv_text = cv.raw_text

        filters = SearchFilters(**filters_payload)
        result = await run_job_search(profile, filters, cv_text=cv_text, cv_id=cv_id)
        jobs: List[Job] = result.get("jobs") or []
        errors = result.get("errors") or []

        with session_scope() as db:
            crud.save_search_results(db, cv_id, task_id, filters_payload, jobs, errors)

        await task_store.update(
            task_id,
            status=TaskStatus.completed,
            results=jobs,
            errors=errors,
            progress=result.get("progress", "done"),
        )
        logger.info("Search %s finished: %d jobs, %d source errors", task_id, len(jobs), len(errors))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search task %s crashed", task_id)
        await task_store.update(task_id, status=TaskStatus.failed, error=str(exc)[:500])


@app.post(f"{P}/jobs/search", response_model=SearchTaskResponse, tags=["jobs"])
async def start_search(
    payload: SearchRequest, background: BackgroundTasks, db: Session = Depends(get_db)
) -> SearchTaskResponse:
    if crud.get_cv(db, payload.cv_id) is None:
        raise HTTPException(status_code=404, detail=f"CV '{payload.cv_id}' not found. Upload a CV first.")

    task = await task_store.create({"cv_id": payload.cv_id})
    background.add_task(
        _run_search_task, task.id, payload.cv_id, payload.filters.model_dump(mode="json")
    )
    return SearchTaskResponse(
        task_id=task.id,
        status=TaskStatus.pending,
        message="Search started. Poll /jobs/status/{task_id} for results.",
    )


@app.get(f"{P}/jobs/status/{{task_id}}", response_model=SearchStatusResponse, tags=["jobs"])
async def search_status(task_id: str) -> SearchStatusResponse:
    task = await task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found or expired.")
    return SearchStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=task.progress,
        created_at=task.created_at,
        finished_at=task.finished_at,
        total_found=len(task.results),
        results=task.results,
        errors=task.errors,
        error=task.error,
    )


# --------------------------------------------------------------------------
# Cover letter / mock interview
# --------------------------------------------------------------------------
def _require_profile(db: Session, cv_id: str):
    cv = crud.get_cv(db, cv_id)
    if cv is None:
        raise HTTPException(status_code=404, detail=f"CV '{cv_id}' not found.")
    return crud.cv_to_profile(cv)


@app.post(f"{P}/cover-letter", response_model=CoverLetterResponse, tags=["content"])
async def cover_letter(payload: CoverLetterRequest, db: Session = Depends(get_db)) -> CoverLetterResponse:
    from app.agents.nodes import generate_cover_letter

    profile = _require_profile(db, payload.cv_id)
    return await generate_cover_letter(
        profile,
        payload.job_title,
        payload.company,
        payload.job_description,
        payload.tone,
        payload.language,
    )


@app.post(f"{P}/mock-interview", response_model=MockInterviewResponse, tags=["content"])
async def mock_interview(payload: MockInterviewRequest, db: Session = Depends(get_db)) -> MockInterviewResponse:
    from app.agents.nodes import generate_mock_interview

    profile = _require_profile(db, payload.cv_id)
    return await generate_mock_interview(
        profile,
        payload.job_title,
        payload.company,
        payload.job_description,
        payload.num_questions,
        payload.language,
    )


# --------------------------------------------------------------------------
# Skill gap
# --------------------------------------------------------------------------
@app.post(f"{P}/skill-gap/job", response_model=SkillGapResponse, tags=["skill-gap"])
async def skill_gap_job(payload: SkillGapRequest, db: Session = Depends(get_db)) -> SkillGapResponse:
    from app.services.skill_gap import analyze_skill_gap

    profile = _require_profile(db, payload.cv_id)
    report = await analyze_skill_gap(
        profile, payload.job_title, payload.job_description, payload.job_url
    )
    crud.save_skill_gap_report(db, payload.cv_id, report.model_dump(mode="json"), is_aggregate=False)
    return report


@app.post(f"{P}/skill-gap/aggregate", response_model=AggregateSkillGapResponse, tags=["skill-gap"])
async def skill_gap_aggregate(
    payload: AggregateSkillGapRequest, db: Session = Depends(get_db)
) -> AggregateSkillGapResponse:
    from app.services.skill_gap import aggregate_skill_gaps

    profile = _require_profile(db, payload.cv_id)
    jobs = payload.jobs
    if not jobs and payload.use_cached_results:
        jobs = crud.latest_search_results(db, payload.cv_id)
    if not jobs:
        raise HTTPException(
            status_code=400,
            detail="No jobs supplied and no cached search results found. Run a job search first.",
        )

    report = await aggregate_skill_gaps(profile, jobs, top_n=payload.top_n)
    crud.save_skill_gap_report(db, payload.cv_id, report.model_dump(mode="json"), is_aggregate=True)
    return report


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
@app.post(f"{P}/applications", response_model=ApplicationOut, status_code=201, tags=["applications"])
async def create_application(payload: ApplicationCreate, db: Session = Depends(get_db)) -> ApplicationOut:
    if crud.get_cv(db, payload.cv_id) is None:
        raise HTTPException(status_code=404, detail=f"CV '{payload.cv_id}' not found.")
    row = crud.create_application(db, payload.model_dump())
    return ApplicationOut.model_validate(row)


@app.get(f"{P}/applications", response_model=List[ApplicationOut], tags=["applications"])
async def list_applications(
    cv_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> List[ApplicationOut]:
    rows = crud.list_applications(db, cv_id=cv_id, status=status_filter)
    return [ApplicationOut.model_validate(r) for r in rows]


@app.patch(f"{P}/applications/{{application_id}}", response_model=ApplicationOut, tags=["applications"])
async def patch_application(
    application_id: str, payload: ApplicationUpdate, db: Session = Depends(get_db)
) -> ApplicationOut:
    row = crud.get_application(db, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' not found.")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields supplied to update.")
    if changes.get("status") is not None:
        changes["status"] = changes["status"].value if hasattr(changes["status"], "value") else changes["status"]
    row = crud.update_application(db, row, changes)
    return ApplicationOut.model_validate(row)


@app.delete(f"{P}/applications/{{application_id}}", status_code=204, tags=["applications"])
async def delete_application(application_id: str, db: Session = Depends(get_db)) -> None:
    row = crud.get_application(db, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' not found.")
    crud.delete_application(db, row)


@app.get(f"{P}/applications/{{application_id}}/timeline", response_model=ApplicationTimeline, tags=["applications"])
async def application_timeline(application_id: str, db: Session = Depends(get_db)) -> ApplicationTimeline:
    row = crud.get_application(db, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' not found.")
    return ApplicationTimeline(
        application=ApplicationOut.model_validate(row),
        events=[e for e in row.events],
    )


@app.get(f"{P}/applications/stats", tags=["applications"])
async def applications_stats(cv_id: str = Query(...), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return crud.application_stats(db, cv_id)


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
@app.post(f"{P}/alerts", response_model=AlertOut, status_code=201, tags=["alerts"])
async def create_alert(payload: AlertCreate, db: Session = Depends(get_db)) -> AlertOut:
    if crud.get_cv(db, payload.cv_id) is None:
        raise HTTPException(status_code=404, detail=f"CV '{payload.cv_id}' not found.")
    data = payload.model_dump(mode="json")
    data["filters"] = payload.filters.model_dump(mode="json")
    row = crud.create_alert(db, data)
    return AlertOut(**crud.alert_to_dict(row))


@app.get(f"{P}/alerts", response_model=List[AlertOut], tags=["alerts"])
async def list_alerts(
    cv_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)
) -> List[AlertOut]:
    return [AlertOut(**crud.alert_to_dict(a)) for a in crud.list_alerts(db, cv_id)]


@app.patch(f"{P}/alerts/{{alert_id}}", response_model=AlertOut, tags=["alerts"])
async def patch_alert(alert_id: str, payload: AlertUpdate, db: Session = Depends(get_db)) -> AlertOut:
    row = crud.get_alert(db, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")
    changes = payload.model_dump(exclude_unset=True, mode="json")
    if not changes:
        raise HTTPException(status_code=400, detail="No fields supplied to update.")
    row = crud.update_alert(db, row, changes)
    return AlertOut(**crud.alert_to_dict(row))


@app.delete(f"{P}/alerts/{{alert_id}}", status_code=204, tags=["alerts"])
async def delete_alert(alert_id: str, db: Session = Depends(get_db)) -> None:
    row = crud.get_alert(db, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")
    crud.delete_alert(db, row)


@app.post(f"{P}/alerts/{{alert_id}}/run", tags=["alerts"])
async def run_alert_now(
    alert_id: str, send_email: bool = Query(default=True), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Trigger a subscription immediately (useful for testing the pipeline)."""
    from app.services.scheduler import run_alert

    if crud.get_alert(db, alert_id) is None:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")
    outcome = await run_alert(alert_id, send_email=send_email)
    jobs = outcome.get("new_jobs") or []
    return {
        "alert_id": alert_id,
        "new_jobs_count": len(jobs),
        "new_jobs": [j.model_dump(mode="json") for j in jobs[:20]],
        "total_found": outcome.get("total_found", 0),
        "emailed": outcome.get("emailed", False),
        "email_error": outcome.get("email_error"),
        "errors": [e.model_dump(mode="json") for e in (outcome.get("errors") or [])],
    }


# --------------------------------------------------------------------------
# Career agent
# --------------------------------------------------------------------------
@app.post(f"{P}/career-agent/chat", response_model=CareerChatResponse, tags=["career-agent"])
async def career_agent_chat(payload: CareerChatRequest, db: Session = Depends(get_db)) -> CareerChatResponse:
    from app.services.career_agent import chat

    if crud.get_cv(db, payload.cv_id) is None:
        raise HTTPException(status_code=404, detail=f"CV '{payload.cv_id}' not found.")
    session_id = payload.session_id or uuid.uuid4().hex
    return await chat(db, payload.cv_id, session_id, payload.message)


@app.get(f"{P}/career-agent/history", tags=["career-agent"])
async def career_agent_history(
    cv_id: str = Query(...), session_id: str = Query(...), db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    row = crud.get_or_create_chat_session(db, cv_id, session_id)
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at}
        for m in crud.get_chat_history(db, row, limit=100)
    ]
