"""Skill vocabulary used for deterministic skill detection (LLM-independent)."""
from __future__ import annotations

import re

SKILL_TAXONOMY: dict[str, list[str]] = {
    # languages
    "Python": ["python", "بايثون"], "JavaScript": ["javascript", "js"],
    "TypeScript": ["typescript", "ts"], "Java": ["java "], "C#": ["c#", "csharp", ".net c#"],
    "C++": ["c++", "cpp"], "Go": ["golang", " go "], "Rust": ["rust"], "PHP": ["php"],
    "Ruby": ["ruby"], "Kotlin": ["kotlin"], "Swift": ["swift"], "Scala": ["scala language"], 
    "MATLAB": ["matlab"], "Bash": ["bash", "shell scripting"],
    # web / frontend
    "React": ["react", "react.js", "reactjs"], "Next.js": ["next.js", "nextjs"],
    "Vue.js": ["vue", "vue.js"], "Angular": ["angular"], "Svelte": ["svelte"],
    "HTML": ["html"], "CSS": ["css"], "Tailwind CSS": ["tailwind"],
    "Redux": ["redux"], "jQuery": ["jquery"],
    # backend
    "Django": ["django"], "Flask": ["flask"], "FastAPI": ["fastapi"],
    "Node.js": ["node.js", "nodejs", "node "], "Express.js": ["express"],
    "Spring Boot": ["spring boot", "spring"], "Laravel": ["laravel"],
    "ASP.NET": ["asp.net", "dotnet", ".net"], "GraphQL": ["graphql"],
    "REST API": ["rest api", "restful", "rest apis"], "gRPC": ["grpc"],
    "Microservices": ["microservice"], "WebSockets": ["websocket"],
    # data / db
    "SQL": ["sql", "اس كيو ال"], "PostgreSQL": ["postgres", "postgresql"],
    "MySQL": ["mysql"], "SQLite": ["sqlite"], "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"], "Elasticsearch": ["elasticsearch", "elastic search"],
    "Cassandra": ["cassandra"], "Oracle DB": ["oracle db", "oracle database"],
    "SQLAlchemy": ["sqlalchemy"], "Data Modeling": ["data modeling", "data modelling"],
    "ETL": ["etl", "elt "], "Airflow": ["airflow"], "dbt": ["dbt"],
    "Spark": ["spark", "pyspark"], "Hadoop": ["hadoop"], "Kafka": ["kafka"],
    "Snowflake": ["snowflake"], "BigQuery": ["bigquery"],
    # analytics / ML
    "Pandas": ["pandas"], "NumPy": ["numpy"], "scikit-learn": ["scikit", "sklearn"],
    "TensorFlow": ["tensorflow"], "PyTorch": ["pytorch", "torch"],
    "Machine Learning": ["machine learning", "ml ", "تعلم الآلة"],
    "Deep Learning": ["deep learning"], "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision", "opencv"],
    "LLM": ["llm", "large language model", "gpt", "openai"],
    "LangChain": ["langchain"], "RAG": ["rag ", "retrieval augmented"],
    "Data Analysis": ["data analysis", "data analytics", "تحليل البيانات"],
    "Statistics": ["statistics", "statistical"], "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau"], "Excel": ["excel", "اكسل"], "Looker": ["looker"],
    # cloud / devops
    "AWS": ["aws", "amazon web services"], "Azure": ["azure"],
    "Google Cloud": ["gcp", "google cloud"], "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"], "Terraform": ["terraform"],
    "Ansible": ["ansible"], "Jenkins": ["jenkins"],
    "CI/CD": ["ci/cd", "cicd", "continuous integration"],
    "GitHub Actions": ["github actions"], "Linux": ["linux", "ubuntu"],
    "Nginx": ["nginx"], "Serverless": ["serverless", "lambda"],
    "Prometheus": ["prometheus"], "Grafana": ["grafana"],
    # mobile
    "Android": ["android"], "iOS": ["ios "], "Flutter": ["flutter"],
    "React Native": ["react native"],
    # practices / tools
    "Git": ["git ", "github", "gitlab"], "Agile": ["agile", "سكرم"],
    "Scrum": ["scrum"], "Jira": ["jira"], "Testing": ["unit test", "pytest", "jest", "testing"],
    "TDD": ["tdd", "test driven"], "Code Review": ["code review"],
    "System Design": ["system design", "architecture"],
    "Security": ["security", "owasp", "أمن المعلومات"],
    "Performance Optimization": ["performance optimization", "optimization"],
    # design / product / business
    "Figma": ["figma"], "UI/UX": ["ui/ux", "ux design", "user experience"],
    "Adobe Photoshop": ["photoshop"], "Illustrator": ["illustrator"],
    "Product Management": ["product management", "product manager"],
    "Project Management": ["project management", "pmp", "إدارة المشاريع"],
    "Digital Marketing": ["digital marketing", "تسويق رقمي"],
    "SEO": ["seo"], "Content Writing": ["content writing", "copywriting"],
    "Sales": ["sales", "مبيعات"], "Customer Service": ["customer service", "خدمة العملاء"],
    "Accounting": ["accounting", "محاسبة"], "Finance": ["finance", "financial"],
    "HR": ["human resources", "hr ", "موارد بشرية"],
    # soft skills
    "Communication": ["communication", "تواصل"], "Leadership": ["leadership", "قيادة"],
    "Teamwork": ["teamwork", "team player", "عمل جماعي"],
    "Problem Solving": ["problem solving", "حل المشكلات"],
    "Time Management": ["time management"], "English": ["english", "انجليزي"],
    "Arabic": ["arabic", "عربي"],
}

