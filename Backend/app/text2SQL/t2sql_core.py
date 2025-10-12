from __future__ import annotations

# ===================== Imports =====================
import os
import re
import sys
import logging
from dataclasses import dataclass
from typing import List, Dict, Tuple, Any, Optional
from sqlalchemy.orm import Session

import sqlglot
import sqlglot.expressions as exp
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.engine import Engine
from unidecode import unidecode
from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek

from .selector_and_prompt import build_schema_prompt, selector_lite
from .schema_utils import load_schema, render_schema, SchemaSummary
from .enrich import enrich_with_resume_urls


sys.path.append(os.path.abspath('../../'))
from config.config import DEEPSEEK_API_KEY, DATABASE_URL


# ===================== Logging =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("scan-cv.sql")


# ===================== LLM Adapter =====================
class LLM:
    """Thin wrapper để trích SQL từ LLM output (gỡ ```sql ... ```)."""
    def __init__(self, invoke_fn):
        self._invoke = invoke_fn

    def gen(self, prompt: str) -> str:
        out = self._invoke(prompt).strip()
        out = re.sub(r"^```(?:sql|SQL)?\s*|\s*```$", "", out, flags=re.MULTILINE).strip()
        return out


# ===================== Guards =====================
SAFE_SELECT = re.compile(r"^\s*select\b", re.IGNORECASE | re.DOTALL)
FORBIDDEN   = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke)\b",
    re.IGNORECASE,
)

def sql_guard(sql: str) -> None:
    """Chỉ cho phép SELECT và chặn từ khóa nguy hiểm."""
    if not SAFE_SELECT.search(sql):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(sql):
        raise ValueError("Dangerous SQL keyword detected.")

def _extract_tables(sql: str) -> List[str]:
    """
    Parse SQL properly to get real table names.
    Avoids false positives like EXTRACT(YEAR FROM AGE(...)) where 'FROM AGE' confused regex.
    """
    try:
        node = sqlglot.parse_one(sql, read="postgres")
        return [t.this.name for t in node.find_all(exp.Table)]
    except Exception:
        # fail-soft: return empty (better than wrong)
        return []

def _extract_qualified_cols(sql: str) -> List[Tuple[str, str]]:
    """
    Return list of (table_or_alias, column_name) for qualified columns (t.col).
    """
    out: List[Tuple[str, str]] = []
    try:
        node = sqlglot.parse_one(sql, read="postgres")
        for col in node.find_all(exp.Column):
            # col.table is Identifier or None; col.name is column name
            table_name = None
            if col.table:
                if isinstance(col.table, exp.Identifier):
                    table_name = col.table.this
                else:
                    table_name = str(col.table)
            if table_name:
                out.append((table_name, col.name))
    except Exception:
        pass
    return out

# ================================
# 2) Schema guard
# ================================
def schema_guard(sql: str, schema: 'SchemaSummary') -> Optional[str]:
    """
    Validate table/column names using sqlglot AST (no regex).
    Returns warning string if invalid; otherwise None.
    """
    # known tables & columns
    known_tables = set(schema.tables.keys())
    # chỉ lấy tên cột, tránh ColumnInfo unhashable
    table_cols: Dict[str, set] = {
        t.name: set(c.name for c in t.columns)
        for t in schema.tables.values()
    }

    # parse once
    try:
        node = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        # nếu parse lỗi thì không guard quá gắt
        return None

    # collect tables + alias map
    used_tables: set[str] = set()
    alias_map: Dict[str, str] = {}  # alias -> real table

    for t in node.find_all(exp.Table):
        real_name = t.this.name if isinstance(t.this, exp.Identifier) else str(t.this)
        used_tables.add(real_name)

        # alias, if any
        if t.alias:
            alias_name = None
            if isinstance(t.alias, exp.TableAlias):
                if isinstance(t.alias.this, exp.Identifier):
                    alias_name = t.alias.this.this
                else:
                    alias_name = str(t.alias.this)
            elif isinstance(t.alias, exp.Identifier):
                alias_name = t.alias.this
            elif isinstance(t.alias, str):
                alias_name = t.alias
            if alias_name:
                alias_map[alias_name] = real_name
        else:
            # allow referencing table by its own name as "alias" too
            alias_map[real_name] = real_name

    # unknown tables?
    unknown_tbls = sorted([t for t in used_tables if t not in known_tables])
    if unknown_tbls:
        return f"Unknown tables: {unknown_tbls}. Allowed: {sorted(known_tables)}."

    # qualified columns check
    bad_cols: List[Tuple[str, str, str]] = []  # (alias_or_table, real_table, col)
    for alias, col in set(_extract_qualified_cols(sql)):
        alias_str = str(alias)
        real_table = alias_map.get(alias_str, alias_str)
        if real_table in table_cols and col not in table_cols[real_table]:
            bad_cols.append((alias_str, real_table, col))

    if bad_cols:
        msg = ", ".join([f"{a}.{c} (table {t})" for a, t, c in bad_cols])
        return f"Unknown columns: {msg}. Please use only existing columns per schema."

    return None

