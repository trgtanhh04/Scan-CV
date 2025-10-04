import os
from translate import Translator
import re
from difflib import get_close_matches
from langchain_deepseek import ChatDeepSeek
from config import DEEPSEEK_API_KEY

deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)


# Centralized abbreviation map for job titles / roles / seniority
# Add or modify entries here to match your team's conventions.
ABBREV_MAP = {
    # Roles
    "DE": "Data Engineer",
    "SDE": "Software Development Engineer",
    "SWE": "Software Engineer",
    "SE": "Software Engineer",
    "FE": "Frontend Engineer",
    "BE": "Backend Engineer",
    "Fullstack": "Fullstack Engineer",
    "PO": "Product Owner",
    "PM": "Project Manager",
    "PdM": "Product Manager",
    "QA": "Quality Assurance Engineer",
    "SDET": "Software Development Engineer in Test",
    "DevOps": "DevOps Engineer",
    "SRE": "Site Reliability Engineer",
    "TL": "Tech Lead",
    "EM": "Engineering Manager",
    "EngMgr": "Engineering Manager",
    "Mgr": "Manager",

    # Data / ML
    "DS": "Data Scientist",
    "DA": "Data Analyst",
    "BI": "Business Intelligence",
    "ML": "Machine Learning",
    "MLE": "Machine Learning Engineer",
    "MLEng": "Machine Learning Engineer",

    # Product / Design / Leadership
    "UX": "User Experience",
    "UI": "User Interface",
    "CTO": "Chief Technology Officer",
    "CPO": "Chief Product Officer",
    "CEO": "Chief Executive Officer",
    "VP": "Vice President",

    # Seniority
    "Sr": "Senior",
    "Jr": "Junior",

    # Other common shorthand
    "BD": "Business Development",
    "AI": "Artificial Intelligence",
}

#============= HELPERS =============

# Convert job description to English if needed
def translate_to_english(query):
    translator = Translator(to_lang="en", from_lang="vi")
    return translator.translate(query)

# Fine-tune job description to a precise search query
def convert_job_to_question(job_description):
    search_query_prompt = f"""
        You are a Text-to-Search Query assistant.
        Convert the input job description into ONE concise English search query for finding candidates.
        Rules:
        - Output exactly ONE sentence, starting with "Find candidates ...".
        - No explanations, no lists, no code fences.
        - Preserve the user's intent (skills, seniority, years of experience, location, role).
        - Use clear, natural English suitable for downstream Text2SQL processing.

        Examples:
            Input: "Find candidates that know Python."
            Output: "Find candidates that know Python."

            Input: "Python, pandas, SQL"
            Output: "Find candidates that know Python, pandas, and SQL."

            Input: "5+ years as a Fullstack Engineer, AI Specialist, or similar, with experience deploying scalable applications."
            Output: "Find candidates with 5+ years fullstack or AI specialist experience and a proven track record of deploying scalable applications."

            Input: "Data Engineer with 7 years experience in ETL, Python, Airflow"
            Output: "Find Data Engineers with 7 years of experience in ETL and strong skills in Python and Airflow."

            Input: "Senior Software Engineer, 5+ years, Kubernetes, microservices, AWS"
            Output: "Find Senior Software Engineers with 5+ years experience in Kubernetes, microservices, and AWS."

            Input: "Looking for PM to lead a small product team and own roadmap"
            Output: "Find Product Managers with experience leading small teams and owning product roadmaps."

            Input: "Data Scientist, machine learning, production deployment"
            Output: "Find Data Scientists experienced in machine learning and deploying models to production."

            Input: "Data Engineer, 5 years, HCM"
            Output: "Find Data Engineers with 5 years experience located in Ho Chi Minh City."

            Input: "Fullstack (React/Node), 3 yrs"
            Output: "Find Fullstack Engineers skilled in React and Node with 3 years experience."

            Now convert the following input into one sentence:
    """
    response = deepseek.invoke(search_query_prompt + f"\nInput: '{job_description}'\nOutput:")
    return response.content.strip()


