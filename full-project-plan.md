# Job Matching Agent — خطة التنفيذ الكاملة

مستند واحد شامل لكل قرارات وتصميم المشروع، مُعد عشان يتستخدم كـ spec كامل لأي أداة agentic (Antigravity أو غيرها) تبني بيه المشروع من الصفر أو تكمل عليه.

---

## 1. نظرة عامة

Agent بياخد CV من المستخدم، يدوّر على وظائف مناسبة من 5 مواقع (Wuzzuf, Bayt, Tanqeeb, Indeed, LinkedIn)، يرتبهم حسب نسبة التطابق، ويقدر كمان يعمل:
- Cover letter مخصص لكل وظيفة
- Mock interview questions
- تحليل فجوة المهارات (Skill Gap)
- متابعة حالة التقديمات (Application Tracker)
- تنبيهات دورية بوظايف جديدة (Job Alerts)
- محادثة مفتوحة عن المسار المهني (Career Agent)

**الحجم المستهدف حاليًا:** استخدام شخصي/تجريبي (<10 مستخدمين) — القرارات المعمارية كلها مبنية على ده، مع ملاحظات صريحة إزاي تترقّى لـ production أكبر.

---

## 2. Tech Stack

| الطبقة | الاختيار | السبب |
|---|---|---|
| Orchestration | LangChain + LangGraph | فيه branching/fan-out-fan-in للبحث المتوازي في 5 مواقع |
| LLM Provider | OpenRouter (موديلات مجانية) | مجاني، مع fallback chain بين عدة موديلات لو واحد وصل لحد الاستخدام |
| Scraping | Playwright (مش requests/BeautifulSoup) | المواقع المستهدفة JS-heavy |
| Backend | FastAPI | async native، مناسب لـ scraping متوازي |
| Task Queue | FastAPI BackgroundTasks + in-memory store | كافي لـ <10 مستخدمين — **قابل للترقية لـ Celery+Redis لاحقًا** |
| Frontend | Streamlit | سريع البناء لواجهة داخلية/شخصية |
| Embeddings | sentence-transformers (محلي) | ما بيستهلكش من quota الموديلات المجانية على OpenRouter |
| Database | SQLite + SQLAlchemy (مخطط، لسه ما اتبنيش) | كافي للحجم الحالي، سهل الترقية لـ Postgres |

---

## 3. البنية العامة (Pipeline)

```
CV Upload → Parse & Extract → [fan-out] Multi-source Search (parallel) →
[fan-in] Normalize → Filter (salary/date) → Rank (embedding similarity) →
Results → { Cover Letter | Mock Interview | Skill Gap | Track Application }
```

---

## 4. LangGraph Flow (مبني وشغال)

```
        build_search_query
               |
      -------- fan-out --------
      |    |    |    |    |
   wuzzuf bayt tanqeeb indeed linkedin   (parallel scraping nodes)
      |    |    |    |    |
      -------- fan-in ---------
               |
          filter_jobs   (سلاري + تاريخ)
               |
           rank_jobs    (embedding similarity)
               |
              END
```

كل مصدر عنده node منفصل مستقل — لو مصدر وقع (fail)، الباقي بيكمل عادي والأخطاء بتتجمع في `state["errors"]` بدل ما توقف الـ pipeline كله.

---

## 5. هيكل المشروع الحالي

```
job-agent/
├── app/
│   ├── config.py                # إعدادات + fallback chain للموديلات المجانية
│   ├── schemas.py                # كل الـ Pydantic models
│   ├── main.py                   # FastAPI app + كل الـ endpoints
│   ├── scrapers/
│   │   ├── base.py               # Abstract base - Playwright context, retry, delay
│   │   ├── wuzzuf.py             # ✅ مبني بالكامل - selectors محتاجة تأكيد
│   │   ├── bayt.py               # ⚠️ structure جاهز - selectors تقريبية
│   │   ├── tanqeeb.py            # ⚠️ structure جاهز - selectors تقريبية
│   │   ├── indeed.py             # ⚠️ structure جاهز - anti-bot قوي
│   │   └── linkedin.py           # ⚠️ structure جاهز - أعلى خطورة حظر
│   ├── agents/
│   │   ├── state.py              # LangGraph state definition
│   │   ├── nodes.py              # node functions + cover letter + mock interview generators
│   │   └── graph.py              # بناء الـ graph (fan-out/fan-in)
│   └── services/
│       ├── llm_client.py         # OpenRouter wrapper + fallback بين الموديلات
│       ├── matching.py           # CV parsing (PDF/DOCX) + embedding similarity
│       ├── task_store.py         # in-memory task queue (بديل Celery المؤقت)
│       └── skill_gap.py          # ✅ تحليل فردي + مجمّع لفجوة المهارات
├── streamlit_app.py               # واجهة كاملة: بحث + نتائج + skill gap tab
├── requirements.txt
├── .env.example
└── README.md
```

---

## 6. الـ API Endpoints (الحالية)