# ===================== SQL exec & refine =====================
def run_sql(engine: Engine, sql: str) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    with engine.connect() as conn:
        rs = conn.execute(sa_text(sql))
        rows = rs.fetchall()
        cols = list(rs.keys())
    return cols, rows

def refine_prompt(schema_txt: str, user_query: str, prev_sql: str, reason: str) -> str:
    return f"""
        The schema is:
        {schema_txt}

        User question:
        {user_query}

        The previous SQL was:
        {prev_sql}

        It failed or returned empty because:
        {reason}

        Please return ONLY a corrected PostgreSQL SELECT query (no explanation).
    """.strip()


# ===================== DISTINCT/EXISTS post-process =====================
def _root_select(node: exp.Expression) -> Optional[exp.Select]:
    return node if isinstance(node, exp.Select) else node.find(exp.Select)

def _find_alias_for_table(sel: exp.Select, table_name: str) -> Optional[str]:
    from_ = sel.find(exp.From)
    if not from_:
        return None
    for t in from_.find_all(exp.Table):
        if t.this and t.this.name == table_name:
            return t.alias_or_name
    return None

def _has_group_by(sel: exp.Select) -> bool:
    return sel.find(exp.Group) is not None

def _has_any_join(sel: exp.Select) -> bool:
    return sel.find(exp.Join) is not None

def _has_count_agg(sel: exp.Select) -> bool:
    return any(isinstance(fn, exp.Count) for fn in sel.find_all(exp.Count))

def _select_refs_other_tables(sel: exp.Select, base_alias: str) -> bool:
    for item in sel.expressions:
        node = item.this if isinstance(item, exp.Alias) else item
        if isinstance(node, exp.Star):
            return True
        if isinstance(node, exp.Column) and node.table and node.table != base_alias:
            return True
    return False

def _first_table_alias(sel: exp.Select, table_name: str) -> Optional[str]:
    for t in sel.find_all(exp.Table):
        if t.this and t.this.name == table_name:
            return t.alias_or_name
    return None

def _ordered(expr_node: exp.Expression, desc: bool = False) -> exp.Ordered:
    return exp.Ordered(this=expr_node, desc=bool(desc))

def _ensure_order_by_prefix(sel: exp.Select,
                            first_terms: List[exp.Ordered],
                            extra_terms: Optional[List[exp.Ordered]] = None) -> None:
    ob = sel.args.get("order")
    existing = list(ob.expressions) if ob else []

    def _exists_eq(term: exp.Ordered) -> bool:
        return any(str(t.sql()) == str(term.sql()) for t in existing)

    new_terms: List[exp.Ordered] = []
    for t in first_terms:
        if not _exists_eq(t):
            new_terms.append(t)
    new_terms.extend(existing)
    if extra_terms:
        for t in extra_terms:
            if not _exists_eq(t):
                new_terms.append(t)

    sel.set("order", exp.Order(expressions=new_terms))

def _supports_distinct_on() -> bool:
    return hasattr(exp, "DistinctOn")  # sqlglot >= 28

