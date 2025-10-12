import os
from translate import Translator
import re
from difflib import get_close_matches
from langchain_deepseek import ChatDeepSeek

from config import DEEPSEEK_API_KEY

from googleapiclient.discovery import build

from googleapiclient.discovery import build
from google.auth.credentials import AnonymousCredentials

    


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
    "Dev": "Developer",
    "Eng": "Engineer",
    "Engr": "Engineer",
    "Fullstack": "Fullstack Engineer",
    "PO": "Product Owner",
    "PM": "Project Manager",
    "PdM": "Product Manager",
    "PMO": "Project Management Office",
    "QA": "Quality Assurance Engineer",
    "QE": "Quality Engineer",
    "SDET": "Software Development Engineer in Test",
    "DevOps": "DevOps Engineer",
    "SRE": "Site Reliability Engineer",
    "TL": "Tech Lead",
    "EM": "Engineering Manager",
    "EngMgr": "Engineering Manager",
    "Mgr": "Manager",
    "Lead": "Team Lead",
    "IC": "Individual Contributor",
    "SM": "Scrum Master",

    # Data / ML
    "DS": "Data Scientist",
    "DA": "Data Analyst",
    "BI": "Business Intelligence",
    "ML": "Machine Learning",
    "MLE": "Machine Learning Engineer",
    "MLEng": "Machine Learning Engineer",
    "MLOps": "MLOps Engineer",
    "DataEng": "Data Engineer",
    "DBA": "Database Administrator",

    # Product / Design / Leadership
    "UX": "User Experience",
    "UI": "User Interface",
    "CTO": "Chief Technology Officer",
    "CPO": "Chief Product Officer",
    "CEO": "Chief Executive Officer",
    "VP": "Vice President",
    "CFO": "Chief Financial Officer",
    "COO": "Chief Operating Officer",
    "CIO": "Chief Information Officer",
    "CISO": "Chief Information Security Officer",
    "SVP": "Senior Vice President",
    "AVP": "Associate Vice President",

    # Seniority
    "Sr": "Senior",
    "Jr": "Junior",
    "Sr.": "Senior",
    "Jr.": "Junior",

    # Other common shorthand
    "BD": "Business Development",
    "AI": "Artificial Intelligence",
    "SDR": "Sales Development Representative",
    "BDR": "Business Development Representative",
    "AE": "Account Executive",
    "CS": "Customer Success",
    "HR": "Human Resources",
    "Ops": "Operations",
    "FTE": "Full-time Employee",
    "Intern": "Intern",
}



MIME_TYPE_FOLDER = "application/vnd.google-apps.folder"


def extract_folder_id(drive_url: str) -> str:
    """Trích xuất folder_id từ link Google Drive public"""
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", drive_url)
    if match:
        return match.group(1)
    raise ValueError("❌ Không tìm thấy folder ID trong link Drive")

def get_drive_service(API_KEY):
    """Tạo service kết nối Google Drive API bằng API key"""
    return build("drive", "v3", developerKey=API_KEY, credentials=AnonymousCredentials())

def list_files_in_folder(service, folder_id: str):
    """Liệt kê file/folder trong thư mục public"""
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get("files", [])


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
    # If the string contains Vietnamese-specific characters (đ, ă, â, ê, ô, ơ, ư), treat as not English
    if re.search(r"[đĐăââêôơưĂÂÊÔƠƯ]", s):
        return False

    ascii_letters = re.findall(r"[A-Za-z]", s)
    ascii_ratio = len(ascii_letters) / max(1, len(s))

    lowers = s.lower()
    # Common English indicator words
    english_indicators = {"the", "and", "or", "is", "are", "candidate", "experience", "skills", "find", "finds", "looking", "for", "with", "years", "year"}

    # If plenty of ASCII letters and contains spaces or english words -> likely English
    if ascii_ratio > 0.6:
        # check if any english indicator appears as a separate word
        words = re.findall(r"\w+", lowers)
        if any(w in english_indicators for w in words):
            return True
        # if it's multiple ASCII words (has spaces) assume English-ish
        if len(words) >= 2:
            return True

    # If mixed ASCII but fewer letters, still check for clear English keywords
    if 0.25 < ascii_ratio <= 0.6:
        words = re.findall(r"\w+", lowers)
        if any(w in english_indicators for w in words):
            return True

    return False


