"""Builds the LangGraph search pipeline (fan-out / fan-in).

        build_search_query
               |
      -------- fan-out --------
      |    |     |     |     |
   wuzzuf bayt tanqeeb indeed linkedin      (parallel, independent)
      |    |     |     |     |
      -------- fan-in ---------
               |
          normalize_jobs
               |
           filter_jobs
               |
           rank_jobs
               |
              END
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph

from app.agents.nodes import (
    build_search_query,
    filter_jobs,
    make_scraper_node,
    normalize_jobs,
    rank_jobs_node,
)
from app.agents.state import SearchState
from app.config import settings
from app.schemas import CVProfile, SearchFilters
from app.scrapers.base import BrowserSession, ScraperUnavailable
from app.scrapers.registry import ALL_SOURCES

logger = logging.getLogger(__name__)

_compiled = None


def build_graph():
    """Compile the graph once and reuse it."""
    graph = StateGraph(SearchState)

    graph.add_node("build_search_query", build_search_query)
    for source in ALL_SOURCES:
        graph.add_node(f"scrape_{source}", make_scraper_node(source))
    graph.add_node("normalize_jobs", normalize_jobs)
    graph.add_node("filter_jobs", filter_jobs)
    graph.add_node("rank_jobs", rank_jobs_node)

    graph.set_entry_point("build_search_query")

    # fan-out
    for source in ALL_SOURCES:
        graph.add_edge("build_search_query", f"scrape_{source}")
    # fan-in — normalize waits for every scraper branch
    for source in ALL_SOURCES:
        graph.add_edge(f"scrape_{source}", "normalize_jobs")

    graph.add_edge("normalize_jobs", "filter_jobs")
    graph.add_edge("filter_jobs", "rank_jobs")
    graph.add_edge("rank_jobs", END)

    return graph.compile()


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


async def run_job_search(
    profile: CVProfile,
    filters: SearchFilters,
    cv_text: str = "",
    cv_id: str = "",
) -> Dict[str, Any]:
    """Run the full pipeline with a managed browser session.

    Always returns a dict — a total scraping outage yields empty results plus
    a populated `errors` list rather than an exception.
    """
    initial: Dict[str, Any] = {
        "cv_id": cv_id,
        "cv_text": cv_text,
        "profile": profile,
        "filters": filters,
        "raw_jobs": [],
        "errors": [],
        "source_stats": {},
        "jobs": [],
    }

    session: Optional[BrowserSession] = None
    try:
        session = await BrowserSession().__aenter__()
        initial["browser"] = session
    except ScraperUnavailable as exc:
        # Each scraper node reports this once, so we don't double-count errors.
        logger.error("Browser unavailable: %s", exc)
        initial["browser"] = None
        initial["browser_error"] = str(exc)

    try:
        result = await get_graph().ainvoke(initial)
    except Exception as exc:  # noqa: BLE001 - graph-level safety net
        logger.exception("Graph execution failed")
        from app.schemas import SourceError

        result = {
            **initial,
            "jobs": [],
            "total_found": 0,
            "errors": list(initial.get("errors", []))
            + [SourceError(source="pipeline", error=str(exc)[:500], error_type="pipeline_error")],
        }
    finally:
        if session is not None:
            await session.close()

    result.pop("browser", None)
    return result
