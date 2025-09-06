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
class ColumnInfo:
    name: str
    type: str

@dataclass
class TableInfo:
    name: str
    columns: List[ColumnInfo]

@dataclass
class SchemaSummary:
    tables: Dict[str, TableInfo] 

def load_schema(engine: Engine, only: Optional[List[str]] = None) -> SchemaSummary:
    insp = sa_inspect(engine)
    tables: Dict[str, TableInfo] = {}
    for t in insp.get_table_names():
        if only and t not in only:
            continue
        cols = [ColumnInfo(name=c["name"], type=str(c["type"])) for c in insp.get_columns(t)]
        tables[t] = TableInfo(name=t, columns=cols)
    return SchemaSummary(tables=tables)

def render_schema(schema: SchemaSummary) -> str:
    lines = []
    for t in schema.tables.values():
        col_defs = ", ".join([f"{c.name} ({c.type})" for c in t.columns])
        lines.append(f"<{t.name}({col_defs})>")
    return "\n".join(lines)