def expand_abbreviations(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    # Prepare a canonical uppercase-keyed map for case-insensitive lookup
    canonical_map = {k.upper(): v for k, v in ABBREV_MAP.items()}
    keys = list(canonical_map.keys())
    # Sort by length so longer keys (e.g., 'SDE') match before shorter ones ('DE')
    keys.sort(key=lambda x: -len(x))
    # Allow optional plural suffix 's' or 'es' after the abbreviation
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")(?:s|es)?\b", flags=re.IGNORECASE)

    def _repl(m):
        base = m.group(1)
        full = m.group(0)
        suffix = full[len(base):]  # '' or 's' or 'es'
        replacement = canonical_map.get(base.upper())
        if replacement is None:
            return full
        # Prevent replacing inside email addresses or URLs like hr@example.com or dev.team@company
        start, end = m.start(), m.end()
        if (start > 0 and text[start-1] in ('@', '.')) or (end < len(text) and text[end] in ('@', '.')):
            return full

        # Preserve plural if present
        if suffix:
            # simple pluralization: append the same suffix
            return f"{replacement}{suffix}"
        return replacement

    return pattern.sub(_repl, text)

if __name__ == "__main__":
    # A set of bilingual test cases from easy -> harder to validate expand_abbreviations
    # test_cases = [
    #     # Easy / exact
    #     "DE",
    #     "SDE",
    #     "FE",
    #     "BE",
    #     # Simple English sentences
    #     "Find candidate: DE",
    #     "Looking for an SDE.",
    #     "Hiring FE and BE engineers",
    #     # Vietnamese short forms
    #     "Tìm ứng viên vị trí DE",
    #     "Cần SDE cho team backend",
    #     # Mixed text and punctuation
    #     "Senior DE, 5+ years",
    #     "Apply: FE/BE fullstack",
    #     "Ứng tuyển vị trí: DE, SE và QA",
    #     # Plurals and suffixes
    #     "DEs available",
    #     "SDEs in HCM",
    #     # Abbreviations inside longer sentences
    #     "Looking for a Sr DevOps (SRE/DevOps) to lead infra",
    #     "Tìm Data Engineer (DE) hoặc Data Scientist (DS) có kinh nghiệm",
    #     # Harder / ambiguous cases
    #     "Fullstack engineer (Fullstack) with React + Node",
    #     "Hiring ML / MLE for production",
    #     "We need a PM or PdM to manage roadmap",
    #     "Tuyển: Sr, Jr, EngMgr, EM",
    # ]

    # print("Running expand_abbreviations tests:\n")
    # for tc in test_cases:
    #     expanded = expand_abbreviations(tc)
    #     print(f"Original: {tc!r}\nExpanded: {expanded!r}\n")

    # Tests for is_probably_english (after expansion)
    print("\nRunning is_probably_english tests:\n")
    english_tests = [
        "Find candidates with Python and SQL",
        "Looking for a Data Engineer with 3 years experience",
        "This is an English sentence",
        "Apply now",
        "Tìm ứng viên vị trí DE",  # after expand -> should still contain vietnamese words, so not english
        "Ứng tuyển: Data Engineer, có kinh nghiệm 3 năm",
        "Senior Software Engineer, 5+ years",
        "Tuyển dụng - Apply here",
        "We need a PM or PdM to manage roadmap",
        "Gửi CV to hr@example.com",
        "Tìm ứng viên học tại India University"
    ]

    for t in english_tests:
        expanded = expand_abbreviations(t)
        is_eng = is_probably_english(expanded)
        print(f"Text: {t!r}\nExpanded: {expanded!r}\nIs_English: {is_eng}\n")