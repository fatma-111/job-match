"""LangGraph node functions + cover letter / mock interview generators."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.agents.state import SearchState
from app.config import settings
from app.schemas import (
    CoverLetterResponse,
    CVProfile,
    InterviewQuestion,
    Job,
    MockInterviewResponse,
    SearchFilters,
    SourceError,
)
from app.scrapers.base import BrowserSession, ScraperError, ScraperUnavailable
from app.scrapers.registry import get_scraper_class
from app.services.llm_client import LLMUnavailable, llm_client
from app.services.matching import rank_jobs
from app.services.normalize import monthly_equivalent, normalize_and_dedupe

logger = logging.getLogger(__name__)


# ==========================================================================
# 1. Query building
# ==========================================================================
def build_search_query(state: SearchState) -> Dict[str, Any]:
    """Turn the CV profile + filters into a search string."""
    filters: SearchFilters = state.get("filters") or SearchFilters()
    profile: CVProfile = state.get("profile") or CVProfile()

    if filters.keywords and filters.keywords.strip():
        query = filters.keywords.strip()
    elif profile.job_titles:
        query = profile.job_titles[0]
    elif profile.skills:
        query = " ".join(profile.skills[:3])
    else:
        query = "jobs"

    requested = [s.value for s in filters.sources] if filters.sources else settings.sources
    sources = [s for s in requested if s in settings.sources] or settings.sources

    return {
        "query": query[:120],
        "location": (filters.location or "").strip(),
        "sources": sources,
        "progress": f"searching {len(sources)} source(s) for '{query[:60]}'",
    }


# ==========================================================================
# 2. Fan-out: one node per source, fully isolated
# ==========================================================================
def make_scraper_node(source: str):
    """Build an async node that scrapes one source and never raises."""

    async def _node(state: SearchState) -> Dict[str, Any]:
        if source not in (state.get("sources") or []):
            return {}  # source disabled for this run

        filters: SearchFilters = state.get("filters") or SearchFilters()
        browser: BrowserSession | None = state.get("browser")
        started = datetime.now(timezone.utc)

        if browser is None:
            reason = state.get("browser_error") or "No browser session available."
            return {
                "errors": [
                    SourceError(source=source, error=reason[:400], error_type="unavailable")
                ],
                "source_stats": {source: {"count": 0, "error": True}},
            }

        try:
            scraper = get_scraper_class(source)(browser)
            jobs = await scraper.search(
                state.get("query", ""),
                state.get("location", ""),
                limit=filters.limit_per_source,
            )
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            logger.info("%s returned %d jobs in %.1fs", source, len(jobs), elapsed)
            return {
                "raw_jobs": jobs,
                "source_stats": {source: {"count": len(jobs), "seconds": round(elapsed, 1)}},
            }
        except (ScraperError, ScraperUnavailable) as exc:
            logger.warning("%s failed: %s", source, exc)
            return {
                "errors": [
                    SourceError(
                        source=source,
                        error=str(exc)[:500],
                        error_type=getattr(exc, "error_type", "scrape_error"),
                    )
                ],
                "source_stats": {source: {"count": 0, "error": True}},
            }
        except Exception as exc:  # noqa: BLE001 - a source must never kill the graph
            logger.exception("%s unexpected failure", source)
            return {
                "errors": [
                    SourceError(source=source, error=f"Unexpected: {exc}"[:500], error_type="unexpected")
                ],
                "source_stats": {source: {"count": 0, "error": True}},
            }

    _node.__name__ = f"scrape_{source}"
    return _node


# ==========================================================================
# 3. Fan-in: normalize -> filter -> rank
# ==========================================================================
def normalize_jobs(state: SearchState) -> Dict[str, Any]:
    raws = state.get("raw_jobs") or []
    jobs = normalize_and_dedupe(raws)
    return {
        "jobs": jobs,
        "total_found": len(jobs),
        "progress": f"normalised {len(jobs)} unique job(s) from {len(raws)} raw result(s)",
    }


def filter_jobs(state: SearchState) -> Dict[str, Any]:
    """Apply salary / date / location / type / keyword filters.

    Missing data never causes exclusion — we don't penalise a job for a field
    the site didn't publish.
    """
    jobs: List[Job] = state.get("jobs") or []
    filters: SearchFilters = state.get("filters") or SearchFilters()
    if not jobs:
        return {"jobs": [], "total_found": 0}

    cutoff = None
    if filters.max_age_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=filters.max_age_days)

    kept: List[Job] = []
    for job in jobs:
        if filters.min_salary is not None:
            monthly = monthly_equivalent(job.salary_min, job.salary_period)
            if monthly is not None and monthly < filters.min_salary:
                continue  # only exclude when we actually know the salary

        if cutoff is not None and job.posted_date is not None:
            posted = job.posted_date
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            if posted < cutoff:
                continue

        if filters.location:
            needle = filters.location.lower().strip()
            haystack = f"{job.location} {job.title} {job.description}".lower()
            if job.location and needle not in haystack:
                continue

        if filters.job_type:
            wanted = filters.job_type.lower().strip()
            available = f"{job.job_type or ''} {job.title} {job.description}".lower()
            if job.job_type and wanted not in available:
                continue

        if filters.keywords:
            terms = [t for t in filters.keywords.lower().split() if len(t) > 2]
            blob = f"{job.title} {job.company} {job.description}".lower()
            if terms and not any(t in blob for t in terms):
                continue

        kept.append(job)

    return {
        "jobs": kept,
        "total_found": len(kept),
        "progress": f"{len(kept)} job(s) passed filters",
    }


def rank_jobs_node(state: SearchState) -> Dict[str, Any]:
    jobs: List[Job] = state.get("jobs") or []
    profile: CVProfile = state.get("profile") or CVProfile()
    ranked = rank_jobs(jobs, profile, state.get("cv_text", ""))
    return {
        "jobs": ranked,
        "total_found": len(ranked),
        "progress": f"ranked {len(ranked)} job(s)",
    }


# ==========================================================================
# 4. Content generators (cover letter, mock interview)
# ==========================================================================
_COVER_LETTER_PROMPT = """Write a cover letter for this candidate and job.

