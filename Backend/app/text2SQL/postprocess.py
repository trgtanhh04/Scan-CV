
from __future__ import annotations
import sqlglot
import sqlglot.expressions as exp
from typing import Optional, List
import re

# ==================================================
# 5) DISTINCT/EXISTS postprocess (AST with sqlglot) — 27.8.x SAFE
# ==================================================
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
        • Nếu SELECT có cột từ bảng khác -> DISTINCT ON (c.id) + ORDER BY c.id [, e.start_date DESC]
        • Ngược lại -> SELECT DISTINCT
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
