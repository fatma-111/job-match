"""SQLAlchemy ORM models — mirrors the schema in section 9.0 of the project plan."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class ApplicationStatus(str, PyEnum):
    saved = "saved"
    applied = "applied"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"


TERMINAL_STATUSES = {
    ApplicationStatus.rejected,
    ApplicationStatus.withdrawn,
    ApplicationStatus.offer,
}


class CV(Base):
    __tablename__ = "cvs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    job_titles_json: Mapped[str] = mapped_column(Text, default="[]")
    experience_json: Mapped[str] = mapped_column(Text, default="[]")
    education_json: Mapped[str] = mapped_column(Text, default="[]")
    technologies_json: Mapped[str] = mapped_column(Text, default="[]")
    certifications_json: Mapped[str] = mapped_column(Text, default="[]")
    years_experience: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    parse_method: Mapped[str] = mapped_column(String(32), default="heuristic")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    applications: Mapped[list["Application"]] = relationship(
        back_populates="cv", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["AlertSubscription"]] = relationship(
        back_populates="cv", cascade="all, delete-orphan"
    )
    skill_gap_reports: Mapped[list["SkillGapReport"]] = relationship(
        back_populates="cv", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["CareerChatSession"]] = relationship(
        back_populates="cv", cascade="all, delete-orphan"
    )
    searches: Mapped[list["SearchResultCache"]] = relationship(
        back_populates="cv", cascade="all, delete-orphan"
    )


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    cv_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cvs.id", ondelete="CASCADE"), index=True
    )
    job_url: Mapped[str] = mapped_column(Text, default="")
    job_title: Mapped[str] = mapped_column(String(500), default="")
    company: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    source: Mapped[str] = mapped_column(String(50), default="")
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(
        String(32), default=ApplicationStatus.saved.value, index=True
    )
    applied_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    next_action_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    cv: Mapped[CV] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.created_at",
    )


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    old_status: Mapped[str] = mapped_column(String(32), default="")
    new_status: Mapped[str] = mapped_column(String(32), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped[Application] = relationship(back_populates="events")


class AlertSubscription(Base):
    __tablename__ = "alert_subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    cv_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cvs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="My alert")
    filters_json: Mapped[str] = mapped_column(Text, default="{}")
    channel: Mapped[str] = mapped_column(String(32), default="email")
    destination: Mapped[str] = mapped_column(String(320), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    cv: Mapped[CV] = relationship(back_populates="alerts")
    seen_jobs: Mapped[list["SeenJob"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )


class SeenJob(Base):
    __tablename__ = "seen_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    alert_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("alert_subscriptions.id", ondelete="CASCADE"), index=True
    )
    job_url_hash: Mapped[str] = mapped_column(String(64), index=True)
    job_title: Mapped[str] = mapped_column(String(500), default="")
    company: Mapped[str] = mapped_column(String(300), default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    alert: Mapped[AlertSubscription] = relationship(back_populates="seen_jobs")


Index("ix_seen_alert_hash", SeenJob.alert_id, SeenJob.job_url_hash, unique=True)


class SkillGapReport(Base):
    __tablename__ = "skill_gap_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    cv_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cvs.id", ondelete="CASCADE"), index=True
    )
    job_url: Mapped[str] = mapped_column(Text, default="")
    job_title: Mapped[str] = mapped_column(String(500), default="")
    missing_skills_json: Mapped[str] = mapped_column(Text, default="[]")
    matching_skills_json: Mapped[str] = mapped_column(Text, default="[]")
    gap_score: Mapped[float] = mapped_column(Float, default=0.0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    is_aggregate: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    cv: Mapped[CV] = relationship(back_populates="skill_gap_reports")


class CareerChatSession(Base):
    __tablename__ = "career_chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    cv_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cvs.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Career chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    cv: Mapped[CV] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["CareerChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CareerChatMessage.created_at",
    )


class CareerChatMessage(Base):
    __tablename__ = "career_chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("career_chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="user")
    content: Mapped[str] = mapped_column(Text, default="")
    tools_used_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session: Mapped[CareerChatSession] = relationship(back_populates="messages")


class SearchResultCache(Base):
    """Stores the last ranked search per CV so the Career Agent has context."""

    __tablename__ = "search_results_cache"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    cv_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cvs.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    query_json: Mapped[str] = mapped_column(Text, default="{}")
    results_json: Mapped[str] = mapped_column(Text, default="[]")
    errors_json: Mapped[str] = mapped_column(Text, default="[]")
    total_found: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    cv: Mapped[CV] = relationship(back_populates="searches")