```
POST   /api/v1/cv/upload                 رفع CV (PDF/DOCX) → cv_id
POST   /api/v1/jobs/search                بدء بحث async → task_id
GET    /api/v1/jobs/status/{task_id}      polling لحالة البحث والنتائج
POST   /api/v1/cover-letter               توليد cover letter لوظيفة معينة
POST   /api/v1/mock-interview             توليد أسئلة mock interview
POST   /api/v1/skill-gap/job              تحليل فجوة مهارات لوظيفة واحدة
POST   /api/v1/skill-gap/aggregate        تحليل مجمّع عبر عدة وظائف (bar chart)
GET    /health
```

---

## 7. القرارات المعمارية المتخذة (Decision Log)

| القرار | الاختيار | السبب |
|---|---|---|
| Scraping strategy | كل المصادر بـ Playwright + proxies من الأول | المستخدم اختارها رغم المخاطرة الأعلى مع LinkedIn/Indeed |
| Task queue | BackgroundTasks بسيط، مش Celery | الحجم <10 مستخدمين ميستاهلش تعقيد Celery/Redis دلوقتي |
| Job Alerts channel | Email (SMTP) | أبسط setup للمرحلة دي |
| Career Agent model | الاكتفاء بالموديلات المجانية حتى لو tool-calling مش دقيق 100% | تفضيل التكلفة صفر على الدقة الكاملة في المرحلة الحالية |
| أول ميزة تتبني من الأربعة الجداد | Skill Gap Analyzer | ✅ **تم البناء والاختبار** |

---

## 8. حالة كل جزء (Implementation Status)

| الجزء | الحالة |
|---|---|
| FastAPI backend skeleton | ✅ جاهز ويشتغل |
| LangGraph fan-out/fan-in flow | ✅ جاهز |
| OpenRouter LLM + fallback chain | ✅ جاهز |
| Matching (embeddings) | ✅ جاهز |
| Streamlit UI (بحث + نتائج) | ✅ جاهز |
| Wuzzuf scraper | ✅ مبني بالكامل - **يحتاج تأكيد الـ selectors فعليًا قبل أول تشغيل** |
| Bayt / Tanqeeb / Indeed / LinkedIn scrapers | ⚠️ Structure كامل، selectors تقريبية - **لازم Inspect Element فعلي** |
| Skill Gap Analyzer (فردي + مجمّع) | ✅ **جاهز ومُختبر منطقيًا (unit-tested الـ aggregation logic)** |
| CV parsing الذكي (استخراج skills/experience بدقة عبر LLM) | ❌ TODO - دلوقتي بيخزن النص الخام بس |
| Date normalization لكل موقع | ❌ TODO |
| Salary parsing (نص → أرقام) | ❌ TODO |
| قاعدة بيانات حقيقية (SQLAlchemy) | ❌ TODO - **أساس لازم قبل الميزات الثلاثة الجاية** |
| Application Tracker | ❌ TODO - مخطط بالكامل في القسم 9 |
| Job Alerts (Email) | ❌ TODO - مخطط بالكامل في القسم 9 |
| Career Agent | ❌ TODO - مخطط بالكامل في القسم 9 |

---

## 9. الميزات الجديدة المخططة (تفصيل كامل)

### 9.0 قاعدة البيانات (أساس لازم أول حاجة)

```
cvs                  (id, raw_text, skills_json, job_titles_json, uploaded_at)
applications         (id, cv_id, job_url, job_title, company, status, applied_date,
                       notes, next_action_date, created_at, updated_at)
application_events   (id, application_id, old_status, new_status, note, created_at)
alert_subscriptions  (id, cv_id, filters_json, channel, destination, is_active, created_at)
seen_jobs            (id, alert_id, job_url_hash, job_title, company, first_seen_at)
skill_gap_reports    (id, cv_id, job_url, missing_skills_json, matching_skills_json,
                       gap_score, created_at)
career_chat_sessions (id, cv_id, session_id, created_at)
career_chat_messages (id, session_id, role, content, created_at)
```

ملفات جديدة: `app/db.py` (SQLAlchemy engine/session)، `app/models_db.py` (ORM models)

### 9.1 Application Tracker

**Status enum:** `saved → applied → interviewing → offer / rejected / withdrawn`

**Endpoints:**
```
POST   /api/v1/applications
GET    /api/v1/applications?cv_id=...
PATCH  /api/v1/applications/{id}          (بيسجل event تلقائي في application_events)
DELETE /api/v1/applications/{id}
GET    /api/v1/applications/{id}/timeline
```

**UI:** Tab "📋 My Applications" — عرض Kanban-style بعمود لكل status، مع زرار "➕ Track this job" يتضاف جنب نتايج البحث العادية.

### 9.2 Job Alerts (Email)

**الفكرة:** المستخدم بيحفظ بحث دوري (filters ثابتة)، والنظام يشغّله كل فترة، ويبعت إيميل لو لقى وظائف جديدة مشافهاش قبل كده.

**Scheduler:** APScheduler (in-process، مناسب للحجم الحالي — يترقّى لـ Celery Beat لاحقًا)

