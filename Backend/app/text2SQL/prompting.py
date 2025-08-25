# ===============================
# 2) PROMPT (schema + examples)
# ===============================
EXAMPLES = [
    (
        "ứng viên biết Angular và ở HCM",
        """SELECT c.id, c.full_name, c.location
        FROM candidates c
        JOIN candidate_skills cs ON cs.candidate_id = c.id
        JOIN skills s ON s.id = cs.skill_id
        WHERE s.name ILIKE '%Angular%' AND c.location ILIKE '%HCM%'
        LIMIT 50;"""
    ),
    (
        "ai từng làm ở Accenture sau 2018",
        """SELECT c.id, c.full_name, e.company, e.start_date, e.end_date
        FROM candidates c
        JOIN experiences e ON e.candidate_id = c.id
        WHERE e.company ILIKE '%Accenture%'
        AND (e.start_date >= '2019-01-01' OR (e.end_date IS NULL AND e.is_current = TRUE))
        ORDER BY e.start_date DESC
        LIMIT 50;"""
    ),
    (
        "names and universities of candidates who studied Computer Science",
        """SELECT DISTINCT c.id, c.full_name, e.university, e.degree
        FROM candidates c
        JOIN educations e ON e.candidate_id = c.id
        WHERE e.degree ILIKE '%Computer Science%'
        LIMIT 50;"""
    )
]

def build_schema_prompt(schema_txt: str, hints: str, user_query: str) -> str:
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