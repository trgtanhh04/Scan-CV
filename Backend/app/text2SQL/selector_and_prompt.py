
from __future__ import annotations
import re
from typing import List, Tuple


# =========================
# 1) SELECTOR (rule-based)
# =========================
EXP_WORDS   = r"(kinh nghiệm|từng làm|đã làm|làm việc|company|công ty|experience|worked)"
EDU_WORDS = r"(bằng cấp|đại học|university|degree|gpa|điểm trung bình|học|tốt nghiệp|education|studied|field of study)"
LOC_WORDS   = r"(địa điểm|location|ở|tại|HCM|HCMC|Ho Chi Minh|Hà Nội|Hanoi|Huế|Đà Nẵng|Singapore|USA|UK)"
LANG_WORDS  = r"(ngôn ngữ|language|languages|tiếng anh|tiếng nhật|english|japanese|vietnamese)"
CERT_WORDS  = r"(chứng chỉ|certificate|chứng nhận)"
SKILL_HINT = r"(skill|skills|k[ỹy]\s*n[ăa]ng|know|python|java|aws|spark|golang|pytorch|sql)"

def selector_lite(user_query: str) -> Tuple[List[str], str]:
    """
    Trả về (danh_sách_bảng_cần, hints chuỗi) dựa theo từ khóa.
    """
    uq = user_query.lower()
    tables = {"candidates"}  # mặc định luôn cần ứng viên

    hints = []

    if re.search(SKILL_HINT, uq):
        tables |= {"skills", "candidate_skills"}
        hints.append("This query involves candidate skills; join skills via candidate_skills.")
        hints.append("If returning a candidate list, use DISTINCT or EXISTS to avoid duplicates.")

    if re.search(EXP_WORDS, uq):
        tables |= {"experiences"}
        hints.append("This query involves work experiences; join experiences on candidate_id.")

    if re.search(EDU_WORDS, uq):
        tables |= {"educations"}
        hints.append("This query involves education; join education on candidate_id.")

    if re.search(LANG_WORDS, uq):
        tables |= {"languages", "candidate_languages"}
        hints.append("This query involves languages; join languages via candidate_languages.")
        hints.append("For unique candidates, use DISTINCT or EXISTS when combining many-to-many joins.")

    if re.search(CERT_WORDS, uq):
        tables |= {"certifications"}
        hints.append("This query involves certifications.")
        hints.append("For unique candidates, use DISTINCT or EXISTS when combining many-to-many joins.")

    if re.search(LOC_WORDS, uq):
        hints.append("User mentions location; consider filtering candidates.location with ILIKE.")

    if not hints:
        hints.append("If unsure, start from candidates and add joins only if needed.")

    return sorted(tables), " ".join(hints)


# ===============================
# 2) PROMPT (schema + examples)
# ===============================
EXAMPLES = [
    (
        "ứng viên biết Angular và ở HCM",
        """SELECT c.id, c.full_name, c.email, c.location
        FROM candidates c
        JOIN candidate_skills cs ON cs.candidate_id = c.id
        JOIN skills s ON s.id = cs.skill_id
        WHERE s.name ILIKE '%Angular%' AND c.location ILIKE '%HCM%'
        LIMIT 50;"""
    ),
    (
        "ai từng làm ở Accenture sau 2018",
        """SELECT c.id, c.full_name, c.email, e.company, e.start_date, e.end_date
        FROM candidates c
        JOIN experiences e ON e.candidate_id = c.id
        WHERE e.company ILIKE '%Accenture%'
        AND (e.start_date >= '2019-01-01' OR (e.end_date IS NULL AND e.is_current = TRUE))
        ORDER BY e.start_date DESC
        LIMIT 50;"""
    ),
    (
        "names and universities of candidates who studied Computer Science",
        """SELECT DISTINCT c.id, c.full_name, c.email, e.university, e.degree
        FROM candidates c
        JOIN educations e ON e.candidate_id = c.id
        WHERE e.degree ILIKE '%Computer Science%'
        LIMIT 50;"""
    ),
    (
        "List all candidate names.",
        """SELECT id, full_name, c.email FROM candidates_info LIMIT 50;"""
    )
]

def build_schema_prompt(schema_txt: str, hints: str, user_query: str, limit: int) -> str:
    ex_txt = "\n\n".join([f"Q: {q}\nSQL:\n{sql}" for q, sql in EXAMPLES])
    prompt = f"""
        You are a Text-to-SQL assistant for a PostgreSQL database.

        Rules:
        - Output ONE PostgreSQL SELECT query only (no commentary).
        - No INSERT/UPDATE/DELETE/DDL.
        - Use table/column names exactly as in schema.
        - Prefer ILIKE for fuzzy text filter.
        - Add LIMIT 50 unless user asks otherwise.
        - Many-to-many joins (skills/languages) create duplicates: if returning a candidate list, use SELECT DISTINCT or use EXISTS for multiple skill conditions.
        - ALWAYS include the candidate id column (e.g. id) in the SELECT result, even if the user only asks for names. This is required for downstream enrichment (e.g. resume_url).
        - ALWAYS include the candidate email column (e.g. email) in the SELECT result if available, even if the user does not explicitly ask for it. This is required for downstream enrichment.
        - Hint: When subtracting two DATE columns in PostgreSQL, result is in days (integer). Do NOT use INTERVAL literal.
        - If the user asks for only names, return both id and name.

        Limit:
        {limit}

        Schema:
        {schema_txt}

        Hints for this question:
        {hints}

        Examples:
        {ex_txt}

        Now write SQL for:
        "{user_query}"
            """.strip()
    return prompt