CANDIDATE
Name/summary: {summary}
Titles: {titles}
Key skills: {skills}
Experience: {experience}
Years of experience: {years}

JOB
Title: {job_title}
Company: {company}
Description: {job_description}

Rules:
- {language}, {tone} tone, 250-350 words.
- 3-4 paragraphs: hook, evidence from the candidate's real background, fit for
  this company, closing with a call to action.
- Reference only skills/experience actually listed above. Never invent employers,
  numbers or achievements.
- No placeholders like [Your Name] except a final signature line.
Return the letter text only."""


async def generate_cover_letter(
    profile: CVProfile,
    job_title: str,
    company: str = "",
    job_description: str = "",
    tone: str = "professional",
    language: str = "english",
) -> CoverLetterResponse:
    if not llm_client.enabled:
        raise LLMUnavailable(
            "Cover letter generation needs OPENROUTER_API_KEY. Set it in your .env file."
        )
    result = await llm_client.complete(
        _COVER_LETTER_PROMPT.format(
            summary=profile.summary or "(not provided)",
            titles=", ".join(profile.job_titles[:4]) or "(not provided)",
            skills=", ".join(profile.skills[:25]) or "(not provided)",
            experience=" | ".join(profile.experience[:5]) or "(not provided)",
            years=profile.years_experience or "unspecified",
            job_title=job_title,
            company=company or "the company",
            job_description=(job_description or "(no description provided)")[:3000],
            tone=tone,
            language=language,
        ),
        system="You are an expert career writer producing truthful, specific cover letters.",
        max_tokens=1200,
        temperature=0.6,
    )
    return CoverLetterResponse(cover_letter=result.text, model_used=result.model)


_INTERVIEW_PROMPT = """Generate {n} mock interview questions for this candidate/job pair.

CANDIDATE SKILLS: {skills}
CANDIDATE EXPERIENCE: {experience}
JOB TITLE: {job_title}
COMPANY: {company}
JOB DESCRIPTION: {job_description}

Return JSON: {{"questions": [
  {{"question": string,
    "category": "technical" | "behavioral" | "situational" | "experience" | "culture",
    "why_asked": string,
    "answer_hint": string}}
]}}

Mix categories. Probe the gaps between the candidate's background and the job.
Write in {language}."""


async def generate_mock_interview(
    profile: CVProfile,
    job_title: str,
    company: str = "",
    job_description: str = "",
    num_questions: int = 8,
    language: str = "english",
) -> MockInterviewResponse:
    if not llm_client.enabled:
        raise LLMUnavailable(
            "Mock interview generation needs OPENROUTER_API_KEY. Set it in your .env file."
        )
    data = await llm_client.complete_json(
        _INTERVIEW_PROMPT.format(
            n=num_questions,
            skills=", ".join(profile.skills[:25]) or "(not provided)",
            experience=" | ".join(profile.experience[:5]) or "(not provided)",
            job_title=job_title,
            company=company or "the company",
            job_description=(job_description or "(no description provided)")[:3000],
            language=language,
        ),
        system="You are a senior hiring manager. Output JSON only.",
        max_tokens=1800,
    )
    raw = data.get("questions") if isinstance(data, dict) else data
    questions: List[InterviewQuestion] = []
    for item in (raw or [])[:num_questions]:
        if isinstance(item, str):
            questions.append(InterviewQuestion(question=item))
        elif isinstance(item, dict) and item.get("question"):
            questions.append(
                InterviewQuestion(
                    question=str(item["question"]),
                    category=str(item.get("category") or "general"),
                    why_asked=str(item.get("why_asked") or ""),
                    answer_hint=str(item.get("answer_hint") or ""),
                )
            )
    if not questions:
        raise LLMUnavailable("Model returned no usable questions.")
    return MockInterviewResponse(questions=questions, model_used="openrouter")
