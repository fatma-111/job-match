"""SMTP email delivery for job alerts. Credentials come from env only."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from html import escape
from typing import List, Sequence

from app.config import settings
from app.schemas import Job

logger = logging.getLogger(__name__)


class EmailNotConfigured(RuntimeError):
    pass


def render_jobs_email(alert_name: str, jobs: Sequence[Job]) -> tuple[str, str]:
    """Returns (plain_text, html)."""
    lines: List[str] = [f"{len(jobs)} new job(s) matched your alert '{alert_name}':", ""]
    rows: List[str] = []
    for job in jobs:
        score = f"{job.match_score:.0f}%" if job.match_score is not None else "—"
        salary = job.salary_text or "Not listed"
        posted = job.posted_text or "Not listed"
        lines.append(f"• {job.title} — {job.company or 'Unknown'} ({job.source})")
        lines.append(f"  Match {score} | {job.location or 'Location not listed'} | Salary: {salary}")
        if job.matching_skills:
            lines.append(f"  Matching: {', '.join(job.matching_skills[:6])}")
        if job.missing_skills:
            lines.append(f"  Missing: {', '.join(job.missing_skills[:6])}")
        lines.append(f"  {job.url}")
        lines.append("")
        rows.append(
            f"""
            <tr>
              <td style="padding:12px;border-bottom:1px solid #eee">
                <a href="{escape(job.url)}" style="font-weight:600;color:#1a56db;text-decoration:none">
                  {escape(job.title)}</a>
                <div style="color:#555;font-size:13px;margin-top:2px">
                  {escape(job.company or 'Unknown')} · {escape(job.location or '—')} · {escape(job.source)}
                </div>
                <div style="color:#777;font-size:12px;margin-top:4px">
                  Match {escape(score)} · Salary: {escape(salary)} · Posted: {escape(posted)}
                </div>
              </td>
            </tr>"""
        )

    html = f"""<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7f9;padding:24px">
      <div style="max-width:640px;margin:auto;background:#fff;border-radius:10px;overflow:hidden">
        <div style="padding:18px 20px;background:#111827;color:#fff">
          <h2 style="margin:0;font-size:17px">{len(jobs)} new job(s) — {escape(alert_name)}</h2>
        </div>
        <table style="width:100%;border-collapse:collapse">{''.join(rows)}</table>
        <div style="padding:14px 20px;color:#888;font-size:12px">
          Sent by your Job Matching Agent. Disable this alert in the Job Alerts tab.
        </div>
      </div></body></html>"""
    return "\n".join(lines), html


def _send_sync(to_email: str, subject: str, text: str, html: str) -> None:
    if not settings.smtp_configured:
        raise EmailNotConfigured(
            "SMTP is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL in .env."
        )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    if settings.smtp_port == 465:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    try:
        if settings.smtp_port != 465 and settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass


async def send_email(to_email: str, subject: str, text: str, html: str) -> None:
    """Run blocking smtplib off the event loop."""
    await asyncio.to_thread(_send_sync, to_email, subject, text, html)


async def send_job_alert_email(to_email: str, alert_name: str, jobs: Sequence[Job]) -> None:
    text, html = render_jobs_email(alert_name, jobs)
    subject = f"{len(jobs)} new job match{'es' if len(jobs) != 1 else ''} — {alert_name}"
    await send_email(to_email, subject, text, html)
    logger.info("Alert email sent to %s (%d jobs)", to_email, len(jobs))