# Decision to fine-tune or not based on clarity/complexity of job description
def needs_finetune(job_description: str) -> bool:
    if not job_description or not isinstance(job_description, str):
        return False

    normalized = expand_abbreviations(job_description)
    norm_lower = normalized.lower()

    if re.match(r"^\s*(find|list|show|search for)\b", norm_lower) and re.search(r"\b(candidate|candidates|resume|cv|cvs)\b", norm_lower):
        return False

    words = re.findall(r"\w+", norm_lower)
    if len(words) <= 6 and any(k in norm_lower for k in ["python","java","sql","pandas","django","react","data engineer","software engineer","engineer","devops","sre","ml","machine learning"]):
        return False

    if len(words) <= 8 and re.search(r"\b\d+\s*(year|years|yr|yrs|năm)\b", norm_lower):
        return False

    complex_indicators = [
        "deploy", "scalable", "production", "production-ready", "distributed", "microservices",
        "kubernetes", "ci/cd", "team management", "project management", "lead", "architect",
        "machine learning", "deep learning", "data scientist", "business intelligence",
        "responsible for", "responsibilities", "requirements", "must have", "experience in",
    ]

    if len(words) > 12 or any(ci in norm_lower for ci in complex_indicators):
        return True

    return False

# Validate if query is suitable for candidate search
def validate_candidate_query(query: str, cutoff: float = 0.8) -> bool:
    """
    Kiểm tra xem câu truy vấn có hợp lệ để tìm ứng viên hay không.
    - Loại bỏ spam / câu vô nghĩa
    - Check từ khóa hợp lệ (có fuzzy matching để xử lý typo)
    - Cho qua câu chứa các động từ tìm kiếm phổ biến ("find", "search", "know")
    """
    query_lower = query.lower()

    valid_keywords = [
        "skills", "skill", "experience", "cv", "resume", "candidate", "email",
        "database", "knowledge", "years of experience", "project", "role", "position",
        "tech", "technology", "programming", "python", "java", "javascript",
        "sql", "nosql", "aws", "cloud", "deployment", "machine learning", "ai", "fullstack",
        "data engineer", "software", "development", "teamwork", "communication", "leadership",
        'chatbot', 'llm', 'gpt', 'deepseek', 'openai', 'langchain', 'university', 'degree', 'education', 'certification',
        'location', 'language', 'vietnamese', 'english', 'japanese', 'role', 'company', 'work', 'worked', 'working',
    ]

    invalid_patterns = [
        r"^[\W_]+$",                 
        r"^\s*$",                   
        r"\b(?:haha|hehe|hihi|hahaha|hoho|lmao|lol)\b", 
        r"\b(?:beauty|travel|vacation|holiday|shopping|love|friendship|handsome|happy|xinh đẹp)\b" 
    ]

    if any(re.search(pattern, query_lower) for pattern in invalid_patterns):
        return False

    words = re.findall(r'\w+', query_lower)
    for kw in valid_keywords:
        if kw.lower() in words:
            return True
        if get_close_matches(kw.lower(), words, cutoff=cutoff):
            return True

    if any(re.search(pattern, query_lower) for pattern in ["find", "search", "know", "list"]):
        return True

    return False


# ---------------------- Helpers migrated from main.py ----------------------
def is_probably_english(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    ascii_letters = re.findall(r"[A-Za-z]", s)
    ascii_ratio = len(ascii_letters) / max(1, len(s))
    if ascii_ratio > 0.6:
        lowers = s.lower()
        for w in ("the", "and", "or", "is", "are", "candidate", "experience", "skills"):
            if f" {w} " in f" {lowers} ":
                return True
        if " " in s:
            return True
    return False


def expand_abbreviations(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    keys = list(ABBREV_MAP.keys())
    keys.sort(key=lambda x: -len(x))
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")(?:\.|s|es)?\b", flags=re.IGNORECASE)
    def _repl(m):
        raw = re.sub(r"[\.|s|es]+$", "", m.group(0), flags=re.IGNORECASE)
        return ABBREV_MAP.get(raw.upper(), ABBREV_MAP.get(raw, m.group(0)))

    return pattern.sub(_repl, text)