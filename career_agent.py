"""Career Agent — tool-calling chat over the user's own job-search data.

Strategy (matches the plan's "free models only" decision):
  1. Try native OpenRouter tool-calling with the five tools.
  2. If the model chain doesn't support tools or returns nothing useful, fall
     back to a context-injection pass where the tool outputs are pre-computed
     and embedded in the system prompt. That keeps answers grounded even on
     free models with unreliable function calling.

Conversation history is persisted in SQLite (career_chat_sessions /
career_chat_messages) so a session survives a browser restart.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Tuple

import httpx
from sqlalchemy.orm import Session

from app import crud
from app.schemas import CareerChatResponse
from app.services.llm_client import LLMUnavailable, llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a pragmatic career coach embedded in a job-matching app.

You can see the user's CV, their matched jobs, their skill-gap analysis and their
application tracker. Ground every answer in that data — quote real job titles,
companies and skills. If the data is empty, say so and tell them which tab to
use (Job Search, Skill Gap, My Applications) instead of inventing facts.

Be concise and concrete. Prefer short paragraphs and bullets. Never invent
salary figures, employers or interview outcomes."""


# ==========================================================================
# Tools
# ==========================================================================
def _tool_get_my_cv_summary(db: Session, cv_id: str, **_: Any) -> Dict[str, Any]:
    cv = crud.get_cv(db, cv_id)
    if not cv:
        return {"error": "No CV found. Upload one in the Job Search tab."}
    profile = crud.cv_to_profile(cv)
    return {
        "summary": profile.summary,
        "job_titles": profile.job_titles,
        "skills": profile.skills[:30],
        "years_experience": profile.years_experience,
        "education": profile.education,
        "certifications": profile.certifications,
    }


def _tool_get_recent_job_matches(db: Session, cv_id: str, limit: int = 8, **_: Any) -> Dict[str, Any]:
    jobs = crud.latest_search_results(db, cv_id)
    if not jobs:
        return {"jobs": [], "note": "No saved search yet — run a search first."}
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 8
    return {
        "jobs": [
            {
                "title": j.title,
                "company": j.company,
                "source": j.source,
                "location": j.location,
                "match_score": j.match_score,
                "matching_skills": j.matching_skills[:6],
                "missing_skills": j.missing_skills[:6],
                "url": j.url,
            }
            for j in jobs[:limit]
        ]
    }


def _tool_get_skill_gap_summary(db: Session, cv_id: str, **_: Any) -> Dict[str, Any]:
    report = crud.latest_skill_gap(db, cv_id, aggregate=True)
    if not report:
        report = crud.latest_skill_gap(db, cv_id, aggregate=False)
    if not report:
        return {"note": "No skill-gap analysis stored yet — run one in the Skill Gap tab."}
    return report


def _tool_get_application_stats(db: Session, cv_id: str, **_: Any) -> Dict[str, Any]:
    return crud.application_stats(db, cv_id)


async def _tool_web_search_salary(db: Session, cv_id: str, role: str = "", location: str = "", **_: Any) -> Dict[str, Any]:
    """Best-effort public salary lookup. Returns a clear note when unavailable."""
    query = f"average salary {role} {location}".strip()
    if not role:
        return {"error": "Provide a role to search salaries for."}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            import re

            snippets = re.findall(
                r'<a class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.S
            )[:4]
            cleaned = [re.sub(r"<[^>]+>", "", s).strip()[:300] for s in snippets]
            if not cleaned:
                raise ValueError("no snippets")
            return {"query": query, "results": cleaned}
    except Exception as exc:  # noqa: BLE001
        logger.info("Salary search unavailable: %s", exc)
        return {
            "query": query,
            "error": "Live salary search is unavailable in this environment.",
            "guidance": (
                "Suggest the user check Wuzzuf salary insights, Glassdoor or Bayt "
                "salary tools for this role, and reason from the salary ranges "
                "visible in their own matched jobs instead."
            ),
        }


