"""Playwright scraping foundation: browser lifecycle, retries, delays, blocking.

Explicit non-goals (per spec §8): we never bypass authentication, CAPTCHAs or
any access control. When a site blocks automated access we raise ScraperBlocked,
the graph records it, and the other four sources continue unaffected.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence

from app.config import settings
from app.schemas import RawJob

logger = logging.getLogger(__name__)

SELECTOR_OVERRIDE_PATH = os.path.join(os.path.dirname(__file__), "selectors.json")

BLOCK_MARKERS = (
    "captcha", "are you a human", "verify you are human", "unusual traffic",
    "authwall", "please log in to continue", "access denied", "cf-challenge",
    "just a moment", "security check", "sign in to continue",
    "enable javascript and cookies",
)


class ScraperError(RuntimeError):
    """Generic scrape failure (navigation, timeout, parse)."""

    error_type = "scrape_error"


class ScraperBlocked(ScraperError):
    """Site actively blocked automated access (bot wall / login wall / CAPTCHA)."""

    error_type = "blocked"


class ScraperUnavailable(ScraperError):
    """Playwright itself is unavailable (browser not installed, no sandbox)."""

    error_type = "unavailable"


def load_selector_overrides() -> Dict[str, Any]:
    """Optional app/scrapers/selectors.json lets you fix selectors without a code change."""
    try:
        if os.path.exists(SELECTOR_OVERRIDE_PATH):
            with open(SELECTOR_OVERRIDE_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read selector overrides: %s", exc)
    return {}


class BrowserSession:
    """One browser for the whole search; each scraper gets its own context/page."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None

    async def __aenter__(self) -> "BrowserSession":
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise ScraperUnavailable(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            ) from exc

        try:
            self._playwright = await async_playwright().start()
            launch_args: Dict[str, Any] = {
                "headless": settings.scraper_headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            }
            if settings.scraper_proxy:
                launch_args["proxy"] = {"server": settings.scraper_proxy}
            self._browser = await self._playwright.chromium.launch(**launch_args)
        except Exception as exc:  # noqa: BLE001
            await self.close()
            raise ScraperUnavailable(
                f"Could not launch Chromium: {exc}. Run 'playwright install chromium'."
            ) from exc
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    async def close(self) -> None:
        for closer in (self._browser, self._playwright):
            if closer is None:
                continue
            try:
                if hasattr(closer, "close"):
                    await closer.close()
                elif hasattr(closer, "stop"):
                    await closer.stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error during browser teardown: %s", exc)
        self._browser = None
        self._playwright = None

    async def new_page(self):
        if self._browser is None:
            raise ScraperUnavailable("Browser session is not started.")
        context = await self._browser.new_context(
            user_agent=settings.scraper_user_agent,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            java_script_enabled=True,
            ignore_https_errors=True,
        )
        # Light stealth: hide the obvious webdriver flag. Not an anti-bot bypass.
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()
        page.set_default_timeout(settings.scraper_timeout_ms)
        return page, context


