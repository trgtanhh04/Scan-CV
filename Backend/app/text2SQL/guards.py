# ==============================
# 4) Guards / Execute / Refine
# ==============================
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Tuple, Any, Optional
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy import create_engine, text as sa_text
from .schema_utils import SchemaSummary

SAFE_SELECT = re.compile(r"^\s*select\b", re.IGNORECASE | re.DOTALL)
FORBIDDEN   = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke)\b", re.IGNORECASE)

def sql_guard(sql: str):
    if not SAFE_SELECT.search(sql):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(sql):
        raise ValueError("Dangerous SQL keyword detected.")

# ---- schema guard: phát hiện bảng/cột không tồn tại (fail-soft) ----
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