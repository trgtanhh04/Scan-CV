
import os
import re
import sys
from typing import List, Dict, Tuple, Any, Optional
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.engine import Engine
import sqlglot
from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek
import sqlglot.expressions as exp


from .selector_and_prompt import build_schema_prompt, selector_lite
from .schema_utils import load_schema, render_schema, SchemaSummary
from .enrich import enrich_with_resume_urls

sys.path.append(os.path.abspath('../../'))
from config.config import DEEPSEEK_API_KEY, DATABASE_URL


# ============== LLM Adapter ==============
class LLM:
    def __init__(self, invoke_fn):
        self._invoke = invoke_fn

    def gen(self, prompt: str) -> str:
        out = self._invoke(prompt).strip()
        # remove markdown fences if any
        out = re.sub(r"^```(?:sql|SQL)?\s*|\s*```$", "", out, flags=re.MULTILINE).strip()
        return out

# ============== Guards ==============
SAFE_SELECT = re.compile(r"^\s*select\b", re.IGNORECASE | re.DOTALL)
FORBIDDEN   = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke)\b", re.IGNORECASE)

def sql_guard(sql: str):
    if not SAFE_SELECT.search(sql):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(sql):
        raise ValueError("Dangerous SQL keyword detected.")

_TBL_PATTERN = re.compile(r'\bFROM\s+([a-zA-Z_]\w*)|\bJOIN\s+([a-zA-Z_]\w*)', re.IGNORECASE)
_COL_DOTS    = re.compile(r'\b([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)\b')

def _extract_tables(sql: str) -> List[str]:
    return [a or b for (a, b) in _TBL_PATTERN.findall(sql)]

def _extract_qualified_cols(sql: str) -> List[Tuple[str, str]]:
    return _COL_DOTS.findall(sql)  # list of (aliasOrTable, col)

def schema_guard(sql: str, schema: SchemaSummary) -> Optional[str]:
    """
    Trả về chuỗi cảnh báo nếu phát hiện bảng/cột không hợp lệ. Hợp lệ -> None.
    """
    known_tables = set(schema.tables.keys())
    used_tables  = set(_extract_tables(sql))
    unknown_tbls = sorted([t for t in used_tables if t not in known_tables])

    if unknown_tbls:
        return f"Unknown tables: {unknown_tbls}. Allowed: {sorted(known_tables)}."

    # map table->cols
    table_cols: Dict[str, set] = {t.name: set(t.columns) for t in schema.tables.values()}

    # alias map FROM/JOIN
    alias_map: Dict[str, str] = {}
    for m in re.finditer(r'\b(FROM|JOIN)\s+([a-zA-Z_]\w*)(?:\s+(?:AS\s+)?([a-zA-Z_]\w*))?', sql, re.IGNORECASE):
        table = m.group(2)
        alias = m.group(3)
        if alias:
            alias_map[alias] = table
        else:
            alias_map[table] = table

    bad_cols: List[Tuple[str, str, str]] = []  # (alias, real_table, col)
    for alias, col in set(_extract_qualified_cols(sql)):
        real_table = alias_map.get(alias, alias)  # nếu không alias, xem alias là tên bảng
        if real_table in table_cols and col not in table_cols[real_table]:
            bad_cols.append((alias, real_table, col))

    if bad_cols:
        msg = ", ".join([f"{a}.{c} (table {t})" for a, t, c in bad_cols])
        return f"Unknown columns: {msg}. Please use only existing columns per schema."

    return None


# ============== SQL exec + refine ==============
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

# ============== DISTINCT/EXISTS post-process ==============

def _root_select(node: exp.Expression) -> Optional[exp.Select]:
    return node if isinstance(node, exp.Select) else node.find(exp.Select)

def _find_candidates_alias(sel: exp.Select) -> Optional[str]:
    from_ = sel.find(exp.From)
    if not from_:
        return None
    for t in from_.find_all(exp.Table):
        if t.this and t.this.name == "candidates":
            return t.alias_or_name
    return None

def _has_group_by(sel: exp.Select) -> bool:
    return sel.find(exp.Group) is not None

def _has_any_join(sel: exp.Select) -> bool:
    return sel.find(exp.Join) is not None

def _has_count_agg(sel: exp.Select) -> bool:
    return any(isinstance(fn, exp.Count) for fn in sel.find_all(exp.Count))

def _select_refs_other_tables(sel: exp.Select, cand_alias: str) -> bool:
    for item in sel.expressions:
        node = item.this if isinstance(item, exp.Alias) else item
        if isinstance(node, exp.Star):
            return True
        if isinstance(node, exp.Column) and node.table and node.table != cand_alias:
            return True
    return False

def _first_experiences_alias(sel: exp.Select) -> Optional[str]:
    for t in sel.find_all(exp.Table):
        if t.this and t.this.name == "experiences":
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
    # 27.8.0 chưa expose DistinctOn class
    return hasattr(exp, "DistinctOn")