```python
# app/services/scheduler.py
@scheduler.scheduled_job("interval", hours=6)
async def run_all_alerts():
    for sub in get_active_subscriptions():
        new_jobs = await run_search_and_diff(sub)   # يقارن مع seen_jobs بالـ URL hash
        if new_jobs:
            await send_email_notification(sub, new_jobs)
```

**Email sending:** SMTP بسيط، أو Resend/SendGrid لو عايز موثوقية أعلى مستقبلاً.

**Endpoints:**
```
POST   /api/v1/alerts
GET    /api/v1/alerts?cv_id=...
PATCH  /api/v1/alerts/{id}     (تفعيل/تعطيل)
DELETE /api/v1/alerts/{id}
```

**UI:** Tab "🔔 Job Alerts" — نفس فورم فلاتر البحث + حقل الإيميل + toggle تفعيل.

### 9.3 Skill Gap Analyzer — ✅ تم بالفعل

راجع القسم 8 وملف `app/services/skill_gap.py`. مبني بمستويين:
1. `analyze_skill_gap()` — تحليل وظيفة واحدة (LLM call واحد)
2. `aggregate_skill_gaps()` — تحليل مجمّع عبر أهم N وظيفة، بيحسب تكرار كل مهارة ناقصة/متطابقة باستخدام `Counter`

**تحسين مستقبلي مقترح:** حاليًا كل وظيفة = LLM call متتالي (مفيش parallelism). ممكن يتحسّن بـ `asyncio.gather` لو الأداء بقى مشكلة — لكن خد بالك من rate limits الموديلات المجانية.

### 9.4 Career Agent

**التصميم:** LangChain tool-calling agent (مش graph منفصل) بيربط كل الميزات السابقة كـ tools:

```python
tools = [
    get_my_cv_summary,        # ملخص الـ CV
    get_recent_job_matches,   # آخر نتايج بحث محفوظة
    get_skill_gap_summary,    # آخر aggregate skill gap report
    get_application_stats,    # إحصائيات المتابعات
    web_search_salary,        # بحث عن متوسط المرتبات
]
```

**Memory:** LangGraph checkpointing (`SqliteSaver`) بدل الـ memory القديم، عشان يتخزن في `career_chat_messages` وتكمل المحادثة حتى بعد إعادة فتح المتصفح.

**قرار متخذ:** الاكتفاء بالموديلات المجانية حتى لو دقة الـ tool-calling مش كاملة (بدل موديل مدفوع كـ fallback).

**Endpoint:**
```
POST /api/v1/career-agent/chat
Body: {"cv_id": "...", "session_id": "...", "message": "..."}
```

**UI:** Tab "💬 Career Agent" بواجهة `st.chat_message` / `st.chat_input`.

---

## 10. ترتيب التنفيذ المقترح (كل خطوة بتبني فوق اللي قبلها)

| # | الخطوة | الحالة |
|---|---|---|
| 1 | SQLAlchemy + الجداول كلها | ❌ لسه محتاج يتبني |
| 2 | Application Tracker | ❌ محتاج الـ DB الأول |
| 3 | Skill Gap Analyzer | ✅ **تم** |
| 4 | Job Alerts (Email) | ❌ محتاج DB + scheduler |
| 5 | Career Agent | ❌ الأعقد - محتاج الثلاثة اللي قبله كـ tools |

---

## 11. اعتبارات Production (لو المشروع كبر عن الاستخدام الشخصي)

- **Scraping:** استبدال LinkedIn/Indeed الـ scraping المباشر بـ aggregator API (زي JSearch على RapidAPI) لتقليل مخاطر الحظر القانوني/التقني
- **Task Queue:** الانتقال من BackgroundTasks/APScheduler لـ Celery + Redis (نفس منطق الكود، بس موزّع)
- **Database:** الانتقال من SQLite لـ Postgres (تغيير الـ connection string بس لو استخدمت SQLAlchemy من الأول)
- **LLM:** إضافة موديل مدفوع كـ fallback أخير بعد استنفاد كل الموديلات المجانية، خصوصًا لـ Career Agent
- **Auth:** إضافة user accounts حقيقية (JWT) بدل الاعتماد على `cv_id` كمعرّف وحيد
- **Monitoring:** إضافة Sentry أو أي error tracking، خصوصًا لمراقبة فشل الـ scrapers بمرور الوقت (الـ selectors بتتغيّر)
- **CI/CD:** Docker containers + GitHub Actions لو هيتنشر فعليًا

---

## 12. خطوات التشغيل السريعة

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium

cp .env.example .env              # وحط OPENROUTER_API_KEY بتاعك

# Terminal 1
uvicorn app.main:app --reload --port 8000

# Terminal 2
streamlit run streamlit_app.py
```

**أول حاجة تتأكد منها:** جرب `WuzzufScraper` لوحده (كود تجربة موجود في الـ README الأصلي) قبل ما تشغل الـ pipeline كله، عشان تتأكد إن الـ selectors شغالة عندك فعليًا.
