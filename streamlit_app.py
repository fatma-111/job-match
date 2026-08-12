"""Job Matching Agent — Streamlit front end.

Design direction: an instrument panel, not a marketing page. Match scores are
measurements, so they're set in a monospace face with a thin readout bar; every
other element stays quiet so the numbers carry the page.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
API = f"{BACKEND_URL}/api/v1"
REQUEST_TIMEOUT = 120

st.set_page_config(
    page_title="Job Matching Agent",
    page_icon="◎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------
# Visual system
# --------------------------------------------------------------------------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --ink:#101828; --muted:#667085; --line:#DFE4EA;
  --canvas:#EEF2F6; --surface:#FFFFFF;
  --signal:#0F6FDE; --good:#0E9F6E; --warn:#B54708; --cold:#98A2B3;
}
html, body, [class*="css"] { font-family:'Inter',system-ui,sans-serif; }
h1,h2,h3,h4 { font-family:'Space Grotesk',sans-serif !important; letter-spacing:-.02em; color:var(--ink); }
.stApp { background:var(--canvas); }
section[data-testid="stSidebar"] { background:var(--ink); }
section[data-testid="stSidebar"] * { color:#E7ECF2 !important; }

.masthead { font-family:'Space Grotesk',sans-serif; font-size:26px; font-weight:700;
  color:var(--ink); letter-spacing:-.03em; margin:0 0 2px; }
.masthead-sub { font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--muted);
  text-transform:uppercase; letter-spacing:.14em; margin-bottom:18px; }

.jobcard { background:var(--surface); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; margin-bottom:12px; }
.jobtitle { font-family:'Space Grotesk',sans-serif; font-size:16px; font-weight:600; color:var(--ink); }
.jobmeta { font-size:13px; color:var(--muted); margin-top:3px; }

/* Signature element: the match readout */
.readout { font-family:'IBM Plex Mono',monospace; font-size:30px; font-weight:600;
  color:var(--ink); line-height:1; text-align:right; }
.readout span { font-size:13px; color:var(--muted); }
.gauge { height:3px; background:var(--line); border-radius:2px; margin-top:7px; overflow:hidden; }
.gauge > i { display:block; height:100%; background:var(--signal); }

.tag { display:inline-block; font-family:'IBM Plex Mono',monospace; font-size:11px;
  padding:2px 7px; border-radius:4px; margin:2px 4px 2px 0; border:1px solid var(--line); }
.tag.have { background:#E6F6EF; color:#046C4E; border-color:#B7E4CE; }
.tag.gap  { background:#FEF3E7; color:#93370D; border-color:#F5D6B3; }
.tag.src  { background:#EEF2F6; color:#344054; }

.kcol { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:10px; min-height:110px; }
.kcol h4 { font-size:12px !important; font-family:'IBM Plex Mono',monospace !important;
  text-transform:uppercase; letter-spacing:.1em; color:var(--muted); margin:0 0 8px; }
.kitem { border-left:3px solid var(--signal); background:#F9FAFB; border-radius:6px;
  padding:8px 10px; margin-bottom:7px; font-size:13px; }
.kitem b { display:block; color:var(--ink); font-weight:600; }
.kitem small { color:var(--muted); }

.empty { background:var(--surface); border:1px dashed var(--line); border-radius:10px;
  padding:26px; text-align:center; color:var(--muted); font-size:14px; }
.stButton button { border-radius:7px; font-weight:500; font-size:13px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# API helpers
# --------------------------------------------------------------------------
def api_call(method: str, path: str, **kwargs) -> tuple[bool, Any]:
    """Returns (ok, payload_or_message). Never raises."""
    url = f"{API}{path}" if path.startswith("/") else f"{BACKEND_URL}/{path}"
    try:
        response = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.exceptions.ConnectionError:
        return False, f"Can't reach the backend at {BACKEND_URL}. Start it, then reload this page."
    except requests.exceptions.Timeout:
        return False, "The backend took too long to respond. Try again."
    except Exception as exc:  # noqa: BLE001
        return False, f"Request failed: {exc}"

    if response.status_code == 204:
        return True, None
    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": response.text[:300]}
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        if isinstance(detail, list) and detail:
            detail = detail[0].get("msg", str(detail))
        return False, str(detail or f"HTTP {response.status_code}")
    return True, payload


def backend_health() -> Optional[Dict[str, Any]]:
    ok, payload = api_call("GET", "health")
    return payload if ok and isinstance(payload, dict) else None


def init_state() -> None:
    defaults = {
        "cv_id": None,
        "cv_profile": None,
        "cv_name": "",
        "results": [],
        "search_errors": [],
        "task_id": None,
        "chat_session": uuid.uuid4().hex,
        "chat_log": [],
        "panel": {},
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


init_state()


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------
def empty_state(message: str) -> None:
    st.markdown(f"<div class='empty'>{message}</div>", unsafe_allow_html=True)


def score_readout(score: Optional[float]) -> str:
    if score is None:
        return "<div class='readout'>—</div>"
    width = max(0.0, min(100.0, float(score)))
    return (
        f"<div class='readout'>{score:.0f}<span>%</span></div>"
        f"<div class='gauge'><i style='width:{width}%'></i></div>"
    )


def skill_tags(skills: List[str], kind: str, limit: int = 8) -> str:
    return "".join(f"<span class='tag {kind}'>{s}</span>" for s in (skills or [])[:limit])


def format_date(value: Optional[str]) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return str(value)[:10]


def require_cv() -> bool:
    if st.session_state.cv_id:
        return True
    empty_state("Upload a CV in the sidebar first. Everything here works from your CV.")
    return False


# --------------------------------------------------------------------------
# Sidebar: CV + connection
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Your CV")
    uploaded = st.file_uploader("PDF or DOCX", type=["pdf", "docx", "txt"], label_visibility="collapsed")
    if uploaded is not None and st.button("Read this CV", use_container_width=True, type="primary"):
        with st.spinner("Reading your CV…"):
            ok, payload = api_call(
                "POST", "/cv/upload",
                files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream")},
            )
        if ok:
            st.session_state.cv_id = payload["cv_id"]
            st.session_state.cv_profile = payload["profile"]
            st.session_state.cv_name = payload["filename"]
            st.success(f"Read {payload['characters']:,} characters ({payload['parse_method']} extraction)")
        else:
            st.error(payload)

    if st.session_state.cv_id:
        profile = st.session_state.cv_profile or {}
        st.markdown(f"**{st.session_state.cv_name}**")
        st.caption(f"ID {st.session_state.cv_id[:12]} · {profile.get('years_experience', 0):.0f} yrs experience")
        if profile.get("skills"):
            st.markdown("**Skills found**")
            st.markdown(skill_tags(profile["skills"], "have", 14), unsafe_allow_html=True)
        if profile.get("job_titles"):
            st.caption("Titles: " + ", ".join(profile["job_titles"][:3]))
    else:
        st.caption("No CV loaded yet.")

    st.divider()
    health = backend_health()
    if health:
        st.caption(f"Backend {health['status']} · {health['embeddings'].split(':')[0]}")
        st.caption(f"LLM {'on' if health['llm_configured'] else 'off'} · "
                   f"Email {'on' if health['smtp_configured'] else 'off'} · "
                   f"Alerts {health['scheduler']}")
    else:
        st.error(f"Backend offline at {BACKEND_URL}")


st.markdown("<div class='masthead'>Job Matching Agent</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='masthead-sub'>Wuzzuf · Bayt · Tanqeeb · Indeed · LinkedIn</div>",
    unsafe_allow_html=True,
)

tab_search, tab_matches, tab_apps, tab_alerts, tab_gap, tab_agent = st.tabs(
    ["🔎 Job Search", "📊 Job Matches", "📋 My Applications", "🔔 Job Alerts", "🎯 Skill Gap", "💬 Career Agent"]
)


# ==========================================================================
# 1. Job Search
# ==========================================================================
with tab_search:
    if require_cv():
        st.markdown("#### Search terms")
        col1, col2, col3 = st.columns(3)
        with col1:
            keywords = st.text_input("Keywords", placeholder="Leave blank to use your CV title")
            location = st.text_input("Location", value="Egypt")
        with col2:
            job_type = st.selectbox("Job type", ["Any", "Full Time", "Part Time", "Freelance", "Internship"])
            min_salary = st.number_input("Minimum monthly salary", min_value=0, step=1000, value=0,
                                         help="Jobs that don't publish a salary are always kept.")
        with col3:
            max_age = st.selectbox("Posted within", ["Any time", "24 hours", "7 days", "30 days"], index=2)
            per_source = st.slider("Results per source", 5, 40, 15)

        sources = st.multiselect(
            "Sources", ["wuzzuf", "bayt", "tanqeeb", "indeed", "linkedin"],
            default=["wuzzuf", "bayt", "tanqeeb", "indeed", "linkedin"],
        )

        if st.button("Search jobs", type="primary", use_container_width=True):
            age_map = {"Any time": None, "24 hours": 1, "7 days": 7, "30 days": 30}
            filters = {
                "keywords": keywords or None,
                "location": location or None,
                "job_type": None if job_type == "Any" else job_type,
                "min_salary": min_salary or None,
                "max_age_days": age_map[max_age],
                "sources": sources or None,
                "limit_per_source": per_source,
            }
            ok, payload = api_call("POST", "/jobs/search",
                                   json={"cv_id": st.session_state.cv_id, "filters": filters})
            if not ok:
                st.error(payload)
            else:
                task_id = payload["task_id"]
                st.session_state.task_id = task_id
                progress = st.progress(0.0, text="Opening the five job boards…")
                results, errors = [], []
                for tick in range(150):  # up to ~5 minutes
                    time.sleep(2)
                    ok, status_payload = api_call("GET", f"/jobs/status/{task_id}")
                    if not ok:
                        st.error(status_payload)
                        break
                    state = status_payload["status"]
                    progress.progress(min(0.95, (tick + 1) / 40),
                                      text=status_payload.get("progress") or state)
                    if state in ("completed", "failed"):
                        results = status_payload.get("results") or []
                        errors = status_payload.get("errors") or []
                        if state == "failed":
                            st.error(status_payload.get("error") or "The search failed.")
                        break
                progress.empty()
                st.session_state.results = results
                st.session_state.search_errors = errors
                if results:
                    st.success(f"Found {len(results)} ranked jobs. Open the Job Matches tab.")
                elif not errors:
                    st.warning("No jobs matched those filters. Try broader keywords.")

        if st.session_state.search_errors:
            with st.expander(f"Source problems ({len(st.session_state.search_errors)})", expanded=not st.session_state.results):
                for err in st.session_state.search_errors:
                    label = {"blocked": "🚫", "unavailable": "⚙️"}.get(err.get("error_type"), "⚠️")
                    st.markdown(f"{label} **{err['source']}** — {err['error']}")
                st.caption("Blocked sources are skipped on purpose. The remaining sources still return results.")


# ==========================================================================
# 2. Job Matches
# ==========================================================================
with tab_matches:
    results = st.session_state.results
    if not results:
        empty_state("No matches yet. Run a search to rank jobs against your CV.")
    else:
        top = st.columns(4)
        top[0].metric("Jobs ranked", len(results))
        top[1].metric("Best match", f"{max((j.get('match_score') or 0) for j in results):.0f}%")
        top[2].metric("Sources", len({j.get("source") for j in results}))
        top[3].metric("With salary", sum(1 for j in results if j.get("salary_text")))

        st.divider()
        for index, job in enumerate(results[:60]):
            with st.container():
                left, right = st.columns([5, 1])
                with left:
                    st.markdown(
                        f"<div class='jobtitle'>{job.get('title') or 'Untitled role'}</div>"
                        f"<div class='jobmeta'>{job.get('company') or 'Company not listed'} · "
                        f"{job.get('location') or 'Location not listed'} · "
                        f"<span class='tag src'>{job.get('source')}</span></div>"
                        f"<div class='jobmeta'>Salary: {job.get('salary_text') or 'not listed'} · "
                        f"Posted: {job.get('posted_text') or 'not listed'}</div>",
                        unsafe_allow_html=True,
                    )
                with right:
                    st.markdown(score_readout(job.get("match_score")), unsafe_allow_html=True)

                if job.get("match_explanation"):
                    st.caption(job["match_explanation"])
                tags = skill_tags(job.get("matching_skills"), "have") + skill_tags(job.get("missing_skills"), "gap")
                if tags:
                    st.markdown(tags, unsafe_allow_html=True)

                actions = st.columns(5)
                if job.get("url"):
                    actions[0].link_button("Open job", job["url"], use_container_width=True)
                if actions[1].button("Track job", key=f"track{index}", use_container_width=True):
                    ok, payload = api_call("POST", "/applications", json={
                        "cv_id": st.session_state.cv_id, "job_title": job.get("title", ""),
                        "company": job.get("company", ""), "job_url": job.get("url", ""),
                        "location": job.get("location", ""), "source": job.get("source", ""),
                        "match_score": job.get("match_score") or 0, "status": "saved",
                    })
                    st.success("Saved to My Applications") if ok else st.error(payload)
                if actions[2].button("Cover letter", key=f"cl{index}", use_container_width=True):
                    with st.spinner("Writing your cover letter…"):
                        ok, payload = api_call("POST", "/cover-letter", json={
                            "cv_id": st.session_state.cv_id, "job_title": job.get("title", ""),
                            "company": job.get("company", ""), "job_description": job.get("description", ""),
                            "job_url": job.get("url", ""),
                        })
                    st.session_state.panel = {"kind": "letter", "index": index, "ok": ok, "data": payload}
                if actions[3].button("Interview prep", key=f"mi{index}", use_container_width=True):
                    with st.spinner("Preparing interview questions…"):
                        ok, payload = api_call("POST", "/mock-interview", json={
                            "cv_id": st.session_state.cv_id, "job_title": job.get("title", ""),
                            "company": job.get("company", ""), "job_description": job.get("description", ""),
                        })
                    st.session_state.panel = {"kind": "interview", "index": index, "ok": ok, "data": payload}
                if actions[4].button("Skill gap", key=f"sg{index}", use_container_width=True):
                    with st.spinner("Comparing your skills…"):
                        ok, payload = api_call("POST", "/skill-gap/job", json={
                            "cv_id": st.session_state.cv_id, "job_title": job.get("title", ""),
                            "job_description": job.get("description", ""), "job_url": job.get("url", ""),
                        })
                    st.session_state.panel = {"kind": "gap", "index": index, "ok": ok, "data": payload}

                panel = st.session_state.panel
                if panel.get("index") == index:
                    if not panel["ok"]:
                        st.error(panel["data"])
                    elif panel["kind"] == "letter":
                        st.text_area("Cover letter", panel["data"]["cover_letter"], height=340, key=f"cltxt{index}")
                        st.caption(f"Model: {panel['data'].get('model_used', '—')}")
                    elif panel["kind"] == "interview":
                        for number, question in enumerate(panel["data"]["questions"], 1):
                            with st.expander(f"{number}. {question['question']}"):
                                st.caption(f"Category: {question.get('category', 'general')}")
                                if question.get("why_asked"):
                                    st.write(f"**Why they ask:** {question['why_asked']}")
                                if question.get("answer_hint"):
                                    st.write(f"**How to answer:** {question['answer_hint']}")
                    elif panel["kind"] == "gap":
                        data = panel["data"]
                        st.metric("Gap score", f"{data['gap_score']:.0f}%")
                        st.write(data["explanation"])
                        st.markdown(skill_tags(data["matching_skills"], "have", 20)
                                    + skill_tags(data["missing_skills"], "gap", 20), unsafe_allow_html=True)
                st.markdown("<hr style='border:none;border-top:1px solid #DFE4EA;margin:14px 0'>",
                            unsafe_allow_html=True)


# ==========================================================================
# 3. My Applications (Kanban)
# ==========================================================================
STATUSES = ["saved", "applied", "interviewing", "offer", "rejected", "withdrawn"]

with tab_apps:
    if require_cv():
        head = st.columns([3, 1])
        head[0].markdown("#### Your pipeline")
        if head[1].button("Refresh", use_container_width=True):
            st.rerun()

        ok, applications = api_call("GET", f"/applications?cv_id={st.session_state.cv_id}")
        if not ok:
            st.error(applications)
            applications = []

        if not applications:
            empty_state("Nothing tracked yet. Use “Track job” on any match to start your pipeline.")
        else:
            columns = st.columns(len(STATUSES))
            for column, state in zip(columns, STATUSES):
                items = [a for a in applications if a["status"] == state]
                with column:
                    st.markdown(
                        f"<div class='kcol'><h4>{state} · {len(items)}</h4>"
                        + "".join(
                            f"<div class='kitem'><b>{item['job_title'][:44]}</b>"
                            f"<small>{item['company'] or '—'} · {item['match_score']:.0f}%</small></div>"
                            for item in items
                        )
                        + "</div>",
                        unsafe_allow_html=True,
                    )

            st.divider()
            st.markdown("#### Update an application")
            labels = {f"{a['job_title']} — {a['company'] or '—'} [{a['status']}]": a for a in applications}
            chosen_label = st.selectbox("Application", list(labels.keys()))
            chosen = labels[chosen_label]

            edit = st.columns([2, 2, 3])
            new_status = edit[0].selectbox("Move to", STATUSES, index=STATUSES.index(chosen["status"]))
            note = edit[1].text_input("Add a note", placeholder="Recruiter call booked")
            with edit[2]:
                st.write("")
                buttons = st.columns(2)
                if buttons[0].button("Save changes", type="primary", use_container_width=True):
                    body: Dict[str, Any] = {}
                    if new_status != chosen["status"]:
                        body["status"] = new_status
                    if note:
                        body["event_note"] = note
                    if not body:
                        st.info("Nothing changed.")
                    else:
                        ok, payload = api_call("PATCH", f"/applications/{chosen['id']}", json=body)
                        if ok:
                            st.success("Updated")
                            st.rerun()
                        else:
                            st.error(payload)
                if buttons[1].button("Remove", use_container_width=True):
                    ok, payload = api_call("DELETE", f"/applications/{chosen['id']}")
                    if ok:
                        st.success("Removed")
                        st.rerun()
                    else:
                        st.error(payload)

            ok, timeline = api_call("GET", f"/applications/{chosen['id']}/timeline")
            if ok:
                st.markdown("**History**")
                for event in reversed(timeline["events"]):
                    arrow = f"{event['old_status'] or 'new'} → {event['new_status']}"
                    st.markdown(f"- `{format_date(event['created_at'])}` **{arrow}** — {event['note']}")


# ==========================================================================
# 4. Job Alerts
# ==========================================================================
with tab_alerts:
    if require_cv():
        st.markdown("#### Create an alert")
        st.caption("The agent reruns this search on a schedule and emails you only jobs you haven't seen.")

        with st.form("alert_form"):
            row = st.columns(3)
            alert_name = row[0].text_input("Alert name", value="Backend roles in Cairo")
            alert_email = row[1].text_input("Send to", placeholder="you@example.com")
            alert_limit = row[2].slider("Results per source", 5, 30, 10)
            row2 = st.columns(3)
            alert_keywords = row2[0].text_input("Keywords", value="backend developer")
            alert_location = row2[1].text_input("Location", value="Cairo")
            alert_salary = row2[2].number_input("Minimum monthly salary", min_value=0, step=1000, value=0)
            submitted = st.form_submit_button("Create alert", type="primary")

        if submitted:
            if not alert_email:
                st.error("Add an email address so the agent knows where to send matches.")
            else:
                ok, payload = api_call("POST", "/alerts", json={
                    "cv_id": st.session_state.cv_id, "name": alert_name, "destination": alert_email,
                    "filters": {"keywords": alert_keywords or None, "location": alert_location or None,
                                "min_salary": alert_salary or None, "limit_per_source": alert_limit},
                })
                if ok:
                    st.success("Alert created")
                    st.rerun()
                else:
                    st.error(payload)

        st.divider()
        ok, alerts = api_call("GET", f"/alerts?cv_id={st.session_state.cv_id}")
        if not ok:
            st.error(alerts)
        elif not alerts:
            empty_state("No alerts yet. Create one above and the agent will watch the boards for you.")
        else:
            health = backend_health() or {}
            if not health.get("smtp_configured"):
                st.warning("Email isn't configured, so alerts will collect matches but can't send them. "
                           "Set SMTP_HOST and SMTP_FROM_EMAIL in .env to enable delivery.")
            for alert in alerts:
                with st.container():
                    columns = st.columns([4, 1, 1, 1])
                    filters = alert.get("filters") or {}
                    columns[0].markdown(
                        f"**{alert['name']}** — {alert['destination']}  \n"
                        f"<span class='jobmeta'>{filters.get('keywords') or 'any role'} · "
                        f"{filters.get('location') or 'anywhere'} · "
                        f"last run {format_date(alert.get('last_run_at'))}</span>",
                        unsafe_allow_html=True,
                    )
                    columns[1].markdown("🟢 Active" if alert["is_active"] else "⚪ Paused")
                    if columns[2].button("Pause" if alert["is_active"] else "Activate", key=f"t{alert['id']}"):
                        api_call("PATCH", f"/alerts/{alert['id']}", json={"is_active": not alert["is_active"]})
                        st.rerun()
                    if columns[3].button("Delete", key=f"d{alert['id']}"):
                        api_call("DELETE", f"/alerts/{alert['id']}")
                        st.rerun()
                    if st.button("Run now", key=f"r{alert['id']}"):
                        with st.spinner("Checking the boards…"):
                            ok, payload = api_call("POST", f"/alerts/{alert['id']}/run?send_email=true")
                        if not ok:
                            st.error(payload)
                        else:
                            st.info(f"{payload['new_jobs_count']} new job(s) of {payload['total_found']} found. "
                                    f"Email sent: {payload['emailed']}")
                            if payload.get("email_error"):
                                st.warning(payload["email_error"])


# ==========================================================================
# 5. Skill Gap
# ==========================================================================
with tab_gap:
    if require_cv():
        st.markdown("#### What the market wants that you don't have yet")
        top_n = st.slider("Jobs to analyse", 3, 25, 10)
        use_cached = st.checkbox("Use my last search results", value=True)

        if st.button("Analyse skill gap", type="primary"):
            jobs = [] if use_cached else st.session_state.results[:top_n]
            with st.spinner("Comparing your CV against each job…"):
                ok, payload = api_call("POST", "/skill-gap/aggregate", json={
                    "cv_id": st.session_state.cv_id, "jobs": jobs,
                    "top_n": top_n, "use_cached_results": use_cached,
                })
            if not ok:
                st.error(payload)
            else:
                st.session_state.gap_report = payload

        report = st.session_state.get("gap_report")
        if not report:
            empty_state("No analysis yet. Run a job search first, then analyse the gap across those jobs.")
        else:
            metrics = st.columns(3)
            metrics[0].metric("Jobs analysed", report["jobs_analyzed"])
            metrics[1].metric("Average gap", f"{report['average_gap_score']:.0f}%")
            metrics[2].metric("Skills to learn", len(report["learning_priorities"]))
            st.info(report["summary"])

            if report["top_missing_skills"]:
                st.markdown("**Most requested skills you're missing**")
                frame = pd.DataFrame(report["top_missing_skills"]).set_index("skill")[["count"]]
                st.bar_chart(frame, color="#B54708", height=280)

            if report["top_matching_skills"]:
                st.markdown("**Your skills the market keeps asking for**")
                frame = pd.DataFrame(report["top_matching_skills"]).set_index("skill")[["count"]]
                st.bar_chart(frame, color="#0E9F6E", height=280)

            if report["learning_priorities"]:
                st.markdown("**Learn these first**")
                for position, skill in enumerate(report["learning_priorities"], 1):
                    st.markdown(f"{position}. **{skill}**")


# ==========================================================================
# 6. Career Agent
# ==========================================================================
with tab_agent:
    if require_cv():
        header = st.columns([4, 1])
        header[0].markdown("#### Ask about your search")
        if header[1].button("New conversation", use_container_width=True):
            st.session_state.chat_session = uuid.uuid4().hex
            st.session_state.chat_log = []
            st.rerun()

        if not st.session_state.chat_log:
            st.caption("Try: “Which jobs fit me best?” · “What should I learn next?” · "
                       "“How many jobs have I applied to?” · “Help me prepare for an interview.”")

        for message in st.session_state.chat_log:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        prompt = st.chat_input("Ask about your matches, gaps or applications")
        if prompt:
            st.session_state.chat_log.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    ok, payload = api_call("POST", "/career-agent/chat", json={
                        "cv_id": st.session_state.cv_id,
                        "session_id": st.session_state.chat_session,
                        "message": prompt,
                    })
                reply = payload["reply"] if ok else f"⚠️ {payload}"
                st.markdown(reply)
                if ok and payload.get("tools_used"):
                    st.caption("Looked at: " + ", ".join(payload["tools_used"]))
            st.session_state.chat_log.append({"role": "assistant", "content": reply})