class BaseScraper(ABC):
    """Subclasses declare a source name, a URL builder and selectors."""

    source: str = "base"
    #: Selector groups. Each entry is a list tried in order (fallback chain).
    SELECTORS: Dict[str, List[str]] = {}
    requires_login: bool = False

    def __init__(self, session: Optional[BrowserSession] = None) -> None:
        self.session = session
        overrides = load_selector_overrides().get(self.source, {})
        self.selectors = {**self.SELECTORS}
        for key, value in overrides.items():
            self.selectors[key] = value if isinstance(value, list) else [value]

    # ---------------- hooks for subclasses ----------------
    @abstractmethod
    def build_url(self, query: str, location: str = "", page_num: int = 0) -> str:
        ...

    async def pre_scrape(self, page) -> None:
        """Optional per-site setup (cookie banners etc.)."""
        return None

    def absolute_url(self, href: str) -> str:
        return href

    # ---------------- shared machinery ----------------
    async def _human_delay(self) -> None:
        await asyncio.sleep(
            random.uniform(
                settings.scraper_min_delay_ms / 1000, settings.scraper_max_delay_ms / 1000
            )
        )

    @staticmethod
    async def _first_text(element, selectors: Sequence[str]) -> str:
        for selector in selectors or []:
            try:
                node = await element.query_selector(selector)
                if node:
                    text = (await node.inner_text()) or ""
                    if text.strip():
                        return text.strip()
            except Exception:  # noqa: BLE001 - selector may be invalid on this layout
                continue
        return ""

    @staticmethod
    async def _first_attr(element, selectors: Sequence[str], attr: str = "href") -> str:
        for selector in selectors or []:
            try:
                node = await element.query_selector(selector)
                if node:
                    value = await node.get_attribute(attr)
                    if value:
                        return value.strip()
            except Exception:  # noqa: BLE001
                continue
        return ""

    async def _detect_block(self, page) -> None:
        try:
            content = (await page.content())[:20000].lower()
        except Exception:  # noqa: BLE001
            return
        for marker in BLOCK_MARKERS:
            if marker in content:
                raise ScraperBlocked(
                    f"{self.source}: automated access blocked ('{marker}'). "
                    "Not attempting to bypass — use an official API or search manually."
                )

    async def _find_cards(self, page) -> List[Any]:
        """Try each card selector until one yields results."""
        for selector in self.selectors.get("card", []):
            try:
                await page.wait_for_selector(selector, timeout=8000)
            except Exception:  # noqa: BLE001
                continue
            cards = await page.query_selector_all(selector)
            if cards:
                logger.info("%s: %d cards via '%s'", self.source, len(cards), selector)
                return cards
        return []

    async def parse_card(self, card) -> Optional[RawJob]:
        """Default card parser driven entirely by the selector table."""
        title = await self._first_text(card, self.selectors.get("title", []))
        if not title:
            return None
        url = await self._first_attr(card, self.selectors.get("url", []) or self.selectors.get("title", []))
        return RawJob(
            title=title,
            company=await self._first_text(card, self.selectors.get("company", [])),
            location=await self._first_text(card, self.selectors.get("location", [])),
            url=self.absolute_url(url),
            description=await self._first_text(card, self.selectors.get("description", [])),
            salary_text=await self._first_text(card, self.selectors.get("salary", [])) or None,
            posted_text=await self._first_text(card, self.selectors.get("posted", [])) or None,
            job_type=await self._first_text(card, self.selectors.get("job_type", [])) or None,
            source=self.source,
        )

    async def search(
        self, query: str, location: str = "", limit: Optional[int] = None
    ) -> List[RawJob]:
        """Navigate, parse and return raw jobs. Retries transient failures."""
        limit = limit or settings.scraper_max_results_per_source
        if self.session is None:
            raise ScraperUnavailable(f"{self.source}: no browser session provided.")

        url = self.build_url(query, location)
        last_error: Optional[Exception] = None

        for attempt in range(settings.scraper_max_retries + 1):
            page = context = None
            try:
                page, context = await self.session.new_page()
                logger.info("%s: attempt %d -> %s", self.source, attempt + 1, url)
                response = await page.goto(url, wait_until="domcontentloaded")
                if response is not None and response.status in (403, 429, 503):
                    raise ScraperBlocked(
                        f"{self.source}: HTTP {response.status} — automated access refused."
                    )
                await self.pre_scrape(page)
                await self._human_delay()
                await self._detect_block(page)

                cards = await self._find_cards(page)
                if not cards:
                    raise ScraperError(
                        f"{self.source}: no job cards matched the configured selectors. "
                        "The page layout likely changed — update app/scrapers/selectors.json."
                    )

                jobs: List[RawJob] = []
                seen_urls = set()
                for card in cards[: limit * 2]:
                    try:
                        job = await self.parse_card(card)
                    except Exception as exc:  # noqa: BLE001 - skip bad card, keep going
                        logger.debug("%s: card parse error %s", self.source, exc)
                        continue
                    if not job or not job.title:
                        continue
                    key = (job.url or f"{job.title}|{job.company}").lower()
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    jobs.append(job)
                    if len(jobs) >= limit:
                        break
                return jobs

            except ScraperBlocked:
                raise  # never retry a block — that would be hammering the site
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("%s attempt %d failed: %s", self.source, attempt + 1, exc)
                if attempt < settings.scraper_max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
            finally:
                for closeable in (page, context):
                    try:
                        if closeable:
                            await closeable.close()
                    except Exception:  # noqa: BLE001
                        pass

        raise ScraperError(f"{self.source}: {last_error}")
