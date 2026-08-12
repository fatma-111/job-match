"""Indeed scraper.

Indeed runs aggressive bot protection (Cloudflare). We detect the challenge and
report it as a source error rather than attempting any bypass.
"""
from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from app.scrapers.base import BaseScraper

BASE = "https://eg.indeed.com"


class IndeedScraper(BaseScraper):
    source = "indeed"

    SELECTORS = {
        "card": [
            "div.job_seen_beacon",
            "div[data-testid='slider_item']",
            "td.resultContent",
            "a.tapItem",
        ],
        "title": ["h2.jobTitle span[title]", "h2.jobTitle a span", "h2.jobTitle", "a.jcs-JobTitle span"],
        "url": ["h2.jobTitle a", "a.jcs-JobTitle", "a[data-jk]"],
        "company": ["span[data-testid='company-name']", "span.companyName", "div.company_location span"],
        "location": ["div[data-testid='text-location']", "div.companyLocation", "div.company_location div"],
        "posted": ["span[data-testid='myJobsStateDate']", "span.date", "span[class*='date']"],
        "salary": ["div[data-testid='attribute_snippet_testid']", "div.salary-snippet-container", "div.metadata.salary-snippet-container"],
        "description": ["div[data-testid='jobsnippet_footer']", "div.job-snippet", "ul"],
    }

    def build_url(self, query: str, location: str = "", page_num: int = 0) -> str:
        params = [f"q={quote_plus(query or '')}"]
        if location:
            params.append(f"l={quote_plus(location)}")
        if page_num:
            params.append(f"start={page_num * 10}")
        return f"{BASE}/jobs?" + "&".join(params)

    def absolute_url(self, href: str) -> str:
        if not href:
            return ""
        return href if href.startswith("http") else urljoin(BASE, href)
