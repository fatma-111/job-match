"""Maps source names to scraper classes."""
from __future__ import annotations

from typing import Dict, List, Type

from app.scrapers.base import BaseScraper
from app.scrapers.bayt import BaytScraper
from app.scrapers.indeed import IndeedScraper
from app.scrapers.linkedin import LinkedInScraper
from app.scrapers.tanqeeb import TanqeebScraper
from app.scrapers.wuzzuf import WuzzufScraper

SCRAPERS: Dict[str, Type[BaseScraper]] = {
    WuzzufScraper.source: WuzzufScraper,
    BaytScraper.source: BaytScraper,
    TanqeebScraper.source: TanqeebScraper,
    IndeedScraper.source: IndeedScraper,
    LinkedInScraper.source: LinkedInScraper,
}

ALL_SOURCES: List[str] = list(SCRAPERS.keys())


def get_scraper_class(source: str) -> Type[BaseScraper]:
    try:
        return SCRAPERS[source.lower()]
    except KeyError as exc:
        raise ValueError(f"Unknown source '{source}'. Known: {ALL_SOURCES}") from exc
