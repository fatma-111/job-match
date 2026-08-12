"""LangGraph state definition for the job search pipeline."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from app.schemas import CVProfile, Job, RawJob, SearchFilters, SourceError


def _merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    return {**(left or {}), **(right or {})}


class SearchState(TypedDict, total=False):
    """Shared state across the graph.

    `raw_jobs` and `errors` use operator.add reducers so the five parallel
    scraper nodes can each append without clobbering one another.
    """

    # inputs
    cv_id: str
    cv_text: str
    profile: CVProfile
    filters: SearchFilters

    # derived
    query: str
    location: str
    sources: List[str]

    # fan-out results (concurrent writes -> additive reducers)
    raw_jobs: Annotated[List[RawJob], operator.add]
    errors: Annotated[List[SourceError], operator.add]
    source_stats: Annotated[Dict[str, Any], _merge_dicts]

    # fan-in results
    jobs: List[Job]
    total_found: int

    # runtime handles (not serialised)
    browser: Optional[Any]
    browser_error: str
    progress: str
