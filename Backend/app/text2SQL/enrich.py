# --- Helper: build URL & enrich resume_url từ attachments ---
from typing import Any, Dict
from sqlalchemy import text as sa_text 
from typing import List, Dict, Tuple, Any, Optional
from sqlalchemy.engine import Engine

# def build_local_url(path: str | None, base_url: str | None) -> str | None:
#     """
#     Nếu attachment chưa có public_url (GCP/S3), build URL local dạng:
#     http://localhost:8000/media/<path>
#     """
#     if not path or not base_url:
#         return None
#     return f"{base_url.rstrip('/')}/media/{path.lstrip('/')}"

# def enrich_with_resume_urls(
#     engine: Engine,
#     columns: List[str],
#     rows: List[Tuple[Any, ...]],
#     base_url: str | None = None,
# ) -> List[Dict[str, Any]]:
#     """
#     Từ kết quả SELECT (có cột id), tra bảng attachments để lấy CV mới nhất của từng ứng viên,
#     rồi bổ sung field 'resume_url' (ưu tiên attachments.public_url, fallback sang URL local).
#     Trả về danh sách dict theo cột.
#     """
#     records = [dict(zip(columns, r)) for r in rows]
#     if not records or "id" not in columns:
#         return records

#     cand_ids = list({r["id"] for r in records if r.get("id") is not None})
#     if not cand_ids:
#         return records

#     sql = """
#     SELECT x.candidate_id, x.public_url, x.path
#     FROM (
#         SELECT
#             a.candidate_id,
#             a.public_url,
#             a.path,
#             ROW_NUMBER() OVER (
#                 PARTITION BY a.candidate_id
#                 ORDER BY a.created_at DESC NULLS LAST
#             ) AS rn
#         FROM attachments a
#         WHERE a.candidate_id = ANY(:ids)
#     ) x
#     WHERE x.rn = 1;
#     """

#     with engine.connect() as conn:
#         rs = conn.execute(sa_text(sql), {"ids": cand_ids}).fetchall()

#     latest = {row._mapping["candidate_id"]: dict(row._mapping) for row in rs}

#     for rec in records:
#         att = latest.get(rec["id"])
#         url = None
#         if att:
#             # ưu tiên public_url (GCP/S3); nếu chưa có => tự build URL local
#             url = att.get("public_url") or build_local_url(att.get("path"), base_url)
#         rec["resume_url"] = url

#     return records

def build_local_url(path: Optional[str], base_url: Optional[str]) -> Optional[str]:
    """Nếu attachment chưa có public_url (GCS/S3), build URL local dạng:
    http://<host>/media/<path>
    """
    if not path or not base_url:
        return None
    return f"{base_url.rstrip('/')}/media/{path.lstrip('/')}"

def enrich_with_resume_urls(
    engine: Engine,
    columns: List[str],
    rows: List[Tuple[Any, ...]],
    base_url: Optional[str] = None,
    id_column: Optional[str] = None, 
) -> List[Dict[str, Any]]:
    """
    Ghép 'resume_url' theo candidate_id.
    - Tự động chọn cột khoá: id_column (nếu truyền) -> 'candidate_id' -> 'id'
    - Không làm mất hàng: nếu không tìm được URL thì để None.
    """
    if not rows or not columns:
        return []

    records = [dict(zip(columns, r)) for r in rows]

    # xác định cột khoá để lookup attachments
    key_col = (
        id_column
        if id_column
        else ("candidate_id" if "candidate_id" in columns else ("id" if "id" in columns else None))
    )
    if key_col is None:
        # Không có khoá ứng viên => trả về như cũ (không enrich)
        for rec in records:
            rec.setdefault("resume_url", None)
        return records

    cand_ids = sorted({rec.get(key_col) for rec in records if rec.get(key_col) is not None})
    if not cand_ids:
        for rec in records:
            rec.setdefault("resume_url", None)
        return records

    sql = """
        SELECT t.candidate_id, t.public_url, t.path
        FROM (
            SELECT
                a.candidate_id,
                a.public_url,
                a.path,
                ROW_NUMBER() OVER (
                    PARTITION BY a.candidate_id
                    ORDER BY a.created_at DESC NULLS LAST
                ) AS rn
            FROM attachments a
            WHERE a.candidate_id = ANY(:ids)
        ) AS t
        WHERE t.rn = 1;
    """
    with engine.connect() as conn:
        rs = conn.execute(sa_text(sql), {"ids": cand_ids}).fetchall()

    latest = {row._mapping["candidate_id"]: dict(row._mapping) for row in rs}

    for rec in records:
        att = latest.get(rec.get(key_col))
        url = None
        if att:
            url = att.get("public_url") or build_local_url(att.get("path"), base_url)
        rec["resume_url"] = url

    return records