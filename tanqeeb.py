"""Tanqeeb (MENA job aggregator) scraper."""
from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from app.scrapers.base import BaseScraper

BASE = "https://egypt.tanqeeb.com"


class TanqeebScraper(BaseScraper):
    source = "tanqeeb"

    SELECTORS = {
        "card": [
            "div.job-item",
            "div.card.job-card",
            "div[class*='search-result']",
            "article.job",
        ],
        "title": ["h2 a", "h3 a", "a.job-title", "a[href*='/jobs/']"],
        "url": ["h2 a", "h3 a", "a.job-title", "a[href*='/jobs/']"],
        "company": ["a.company-name", "span.company", "div.company a", "h4"],
        "location": ["span.location", "div.location", "span[class*='city']"],
        "posted": ["span.date", "time", "span[class*='date']"],
        "salary": ["span.salary", "div[class*='salary']"],
        "description": ["div.job-description", "p.description"],
    }

    def build_url(self, query: str, location: str = "", page_num: int = 0) -> str:
        params = [f"keywords={quote_plus(query or '')}"]
        if location:
            params.append(f"location={quote_plus(location)}")
        if page_num:
            params.append(f"page={page_num + 1}")
        return f"{BASE}/jobs/search?" + "&".join(params)

    def absolute_url(self, href: str) -> str:
        if not href:
            return ""
        return href if href.startswith("http") else urljoin(BASE, href)
