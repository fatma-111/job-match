"""Skill Gap Analyzer — per-job and aggregated across many jobs.

Two levels (per project plan §9.3):
  1. analyze_skill_gap()    — one job (LLM-enriched, deterministic fallback)
  2. aggregate_skill_gaps() — N jobs, frequency-counted with Counter
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Dict, List, Optional, Sequence

from app.schemas import (
    AggregateSkillGapResponse,
    CVProfile,
    Job,
    SkillCount,
    SkillGapResponse,
)
from app.services.llm_client import LLMUnavailable, llm_client
from app.services.matching import compare_skills
from app.services.skills_taxonomy import SOFT_SKILLS, canonicalize

logger = logging.getLogger(__name__)

_GAP_PROMPT = """Compare a candidate's skills to a job posting.

CANDIDATE SKILLS: {cv_skills}
CANDIDATE SUMMARY: {cv_summary}

JOB TITLE: {job_title}
JOB DESCRIPTION:
{job_description}

Return JSON:
{{
  "matching_skills": [string],   // candidate skills the job explicitly wants
  "missing_skills": [string],    // job requirements the candidate lacks, max 12
  "explanation": string          // 2-3 sentences: readiness + what to learn first
}}

Only list skills actually mentioned in the job description. No invented skills.
Do NOT output any numeric score."""


def _gap_score(matching: Sequence[str], missing: Sequence[str]) -> float:
    """Deterministic 0-100 gap score. 0 = no gap, 100 = nothing matches.

    Soft skills are weighted at 40% since they're rarely the true blocker.
    """
    def weight(skill: str) -> float:
        return 0.4 if skill in SOFT_SKILLS else 1.0

    matched = sum(weight(s) for s in matching)
    missed = sum(weight(s) for s in missing)
    total = matched + missed
    if total == 0:
        return 0.0
    return round((missed / total) * 100, 1)


async def analyze_skill_gap(
    profile: CVProfile,
    job_title: str,
    job_description: str,
    job_url: str = "",
) -> SkillGapResponse:
    """Analyse one job. Always returns a result — LLM is an enhancement, not a requirement."""
    job_text = f"{job_title}\n{job_description}"
    matching, missing = compare_skills(profile.skills, job_text)
    method = "heuristic"
    explanation = ""

    if llm_client.enabled and job_description.strip():
        try:
            data = await llm_client.complete_json(
                _GAP_PROMPT.format(
                    cv_skills=", ".join(profile.skills[:40]) or "(none extracted)",
                    cv_summary=profile.summary[:400] or "(no summary)",
                    job_title=job_title,
                    job_description=job_description[:4000],
                ),
                system="You are a career coach doing precise skill-gap analysis.",
                max_tokens=900,
            )
            if isinstance(data, dict):
                llm_matching = [
                    canonicalize(str(s)) for s in (data.get("matching_skills") or []) if s
                ]
                llm_missing = [
                    canonicalize(str(s)) for s in (data.get("missing_skills") or []) if s
                ]
                explanation = str(data.get("explanation") or "")[:800]
                # Union with the deterministic scan, keeping order + uniqueness.
                matching = list(dict.fromkeys(matching + llm_matching))
                cv_lower = {s.lower() for s in profile.skills}
                missing = [
                    s for s in dict.fromkeys(missing + llm_missing)
                    if s.lower() not in cv_lower and s not in matching
                ]
                method = "llm"
        except (LLMUnavailable, ValueError, TypeError) as exc:
            logger.warning("LLM skill gap failed (%s) — heuristic result kept", exc)

    score = _gap_score(matching, missing)

    if not explanation:
        hard = [m for m in missing if m not in SOFT_SKILLS]
        if score < 25:
            explanation = (
                f"You cover most requirements for {job_title}. "
                + (f"Brush up on {', '.join(hard[:3])}." if hard else "No significant gaps found.")
            )
        elif score < 60:
            explanation = (
                f"Solid partial fit for {job_title}. "
                f"Closing {', '.join(hard[:3]) or 'the listed gaps'} would make you competitive."
            )
        else:
            explanation = (
                f"Significant gap for {job_title}. "
                f"Priority to learn: {', '.join(hard[:4]) or 'the core requirements listed'}."
            )

    return SkillGapResponse(
        job_title=job_title,
        job_url=job_url,
        matching_skills=matching[:25],
        missing_skills=missing[:25],
        gap_score=score,
        explanation=explanation,
        method=method,
    )


async def aggregate_skill_gaps(
    profile: CVProfile,
    jobs: Sequence[Job],
    top_n: int = 10,
    concurrency: int = 3,
) -> AggregateSkillGapResponse:
    """Run the per-job analysis across the top N jobs and count frequencies.

    Uses bounded concurrency (asyncio.Semaphore) — the improvement flagged in
    §9.3 of the plan — while staying gentle on free-tier rate limits.
    """
    selected = list(jobs)[:top_n]
    if not selected:
        return AggregateSkillGapResponse(
            jobs_analyzed=0, summary="No jobs supplied for aggregate analysis."
        )

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(job: Job) -> Optional[SkillGapResponse]:
        async with semaphore:
            try:
                return await analyze_skill_gap(
                    profile, job.title, job.description, job.url
                )
            except Exception as exc:  # noqa: BLE001 - one job must not kill the batch
                logger.warning("Skill gap failed for '%s': %s", job.title, exc)
                return None

    results = [r for r in await asyncio.gather(*(_one(j) for j in selected)) if r]
    if not results:
        return AggregateSkillGapResponse(
            jobs_analyzed=0, summary="All per-job analyses failed."
        )

    missing_counter: Counter[str] = Counter()
    matching_counter: Counter[str] = Counter()
    for report in results:
        # list(dict.fromkeys(...)) = unique-per-job, order preserved,
        # so one job can only contribute +1 to any skill's count.
        missing_counter.update(list(dict.fromkeys(report.missing_skills)))
        matching_counter.update(list(dict.fromkeys(report.matching_skills)))

    total = len(results)

    def to_counts(counter: Counter, limit: int = 15) -> List[SkillCount]:
        return [
            SkillCount(skill=skill, count=count, percentage=round(count / total * 100, 1))
            for skill, count in counter.most_common(limit)
        ]

    top_missing = to_counts(missing_counter)
    average_gap = round(sum(r.gap_score for r in results) / total, 1)

    # Learning priorities: most frequent hard skills first.
    priorities = [
        sc.skill for sc in top_missing if sc.skill not in SOFT_SKILLS
    ][:5]

    summary_bits = [f"Analysed {total} job(s). Average gap score {average_gap}%."]
    if priorities:
        summary_bits.append(
            "Most requested skills you're missing: " + ", ".join(priorities) + "."
        )
    if matching_counter:
        strengths = [s for s, _ in matching_counter.most_common(4)]
        summary_bits.append("Your strongest recurring match: " + ", ".join(strengths) + ".")

    return AggregateSkillGapResponse(
        jobs_analyzed=total,
        top_missing_skills=top_missing,
        top_matching_skills=to_counts(matching_counter),
        average_gap_score=average_gap,
        learning_priorities=priorities,
        summary=" ".join(summary_bits),
    )
