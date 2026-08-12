"""Wuzzuf (Egypt) scraper."""
from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from app.scrapers.base import BaseScraper

BASE = "https://wuzzuf.net"


class WuzzufScraper(BaseScraper):
    source = "wuzzuf"

    SELECTORS = {
        "card": [
            "div.css-1gatmva",
            "div[class*='css-pkv5jc']",
            "div.css-1gatmva.e1v1l3u10",
            "div[data-testid='job-card']",
            "div.job-card",
        ],
        "title": ["h2.css-m604qf a", "h2 a", "a[href*='/jobs/p/']", "h2"],
        "url": ["h2.css-m604qf a", "h2 a", "a[href*='/jobs/p/']"],
        "company": ["a.css-17s97q8", "div.css-d7j1kk a", "a[href*='/jobs/careers/']"],
        "location": ["span.css-5wys0k", "span.css-1ve4b75", "div.css-d7j1kk span"],
        "posted": ["div.css-4c4ojb", "div.css-do6t5g", "div[class*='css-4c4ojb']"],
        "job_type": ["a.css-n2jc4m", "span.css-1ve4b75"],
        "salary": ["div.css-1kdxlk8", "span[class*='salary']"],
        "description": ["div.css-y4udm8", "div.css-vqbtu2"],
    }

    def build_url(self, query: str, location: str = "", page_num: int = 0) -> str:
        params = [f"q={quote_plus(query or '')}"]
        if location:
            params.append(f"filters%5Bcountry%5D%5B0%5D={quote_plus(location)}")
        if page_num:
            params.append(f"start={page_num}")
        return f"{BASE}/search/jobs/?" + "&".join(params)

    def absolute_url(self, href: str) -> str:
        if not href:
            return ""
        return href if href.startswith("http") else urljoin(BASE, href)

    async def pre_scrape(self, page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