def _inject_distinct_on(sql_text: str, cand_alias: str) -> str:
    if re.search(r'(?i)\bselect\s+distinct\s+on\s*\(', sql_text):
        return sql_text
    return re.sub(r'(?i)\bselect\s+distinct\b',
                  f"SELECT DISTINCT ON ({cand_alias}.id)",
                  sql_text,
                  count=1)

def postprocess_sql(sql: str) -> str:
    """
    Rule:
    - Nếu FROM candidates (+ alias) và có JOIN, không GROUP BY, không COUNT:
      + Nếu SELECT có cột từ bảng khác -> DISTINCT ON (c.id) + ORDER BY c.id [, e.start_date DESC]
      + Ngược lại -> SELECT DISTINCT
    """
    if " count(" in sql.lower():
        return sql

    try:
        parsed = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return sql

    sel = _root_select(parsed)
    if not sel or _has_group_by(sel) or not _has_any_join(sel) or _has_count_agg(sel):
        return sql

    cand_alias = _find_alias_for_table(sel, "candidates")
    if not cand_alias:
        return sql

    selects_other = _select_refs_other_tables(sel, cand_alias)

    if selects_other:
        first_terms = [
            _ordered(exp.Column(this=exp.Identifier(this="id"),
                                table=exp.Identifier(this=cand_alias)))
        ]
        extra_terms: List[exp.Ordered] = []
        e_alias = _first_table_alias(sel, "experiences")
        if e_alias:
            extra_terms.append(
                _ordered(
                    exp.Column(this=exp.Identifier(this="start_date"),
                               table=exp.Identifier(this=e_alias)),
                    desc=True
                )
            )
        _ensure_order_by_prefix(sel, first_terms, extra_terms)

        if _supports_distinct_on():
            sel.set(
                "distinct",
                exp.DistinctOn(expressions=[
                    exp.Column(this=exp.Identifier(this="id"),
                               table=exp.Identifier(this=cand_alias))
                ])
            )
            return sel.sql(dialect="postgres", pretty=True)

        if not sel.args.get("distinct"):
            sel.set("distinct", exp.Distinct())
        return _inject_distinct_on(sel.sql(dialect="postgres", pretty=True), cand_alias)

    if not sel.args.get("distinct"):
        sel.set("distinct", exp.Distinct())
    return sel.sql(dialect="postgres", pretty=True)


# ===================== Fallbacks & helpers =====================
def _extract_missing_tables_from_warn(warn: str) -> List[str]:
    m = re.search(r"Unknown tables:\s*\[([^\]]+)\]", warn or "")
    if not m:
        return []
    raw = m.group(1)
    return [t.strip().strip("'\"") for t in raw.split(",") if t.strip()]

def _db_has_tables(schema: SchemaSummary, names: List[str]) -> bool:
    known = set(schema.tables.keys())
    return all(n in known for n in names)

def _skill_terms_from_query(q: str) -> List[str]:
    qn = unidecode((q or "").lower())
    vocab = ["python","java","golang","aws","spark","pytorch","sql",
             "datatable","pandas","numpy","scikit","airflow"]
    return [kw for kw in vocab if kw in qn]

def _fallback_sql_experiences_like(skills: List[str], limit: int) -> str:
    def _regex_word_match(column: str, kw: str) -> str:
        # Escape single quotes in kw for SQL literal
        esc = kw.replace("'", "''")
        # Use a regex that matches the keyword as a whole word (non-alnum boundaries)
        # (^|[^A-Za-z0-9])KW($|[^A-Za-z0-9])  -> wrapped as case-insensitive (~*)
        regex = f"(^|[^A-Za-z0-9]){esc}($|[^A-Za-z0-9])"
        return f"{column} ~* '{regex}'"

    like_or = " AND ".join(
        [f"({_regex_word_match('e.job_title', kw)} OR {_regex_word_match('e.description', kw)})" for kw in skills]
    ) or "TRUE"
    return f"""
        SELECT DISTINCT c.id, c.full_name
        FROM candidates c
        JOIN experiences e ON e.candidate_id = c.id
        WHERE {like_or}
        LIMIT {limit}
        """.strip()