def _inject_distinct_on(sql_text: str, cand_alias: str) -> str:
    """
    Idempotent:
    - Nếu đã có 'SELECT DISTINCT ON (' -> giữ nguyên
    - Nếu chỉ có 'SELECT DISTINCT' -> đổi thành 'SELECT DISTINCT ON (cand_alias.id)'
    """
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
    low = sql.lower()
    if " count(" in low:
        return sql

    try:
        parsed = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return sql

    sel = _root_select(parsed)
    if not sel or _has_group_by(sel) or not _has_any_join(sel) or _has_count_agg(sel):
        return sql

    cand_alias = _find_candidates_alias(sel)
    if not cand_alias:
        return sql

    selects_other = _select_refs_other_tables(sel, cand_alias)

    if selects_other:
        # ORDER BY cand.id (và e.start_date desc nếu có)
        first_terms = [
            _ordered(exp.Column(this=exp.Identifier(this="id"),
                                table=exp.Identifier(this=cand_alias)))
        ]
        extra_terms: List[exp.Ordered] = []
        e_alias = _first_experiences_alias(sel)
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
            # sqlglot >= 28: có DistinctOn
            sel.set(
                "distinct",
                exp.DistinctOn(expressions=[
                    exp.Column(this=exp.Identifier(this="id"),
                               table=exp.Identifier(this=cand_alias))
                ])
            )
            return sel.sql(dialect="postgres", pretty=True)

        # sqlglot 27.8.x: DISTINCT + chèn "ON (cand.id)" bằng text
        if not sel.args.get("distinct"):
            sel.set("distinct", exp.Distinct())
        sql_text = sel.sql(dialect="postgres", pretty=True)
        return _inject_distinct_on(sql_text, cand_alias)

    # Chỉ cột từ candidates → DISTINCT
    if not sel.args.get("distinct"):
        sel.set("distinct", exp.Distinct())
    return sel.sql(dialect="postgres", pretty=True)


# ============== Orchestrator/Pipeline ==============
def answer_sql(
    engine: Engine,
    llm,
    user_query: str,
    max_refine: int = 1,
    limit: int = 10,
    *,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    # a) selector -> subset schema + schema text
    tables, hints = selector_lite(user_query)
    schema = load_schema(engine, only=tables)
    schema_txt = render_schema(schema)

    # b) generate initial SQL
    prompt = build_schema_prompt(schema_txt, hints, user_query, limit)
    sql = llm.gen(prompt)

    trials: List[Tuple[str, str]] = []

    for attempt in range(max_refine + 1):
        try:
            # --- Guards ---
            sql_guard(sql)

            warn = schema_guard(sql, schema)  # cảnh báo sai bảng/cột (fail-soft)
            if warn:
                pretty_sql = postprocess_sql(sql)
                return {
                    "sql": pretty_sql,
                    "columns": [],
                    "rows": [],
                    "trials": trials + [(sql, warn)],
                    "warning": warn,
                }

            # --- Post-process DISTINCT / ORDER BY cho m-n ---
            sql = postprocess_sql(sql)
            print("[answer_sql] EXEC_SQL:\n", sql)

            # --- Execute ---
            cols, raw_rows = run_sql(engine, sql)
            cols = list(cols or [])  # luôn là list
            print(f"[answer_sql] RES rows={len(raw_rows)} cols={len(cols or [])}")

            # --- Enrich resume_url ---
            id_col = "candidate_id" if "candidate_id" in cols else ("id" if "id" in cols else None)

            enriched = enrich_with_resume_urls(
                engine,
                cols,
                raw_rows,
                base_url=base_url,
                id_column=id_col,          
            )

            if enriched:
                if "resume_url" not in cols:
                    cols = cols + ["resume_url"]
                packed_rows: List[List[Any]] = [[rec.get(c) for c in cols] for rec in enriched]
            else:
                packed_rows = [list(r) for r in raw_rows]

            # --- Empty -> refine ---
            if len(packed_rows) == 0 and attempt < max_refine:
                trials.append((sql, "empty result"))
                sql = llm.gen(refine_prompt(schema_txt, user_query, sql, "empty result"))
                continue

            return {
                "sql": sql,
                "columns": cols,
                "rows": packed_rows,
                "trials": trials,
            }

        except Exception as e:
            if attempt < max_refine:
                trials.append((sql, str(e)))
                sql = llm.gen(refine_prompt(schema_txt, user_query, sql, str(e)))
            else:
                return {
                    "sql": sql,
                    "columns": [],
                    "rows": [],
                    "trials": trials + [(sql, f"db_error: {e}")],
                    "warning": "Query failed at execution. Returned empty result.",
                }
            
            

if __name__ == "__main__":

    # 1) Postgres engine
    engine = create_engine(DATABASE_URL, future=True)

    # 2) DeepSeek client (LangChain)
    deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

    def _invoke(prompt: str) -> str:
        resp = deepseek.invoke([HumanMessage(content=prompt)])
        return resp.content

    llm = LLM(_invoke) 

    # 3) Hỏi thử
    q = "List candidates with the job title 'Software Engineer'."
    result = answer_sql(engine, llm, q, max_refine=1)
    print("SQL:\n", result["sql"])
    print("Columns:", result["columns"])
    print("Results:", result["rows"])
    print("Trials:", result["trials"])
