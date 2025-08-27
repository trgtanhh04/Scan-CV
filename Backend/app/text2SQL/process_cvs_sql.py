# E:\Scan-CV\Backend\app\text2SQL\process_cvs_sql.py
# ===== Batch ingest helpers (final) =====
import os, uuid, shutil, mimetypes, json
from pathlib import Path
from typing import Optional, List
from sqlalchemy.orm import Session

from app.services.info_extract import extract_text_from_pdf, extract_info
from app.models.ingest import insert_candidate_to_db
from config.storage import MEDIA_ROOT, CV_DIR, build_public_url  # <--- dùng config chung

# ---- Attachment ghi vào DB ----
def save_attachment_for_batch(
    db: Session,
    *,
    candidate_id: int,
    rel_path: str,
    original_name: Optional[str],
    storage: str = "local",
    public_url: Optional[str] = None,
):
    """Ghi 1 bản ghi Attachment (đã có model Attachment)."""
    from app.models.models import Attachment  # import cục bộ tránh vòng lặp

    mime = mimetypes.guess_type(rel_path)[0] or "application/pdf"
    size = None
    try:
        size = (MEDIA_ROOT / rel_path).stat().st_size
    except Exception:
        pass

    att = Attachment(
        candidate_id=candidate_id,
        original_name=original_name,
        mime_type=mime,
        size_bytes=size,
        storage=storage,
        path=rel_path,
        public_url=public_url,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att

# ---- Pipeline ingest 1 folder ----
def process_cvs_sql(
    input_dir: str,
    output_file: str,
    db: Session,
    llm,
    limit: int = 1,
):
    """
    - Quét *.pdf trong input_dir (tối đa 'limit')
    - Copy sang MEDIA_ROOT/cv/{uuid}.pdf
    - extract_text_from_pdf -> extract_info(llm) -> insert_candidate_to_db
    - Lưu Attachment (public_url = http(s)://.../media/cv/<uuid>.pdf)
    - Ghi file tổng hợp JSON (kết quả trích xuất)
    """
    input_dir = str(input_dir)
    results: List[dict] = []

    pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]
    pdf_files = pdf_files[:limit]

    for filename in pdf_files:
        src = Path(input_dir) / filename
        print(f"Processing {src}...")

        # 1) copy vào MEDIA_ROOT/cv/{uuid}.pdf
        ext = src.suffix.lower() or ".pdf"
        fid = f"{uuid.uuid4().hex}{ext}"
        dst = CV_DIR / fid
        shutil.copyfile(src, dst)
        rel_path = f"cv/{dst.name}"

        # 2) trích xuất & LLM
        text = extract_text_from_pdf(str(dst))
        info = extract_info(text, llm)

        # 3) upsert ứng viên
        cand = insert_candidate_to_db(db, info)

        # 4) build URL public & lưu attachment
        file_url = build_public_url(rel_path)  # <--- dùng config.storage
        save_attachment_for_batch(
            db=db,
            candidate_id=cand.id,
            rel_path=rel_path,
            original_name=filename,
            storage="local",
            public_url=file_url,
        )

        # 5) tổng hợp trả về FE
        rec = dict(info or {})
        rec["source_file"] = filename
        rec["resume_url"] = file_url
        rec["candidate_id"] = cand.id
        results.append(rec)

    # 6) lưu JSON tổng hợp (đặt ngoài Backend nếu muốn)
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(results)} CVs into {out_path}")
    return results

# --- Test local (tùy chọn) ---
if __name__ == "__main__":
    from app.models.models import create_all, SessionLocal
    from langchain_deepseek import ChatDeepSeek
    from config.config import DEEPSEEK_API_KEY

    deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

    # DB session for local test
    engine = create_all("postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv")
    SessionLocal.configure(bind=engine)
    with SessionLocal() as db:
        out = process_cvs_sql(
            input_dir=r"E:\Scan-CV\Backend\raw",
            output_file=str(MEDIA_ROOT / "batch_result.json"),
            db=db,
            llm=deepseek,
            limit=10,
        )
        print(out[:2])