# ===================== Orchestrator =====================
@dataclass
class AnswerResult:
    sql: str
    columns: List[str]
    rows: List[List[Any]]
    trials: List[Tuple[str, str]]
    warning: Optional[str] = None

def answer_sql(
    engine: Engine,
    llm: LLM,
    user_query: str,
    max_refine: int = 1,
    limit: int = 10,
    *,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    tables, hints = selector_lite(user_query)
    schema = load_schema(engine, only=tables)
    schema_txt = render_schema(schema)

    prompt = build_schema_prompt(schema_txt, hints, user_query, limit)
    sql = llm.gen(prompt)

    trials: List[Tuple[str, str]] = []

    for attempt in range(max_refine + 1):
        try:
            # ---- Guards
            sql_guard(sql)

            warn = schema_guard(sql, schema)
            if warn and "Unknown tables:" in warn and attempt < max_refine:
                missing = _extract_missing_tables_from_warn(warn)
                schema = load_schema(engine, only=None)              # widen once
                schema_txt = render_schema(schema)

                if _db_has_tables(schema, missing):
                    sql = llm.gen(build_schema_prompt(schema_txt, hints, user_query, limit))
                    trials.append((sql, "widened schema due to unknown tables"))
                    continue
                else:
                    skill_terms = _skill_terms_from_query(user_query)
                    if skill_terms:
                        sql = _fallback_sql_experiences_like(skill_terms, limit)
                        warn = None
                    else:
                        pretty_sql = postprocess_sql(sql)
                        return {
                            "sql": pretty_sql, 
                            "columns": [], 
                            "rows": [],
                            "trials": trials + [(sql, warn)], 
                            "warning": warn,
                        }

            # ---- Post-process + Execute
            sql = postprocess_sql(sql)
            # log.info("[answer_sql] EXEC_SQL:\n%s", sql)

            cols, raw_rows = run_sql(engine, sql)
            # log.info("[answer_sql] RES rows=%d cols=%d", len(raw_rows), len(cols or []))
            cols = list(cols or [])

            # ---- Enrich resume_url
            id_col = "candidate_id" if "candidate_id" in cols else ("id" if "id" in cols else None)
            enriched = enrich_with_resume_urls(engine, cols, raw_rows, base_url=base_url, id_column=id_col)


            desired_cols = ["id", "email", "resume_url"]
            packed_rows: List[List[Any]] = [[rec.get(c) for c in desired_cols] for rec in enriched]
            cols = desired_cols


            # ---- Empty -> refine
            if len(packed_rows) == 0 and attempt < max_refine:
                trials.append((sql, "empty result"))
                sql = llm.gen(refine_prompt(schema_txt, user_query, sql, "empty result"))
                continue
            
            print("Final SQL:", sql)
            print("Final Columns:", cols)
            print("Final Rows:", packed_rows)

            return {"sql": sql, "columns": cols, "rows": packed_rows, "trials": trials}

        except Exception as e:
            if attempt < max_refine:
                trials.append((sql, str(e)))
                sql = llm.gen(refine_prompt(schema_txt, user_query, sql, str(e)))
            else:
                log.exception("Query failed")
                return {
                    "sql": sql, "columns": [], "rows": [],
                    "trials": trials + [(sql, f"db_error: {e}")],
                    "warning": "Query failed at execution. Returned empty result.",
                }


# ===================== CLI run =====================
if __name__ == "__main__":
    engine = create_engine(DATABASE_URL, future=True)

    deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)
    def _invoke(prompt: str) -> str:
        resp = deepseek.invoke([HumanMessage(content=prompt)])
        return resp.content

    llm = LLM(_invoke)

    q = "List candidates with the job title 'Software Engineer'."
    result = answer_sql(engine, llm, q, max_refine=1)
    print("SQL:\n", result["sql"])
    print("Columns:", result["columns"])
    print("Results:", result["rows"])
    print("Trials:", result["trials"])

