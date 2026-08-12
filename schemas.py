"""Pydantic request/response models for the whole API."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# --------------------------------------------------------------------------
# CV
# --------------------------------------------------------------------------
class CVProfile(BaseModel):
    skills: List[str] = Field(default_factory=list)
    job_titles: List[str] = Field(default_factory=list)
    experience: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    years_experience: float = 0.0
    summary: str = ""


class CVUploadResponse(BaseModel):
    cv_id: str
    filename: str
    characters: int
    parse_method: str = Field(description="'llm' or 'heuristic'")
    profile: CVProfile


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
class JobSource(str, Enum):
    wuzzuf = "wuzzuf"
    bayt = "bayt"
    tanqeeb = "tanqeeb"
    indeed = "indeed"
    linkedin = "linkedin"


class RawJob(BaseModel):
    """What a scraper returns before normalisation."""

    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    salary_text: Optional[str] = None
    posted_text: Optional[str] = None
    job_type: Optional[str] = None
    source: str = ""


class Job(BaseModel):
    """Normalised + (optionally) ranked job."""

    id: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    source: str = ""
    job_type: Optional[str] = None

    salary_text: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_period: Optional[str] = None

    posted_text: Optional[str] = None
    posted_date: Optional[datetime] = None

    match_score: Optional[float] = None
    matching_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    match_explanation: str = ""


class SearchFilters(BaseModel):
    keywords: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None
    min_salary: Optional[float] = None
    max_age_days: Optional[int] = Field(
        default=None, description="Only keep jobs posted within N days"
    )
    sources: Optional[List[JobSource]] = None
    limit_per_source: int = 20

    @field_validator("limit_per_source")
    @classmethod
    def _cap_limit(cls, v: int) -> int:
        return max(1, min(v, 50))


class SearchRequest(BaseModel):
    cv_id: str
    filters: SearchFilters = Field(default_factory=SearchFilters)


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class SourceError(BaseModel):
    source: str
    error: str
    error_type: str = "scrape_error"


class SearchTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    message: str = ""


class SearchStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: str = ""
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total_found: int = 0
    results: List[Job] = Field(default_factory=list)
    errors: List[SourceError] = Field(default_factory=list)
    error: Optional[str] = None


# --------------------------------------------------------------------------
# Cover letter / mock interview
# --------------------------------------------------------------------------
class CoverLetterRequest(BaseModel):
    cv_id: str
    job_title: str
    company: str = ""
    job_description: str = ""
    job_url: str = ""
    tone: str = "professional"
    language: str = "english"


class CoverLetterResponse(BaseModel):
    cover_letter: str
    model_used: str = ""


class MockInterviewRequest(BaseModel):
    cv_id: str
    job_title: str
    company: str = ""
    job_description: str = ""
    num_questions: int = Field(default=8, ge=3, le=20)
    language: str = "english"


class InterviewQuestion(BaseModel):
    question: str
    category: str = "general"
    why_asked: str = ""
    answer_hint: str = ""


class MockInterviewResponse(BaseModel):
    questions: List[InterviewQuestion]
    model_used: str = ""


# --------------------------------------------------------------------------
# Skill gap
# --------------------------------------------------------------------------
class SkillGapRequest(BaseModel):
    cv_id: str
    job_title: str
    job_description: str = ""
    job_url: str = ""


class SkillGapResponse(BaseModel):
    job_title: str
    job_url: str = ""
    matching_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    gap_score: float = 0.0
    explanation: str = ""
    method: str = "heuristic"


class AggregateSkillGapRequest(BaseModel):
    cv_id: str
    jobs: List[Job] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=30)
    use_cached_results: bool = True


class SkillCount(BaseModel):
    skill: str
    count: int
    percentage: float


class AggregateSkillGapResponse(BaseModel):
    jobs_analyzed: int
    top_missing_skills: List[SkillCount] = Field(default_factory=list)
    top_matching_skills: List[SkillCount] = Field(default_factory=list)
    average_gap_score: float = 0.0
    learning_priorities: List[str] = Field(default_factory=list)
    summary: str = ""


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
class ApplicationStatusEnum(str, Enum):
    saved = "saved"
    applied = "applied"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"


class ApplicationCreate(BaseModel):
    cv_id: str
    job_title: str
    company: str = ""
    job_url: str = ""
    location: str = ""
    source: str = ""
    match_score: float = 0.0
    status: ApplicationStatusEnum = ApplicationStatusEnum.saved
    notes: str = ""
    next_action_date: Optional[datetime] = None


class ApplicationUpdate(BaseModel):
    status: Optional[ApplicationStatusEnum] = None
    notes: Optional[str] = None
    next_action_date: Optional[datetime] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    event_note: Optional[str] = None


class ApplicationEventOut(BaseModel):
    id: str
    old_status: str
    new_status: str
    note: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplicationOut(BaseModel):
    id: str
    cv_id: str
    job_title: str
    company: str
    location: str
    job_url: str
    source: str
    match_score: float
    status: str
    notes: str
    applied_date: Optional[datetime] = None
    next_action_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApplicationTimeline(BaseModel):
    application: ApplicationOut
    events: List[ApplicationEventOut] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
class AlertCreate(BaseModel):
    cv_id: str
    name: str = "My alert"
    destination: EmailStr
    channel: str = "email"
    filters: SearchFilters = Field(default_factory=SearchFilters)
    is_active: bool = True


class AlertUpdate(BaseModel):
    is_active: Optional[bool] = None
    name: Optional[str] = None
    destination: Optional[EmailStr] = None
    filters: Optional[SearchFilters] = None


class AlertOut(BaseModel):
    id: str
    cv_id: str
    name: str
    channel: str
    destination: str
    is_active: bool
    filters: Dict[str, Any] = Field(default_factory=dict)
    last_run_at: Optional[datetime] = None
    last_error: str = ""
    created_at: datetime


# --------------------------------------------------------------------------
# Career agent
# --------------------------------------------------------------------------
class CareerChatRequest(BaseModel):
    cv_id: str
    session_id: Optional[str] = None
    message: str = Field(min_length=1)


class CareerChatResponse(BaseModel):
    session_id: str
    reply: str
    tools_used: List[str] = Field(default_factory=list)
    model_used: str = ""


class ChatMessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    llm_configured: bool
    embeddings: str
    scheduler: str
    smtp_configured: bool
    time: datetime


class ErrorResponse(BaseModel):
    detail: str
    error_type: str = "error"
