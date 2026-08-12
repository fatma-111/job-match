"""Normalisation helpers: dates, salaries, locations, dedup.

Rule from the spec: never fabricate. If a value cannot be parsed we return None.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from app.schemas import Job, RawJob

# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
_AR_NUM = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_RELATIVE_UNITS: Dict[str, float] = {
    "minute": 1 / 1440, "min": 1 / 1440, "دقيقة": 1 / 1440, "دقائق": 1 / 1440,
    "hour": 1 / 24, "hr": 1 / 24, "ساعة": 1 / 24, "ساعات": 1 / 24,
    "day": 1, "يوم": 1, "أيام": 1, "ايام": 1,
    "week": 7, "أسبوع": 7, "اسبوع": 7, "أسابيع": 7, "اسابيع": 7,
    "month": 30, "شهر": 30, "أشهر": 30, "اشهر": 30, "شهور": 30,
    "year": 365, "سنة": 365, "سنوات": 365,
}

_ABSOLUTE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y",
    "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%d.%m.%Y",
]


def parse_posted_date(
    text: Optional[str], now: Optional[datetime] = None
) -> Optional[datetime]:
    """Turn '3 days ago' / 'منذ 3 أيام' / '2026-05-01' into a datetime (UTC).

    Returns None when nothing reliable can be parsed.
    """
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    s = str(text).strip().translate(_AR_NUM).lower()
    if not s:
        return None

    # "today" / "just now" style
    if any(k in s for k in ("just now", "today", "النهارده", "اليوم", "الآن", "حالا")):
        return now
    if any(k in s for k in ("yesterday", "امبارح", "أمس", "امس")):
        return now - timedelta(days=1)

    # "30+ days ago"
    m = re.search(r"(\d+)\s*\+?\s*([a-z\u0600-\u06FF]+)", s)
    if m:
        qty = int(m.group(1))
        unit_word = m.group(2)
        for unit, days in _RELATIVE_UNITS.items():
            if unit_word.startswith(unit) or unit in unit_word:
                return now - timedelta(days=qty * days)

    # Arabic "منذ يوم" (no digit -> 1 unit)
    if "منذ" in s or "ago" in s:
        for unit, days in _RELATIVE_UNITS.items():
            if unit in s:
                return now - timedelta(days=days)

    # Absolute dates
    cleaned = re.sub(r"(posted|on|بتاريخ|نشرت)\s*", "", s).strip()
    for fmt in _ABSOLUTE_FORMATS:
        try:
            dt = datetime.strptime(cleaned[:24].strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Salary
# --------------------------------------------------------------------------
_CURRENCIES = {
    "egp": "EGP", "le": "EGP", "جنيه": "EGP", "ج.م": "EGP", "e£": "EGP",
    "usd": "USD", "$": "USD", "dollar": "USD", "دولار": "USD",
    "sar": "SAR", "ريال": "SAR", "aed": "AED", "درهم": "AED",
    "eur": "EUR", "€": "EUR", "gbp": "GBP", "£": "GBP",
    "kwd": "KWD", "qar": "QAR", "jod": "JOD",
}

_PERIODS = {
    "year": "yearly", "yr": "yearly", "annum": "yearly", "annually": "yearly", "سنوي": "yearly",
    "month": "monthly", "mo": "monthly", "شهري": "monthly", "شهر": "monthly",
    "week": "weekly", "أسبوعي": "weekly",
    "hour": "hourly", "hr": "hourly", "ساعة": "hourly",
    "day": "daily", "يومي": "daily",
}

_MULTIPLIERS = {"k": 1_000, "ألف": 1_000, "الف": 1_000, "m": 1_000_000, "مليون": 1_000_000}


def parse_salary(
    text: Optional[str],
) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """'15,000 - 20,000 EGP/month' -> (15000.0, 20000.0, 'EGP', 'monthly').

    Returns (None, None, None, None) when nothing usable is found — we never guess.
    """
    if not text:
        return None, None, None, None
    s = str(text).strip().translate(_AR_NUM).lower()
    if not s or any(
        k in s for k in ("confidential", "negotiable", "غير محدد", "سري", "not specified")
    ):
        return None, None, None, None

    currency = None
    for token, code in _CURRENCIES.items():
        if token in s:
            currency = code
            break

    period = None
    for token, norm in _PERIODS.items():
        if token in s:
            period = norm
            break

    # Numbers, possibly with k/m suffix.
    numbers: List[float] = []
    for match in re.finditer(r"(\d[\d,\.]*)\s*([km]|ألف|الف|مليون)?", s):
        raw = match.group(1).replace(",", "")
        if not raw or raw == ".":
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = match.group(2)
        if suffix and suffix in _MULTIPLIERS:
            value *= _MULTIPLIERS[suffix]
        # Skip year-like tokens that are clearly not salaries.
        if 1900 <= value <= 2100 and len(raw) == 4 and not suffix:
            continue
        if value <= 0:
            continue
        numbers.append(value)

    numbers = numbers[:2]
    if not numbers:
        return None, None, currency, period
    if len(numbers) == 1:
        return numbers[0], None, currency, period
    lo, hi = sorted(numbers)
    return lo, hi, currency, period


def monthly_equivalent(
    salary_min: Optional[float], period: Optional[str]
) -> Optional[float]:
    """Normalise a salary figure to a monthly value for comparable filtering."""
    if salary_min is None:
        return None
    factors = {
        "yearly": 1 / 12, "monthly": 1.0, "weekly": 4.33,
        "daily": 22.0, "hourly": 176.0,
    }
    return salary_min * factors.get(period or "monthly", 1.0)


# --------------------------------------------------------------------------
# URLs / dedup
# --------------------------------------------------------------------------
def canonical_url(url: str) -> str:
    """Strip tracking params + trailing slash so the same job dedupes correctly."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        path = parsed.path.rstrip("/")
        return urlunparse((parsed.scheme or "https", parsed.netloc.lower(), path, "", "", ""))
    except Exception:
        return url.strip()


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:32]


def job_fingerprint(job: Job) -> str:
    """Dedup key: canonical URL if present, else title+company+location."""
    if job.url:
        return url_hash(job.url)
    base = f"{job.title.lower().strip()}|{job.company.lower().strip()}|{job.location.lower().strip()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def normalize_job(raw: RawJob) -> Job:
    """RawJob (scraper output) -> Job (canonical shape)."""
    salary_min, salary_max, currency, period = parse_salary(raw.salary_text)
    posted = parse_posted_date(raw.posted_text)
    job = Job(
        title=clean_text(raw.title),
        company=clean_text(raw.company),
        location=clean_text(raw.location),
        url=raw.url.strip() if raw.url else "",
        description=clean_text(raw.description)[:6000],
        source=raw.source,
        job_type=clean_text(raw.job_type) or None,
        salary_text=clean_text(raw.salary_text) or None,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        salary_period=period,
        posted_text=clean_text(raw.posted_text) or None,
        posted_date=posted,
    )
    job.id = job_fingerprint(job)
    return job


def normalize_and_dedupe(raws: Iterable[RawJob]) -> List[Job]:
    seen: Dict[str, Job] = {}
    for raw in raws:
        if not (raw.title or raw.url):
            continue
        job = normalize_job(raw)
        existing = seen.get(job.id)
        if existing is None:
            seen[job.id] = job
        elif len(job.description) > len(existing.description):
            seen[job.id] = job  # keep the richer record
    return list(seen.values())
