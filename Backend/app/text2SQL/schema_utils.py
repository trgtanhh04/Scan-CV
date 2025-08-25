from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Tuple, Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy import inspect as sa_inspect

# =========================
# 0) SCHEMA INTROSPECTION
# =========================
@dataclass
class TableInfo:
    name: str
    columns: List[str]

@dataclass
class SchemaSummary:
    tables: Dict[str, TableInfo]  # name -> info

def load_schema(engine: Engine, only: Optional[List[str]] = None) -> SchemaSummary:
    insp = sa_inspect(engine)
    tables: Dict[str, TableInfo] = {}
    for t in insp.get_table_names():
        if only and t not in only:
            continue
        cols = [c["name"] for c in insp.get_columns(t)]
        tables[t] = TableInfo(name=t, columns=cols)
    return SchemaSummary(tables=tables)

def render_schema(schema: SchemaSummary) -> str:
    lines = []
    for t in schema.tables.values():
        cols = ", ".join(t.columns)
        lines.append(f"<{t.name}({cols})>")
    return "\n".join(lines)