TOOL_IMPLEMENTATIONS: Dict[str, Callable[..., Any]] = {
    "get_my_cv_summary": _tool_get_my_cv_summary,
    "get_recent_job_matches": _tool_get_recent_job_matches,
    "get_skill_gap_summary": _tool_get_skill_gap_summary,
    "get_application_stats": _tool_get_application_stats,
    "web_search_salary": _tool_web_search_salary,
}

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_my_cv_summary",
            "description": "Get the user's parsed CV: skills, titles, education, years of experience.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_job_matches",
            "description": "Get the user's most recent ranked job matches with match scores and skill overlap.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "How many jobs to return (1-20)."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_skill_gap_summary",
            "description": "Get the latest skill-gap report: most common missing skills and learning priorities.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_application_stats",
            "description": "Get application tracker stats: totals per status, companies interviewing with.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_salary",
            "description": "Look up public salary information for a role and location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["role"],
            },
        },
    },
]


async def _run_tool(name: str, db: Session, cv_id: str, args: Dict[str, Any]) -> Any:
    impl = TOOL_IMPLEMENTATIONS.get(name)
    if impl is None:
        return {"error": f"Unknown tool '{name}'"}
    try:
        if name == "web_search_salary":
            return await impl(db, cv_id, **args)
        return impl(db, cv_id, **args)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tool %s failed: %s", name, exc)
        return {"error": f"Tool '{name}' failed: {exc}"}


def _gather_context(db: Session, cv_id: str) -> Dict[str, Any]:
    """Pre-compute every tool output for the no-tool-calling fallback path."""
    return {
        "cv": _tool_get_my_cv_summary(db, cv_id),
        "recent_matches": _tool_get_recent_job_matches(db, cv_id, limit=8),
        "skill_gap": _tool_get_skill_gap_summary(db, cv_id),
        "applications": _tool_get_application_stats(db, cv_id),
    }


# ==========================================================================
# Entry point
# ==========================================================================
async def chat(
    db: Session, cv_id: str, session_id: str, user_message: str, max_iterations: int = 3
) -> CareerChatResponse:
    session_row = crud.get_or_create_chat_session(db, cv_id, session_id)
    history = crud.get_chat_history(db, session_row, limit=16)
    crud.add_chat_message(db, session_row, "user", user_message)

    if not llm_client.enabled:
        reply = (
            "The Career Agent needs an OpenRouter API key. Add OPENROUTER_API_KEY "
            "to your .env file and restart the backend, then I can answer questions "
            "about your matches, skill gaps and applications."
        )
        crud.add_chat_message(db, session_row, "assistant", reply, [])
        return CareerChatResponse(session_id=session_id, reply=reply, tools_used=[])

    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history:
        if msg.role in ("user", "assistant"):
            messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    tools_used: List[str] = []
    reply = ""
    model_used = ""

    # ---- Path 1: native tool calling ----
    try:
        working = list(messages)
        for _ in range(max_iterations):
            message, model_used = await llm_client.complete_message(
                working, tools=TOOL_SCHEMAS, max_tokens=1200
            )
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                reply = (message.get("content") or "").strip()
                break

            working.append(message)
            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await _run_tool(name, db, cv_id, args)
                tools_used.append(name)
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", name),
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False, default=str)[:6000],
                    }
                )
    except LLMUnavailable as exc:
        logger.info("Tool-calling path unavailable (%s) — using context injection", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tool-calling path failed (%s) — using context injection", exc)

    # ---- Path 2: context injection fallback ----
    if not reply:
        context = _gather_context(db, cv_id)
        tools_used = sorted(TOOL_IMPLEMENTATIONS.keys() - {"web_search_salary"})
        grounded = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
                + "\n\nHere is the user's live data (JSON):\n"
                + json.dumps(context, ensure_ascii=False, default=str)[:8000],
            }
        ] + messages[1:]
        try:
            result = await llm_client.complete(
                "", messages=grounded, max_tokens=1200, temperature=0.5
            )
            reply, model_used = result.text, result.model
        except LLMUnavailable as exc:
            reply = (
                "I couldn't reach any language model right now "
                f"({str(exc)[:120]}). Your data is safe — try again in a minute."
            )

    crud.add_chat_message(db, session_row, "assistant", reply, tools_used)
    return CareerChatResponse(
        session_id=session_id,
        reply=reply,
        tools_used=list(dict.fromkeys(tools_used)),
        model_used=model_used,
    )
