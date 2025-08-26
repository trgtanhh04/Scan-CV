# =========================
# 5) Pipeline chính (MAC-lite)
# =========================
from sqlalchemy import Engine
from .llm_adapter import LLM
import re
from .schema_utils import load_schema, render_schema
from .selector import selector_lite
from .guards import sql_guard, schema_guard, run_sql, refine_prompt
from .postprocess import postprocess_sql
import sqlglot.expressions as exp
from typing import List, Tuple, Dict, Any
from sqlalchemy import text as sa_text
from .prompting import build_schema_prompt
from .enrich import enrich_with_resume_urls
from typing import List, Dict, Tuple, Any, Optional



# def answer_sql(
#     engine: Engine,
#     llm: LLM,
#     user_query: str,
#     max_refine: int = 1
# ) -> Dict[str, Any]:
#     # a) selector → subset schema
#     tables, hints = selector_lite(user_query)
#     schema = load_schema(engine, only=tables)
#     schema_txt = render_schema(schema)

#     # b) generate
#     prompt = build_schema_prompt(schema_txt, hints, user_query)
#     sql = llm.gen(prompt)

#     trials: List[Tuple[str, str]] = []

#     for attempt in range(max_refine + 1):
#         try:
#             sql_guard(sql)

#             # NEW: schema guard — nếu sai bảng/cột, fail-soft trả rỗng + cảnh báo
#             warn = schema_guard(sql, schema)
#             if warn:
#                 return {
#                     "sql": postprocess_sql(sql),   # vẫn pretty để xem
#                     "columns": [],
#                     "rows": [],
#                     "trials": trials + [(sql, warn)],
#                     "warning": warn
#                 }

#             # DISTINCT/EXISTS post-process
#             sql = postprocess_sql(sql)

#             cols, rows = run_sql(engine, sql)

#             # Empty → refine
#             if len(rows) == 0 and attempt < max_refine:
#                 trials.append((sql, "empty result"))
#                 sql = llm.gen(refine_prompt(schema_txt, user_query, sql, "empty result"))
#                 continue

#             return {"sql": sql, "columns": cols, "rows": [tuple(r) for r in rows], "trials": trials}

#         except Exception as e:
#             if attempt < max_refine:
#                 trials.append((sql, str(e)))
#                 sql = llm.gen(refine_prompt(schema_txt, user_query, sql, str(e)))
#             else:
#                 # fail-soft lần cuối: trả rỗng + warning
#                 return {
#                     "sql": sql,
#                     "columns": [],
#                     "rows": [],
#                     "trials": trials + [(sql, f"db_error: {e}")],
#                     "warning": "Query failed at execution. Returned empty result."
#                 }
def answer_sql(
    engine: Engine,
    llm: LLM,
    user_query: str,
    max_refine: int = 1,
    *,
    base_url: Optional[str] = None,     # <--- THÊM
) -> Dict[str, Any]:
    # a) selector → subset schema
    tables, hints = selector_lite(user_query)
    schema = load_schema(engine, only=tables)
    schema_txt = render_schema(schema)

    # b) generate
    prompt = build_schema_prompt(schema_txt, hints, user_query)
    sql = llm.gen(prompt)

    trials: List[Tuple[str, str]] = []

    for attempt in range(max_refine + 1):
        try:
            sql_guard(sql)

            # NEW: schema guard (fail-soft)
            warn = schema_guard(sql, schema)
            if warn:
                pretty_sql = postprocess_sql(sql)
                return {
                    "sql": pretty_sql,
                    "columns": [],
                    "rows": [],
                    "trials": trials + [(sql, warn)],
                    "warning": warn,
                }

            # DISTINCT/EXISTS post-process
            sql = postprocess_sql(sql)

            cols, rows = run_sql(engine, sql)

            # --- ENRICH: thêm resume_url nếu có cột id ---
            enriched_records = enrich_with_resume_urls(engine, cols, rows, base_url=base_url)
            if enriched_records:
                # bảo đảm có cột 'resume_url'
                if "resume_url" not in cols:
                    cols = cols + ["resume_url"]
                rows = [tuple(rec.get(c) for c in cols) for rec in enriched_records]
            # ---------------------------------------------

            # Empty → refine
            if len(rows) == 0 and attempt < max_refine:
                trials.append((sql, "empty result"))
                sql = llm.gen(refine_prompt(schema_txt, user_query, sql, "empty result"))
                continue

            return {"sql": sql, "columns": cols, "rows": [tuple(r) for r in rows], "trials": trials}

        except Exception as e:
            if attempt < max_refine:
                trials.append((sql, str(e)))
                sql = llm.gen(refine_prompt(schema_txt, user_query, sql, str(e)))
            else:
                # fail-soft lượt cuối
                return {
                    "sql": sql,
                    "columns": [],
                    "rows": [],
                    "trials": trials + [(sql, f"db_error: {e}")],
                    "warning": "Query failed at execution. Returned empty result.",
                }