# Skills that shouldn't count as a meaningful "gap" on their own.
SOFT_SKILLS = {
    "Communication", "Leadership", "Teamwork", "Problem Solving",
    "Time Management", "English", "Arabic",
}

_ALIAS_INDEX: dict[str, str] = {}
for canonical, aliases in SKILL_TAXONOMY.items():
    _ALIAS_INDEX[canonical.lower()] = canonical
    for alias in aliases:
        _ALIAS_INDEX[alias.strip().lower()] = canonical


def canonicalize(skill: str) -> str:
    """Map a free-text skill to its canonical taxonomy name (or title-case it)."""
    if not skill:
        return ""
    key = skill.strip().lower()
    if key in _ALIAS_INDEX:
        return _ALIAS_INDEX[key]
    for alias, canonical in _ALIAS_INDEX.items():
        if len(alias) > 3 and alias == key:
            return canonical
    return skill.strip()[:60]


# Short/ambiguous names need word-boundary + case-sensitive matching so that
# "R" doesn't fire on every stray letter and "Go" doesn't fire on "going".
AMBIGUOUS_PATTERNS: dict[str, str] = {
    "R": r"(?<![A-Za-z])R(?![A-Za-z+#])(?=[\s,/\.\)]|$)",
    "Go": r"(?<![A-Za-z])(?:Go|Golang|golang)(?![A-Za-z])",
    "Java": r"(?<![A-Za-z])Java(?!Script|script)(?![A-Za-z])",
    "C#": r"C#|(?<![A-Za-z])[Cc]sharp(?![A-Za-z])",
    "C++": r"C\+\+|(?<![A-Za-z])cpp(?![A-Za-z])",
    "Scala": r"(?<![A-Za-z])[Ss]cala(?![A-Za-z])",
}


def extract_skills_from_text(text: str, limit: int = 60) -> list[str]:
    """Deterministic keyword scan — used as the LLM-free fallback and cross-check."""
    if not text:
        return []
    padded = f" {text.lower()} "
    found: list[str] = []
    for canonical, pattern in AMBIGUOUS_PATTERNS.items():
        if re.search(pattern, text):
            found.append(canonical)
    for canonical, aliases in SKILL_TAXONOMY.items():
        if canonical in AMBIGUOUS_PATTERNS or canonical in found:
            continue
        for alias in [canonical.lower()] + aliases:
            if alias.strip() and alias.strip() in padded:
                found.append(canonical)
                break
        if len(found) >= limit:
            break
    return found
