"""LinkedIn scraper — public guest job search endpoint only.

Highest blocking risk of the five sources. We only ever request the public,
logged-out job listing page; we never log in, never store credentials and never
attempt to defeat the auth wall. If LinkedIn shows the authwall we surface a
clear source error and the other sources continue.
"""
from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from app.scrapers.base import BaseScraper

BASE = "https://www.linkedin.com"


class LinkedInScraper(BaseScraper):
    source = "linkedin"
    requires_login = False

    SELECTORS = {
        "card": [
            "div.base-card",
            "li div.base-search-card",
            "div.job-search-card",
            "ul.jobs-search__results-list li",
        ],
        "title": ["h3.base-search-card__title", "h3", "span.sr-only"],
        "url": ["a.base-card__full-link", "a.base-search-card__title-link", "a[href*='/jobs/view/']"],
        "company": ["h4.base-search-card__subtitle a", "h4.base-search-card__subtitle", "a.hidden-nested-link"],
        "location": ["span.job-search-card__location", "span[class*='location']"],
        "posted": ["time", "time.job-search-card__listdate", "time[class*='listdate']"],
        "salary": ["span.job-search-card__salary-info", "span[class*='salary']"],
        "description": ["p.job-search-card__snippet", "div.base-search-card__metadata"],
    }

    def build_url(self, query: str, location: str = "", page_num: int = 0) -> str:
        params = [f"keywords={quote_plus(query or '')}"]
        params.append(f"location={quote_plus(location or 'Egypt')}")
        params.append("f_TPR=r604800")  # last 7 days
        if page_num:
            params.append(f"start={page_num * 25}")
        return f"{BASE}/jobs/search?" + "&".join(params)

    def absolute_url(self, href: str) -> str:
        if not href:
            return ""
        return href if href.startswith("http") else urljoin(BASE, href)
