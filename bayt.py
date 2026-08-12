"""Bayt.com (MENA) scraper."""
from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from app.scrapers.base import BaseScraper

BASE = "https://www.bayt.com"


class BaytScraper(BaseScraper):
    source = "bayt"

    SELECTORS = {
        "card": [
            "li[data-js-job]",
            "div.card.is-spaced",
            "li.has-pointer-d",
            "div[data-automation-id='job-card']",
        ],
        "title": ["h2.jb-title a", "h2 a", "a[data-js-aid='jobID']", "h2"],
        "url": ["h2.jb-title a", "h2 a", "a[data-js-aid='jobID']"],
        "company": ["b.jb-company", "div.t-nowrap a", "span.jb-company", "a[href*='/companies/']"],
        "location": ["div.t-mute.t-small", "span.jb-loc", "div.u-stretch span"],
        "posted": ["span[data-automation-id='job-active-date']", "div.u-stretch + div", "span.u-text-muted"],
        "salary": ["div.jb-salary", "span[class*='salary']"],
        "description": ["div.jb-descr", "div.card-content p"],
    }

    def build_url(self, query: str, location: str = "", page_num: int = 0) -> str:
        slug = quote_plus((query or "jobs").strip().replace(" ", "-"))
        url = f"{BASE}/en/jobs/{slug}-jobs/"
        if location:
            url = f"{BASE}/en/{quote_plus(location.lower().replace(' ', '-'))}/jobs/{slug}-jobs/"
        if page_num:
            url += f"?page={page_num + 1}"
        return url

    def absolute_url(self, href: str) -> str:
        if not href:
            return ""
        return href if href.startswith("http") else urljoin(BASE, href)
