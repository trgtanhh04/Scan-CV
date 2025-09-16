# E:\Scan-CV\Backend\app\text2SQL\process_cvs_sql.py
# ===== Batch ingest helpers (final) =====
import os, uuid, shutil, mimetypes, json
from pathlib import Path
from typing import Optional, List, Callable
from sqlalchemy.orm import Session
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from services.extract_cv import extract_text_from_pdf, extract_info
from models.ingest import insert_candidate_to_db
# use models.create_all helper for creating tables
from app.models.models import create_all as models_create_all, SessionLocal
from sqlalchemy import text as sa_text
from config.storage import MEDIA_ROOT
from services.get_cv_url_from_gcs import upload_pdf_and_get_url_gcs


def save_attachment_for_batch(
    db: Session,
    *,
    candidate_id: int,
    object_key: str,                
    original_name: Optional[str],
    public_url: str,             
    storage: str = "gcs",          
    size_bytes: Optional[int] = None, 
):
    """
    Lưu 1 Attachment trỏ tới file trên GCS:
    - path: lưu object_key (vd: 'resumes/uuid/01.pdf')
    - public_url: URL mở được (public hoặc signed)
    - storage: 'gcs'
    """
    from app.models.models import Attachment  # tránh vòng lặp import

    guess_src = original_name or object_key
    mime = mimetypes.guess_type(guess_src)[0] or "application/pdf"

    att = Attachment(
        candidate_id=candidate_id,
        original_name=original_name,
        mime_type=mime,
        size_bytes=size_bytes, 
        storage=storage,         # 'gcs'
        path=object_key,         
        public_url=public_url,
    )
    db.add(att)
    db.commit()
    db.refresh(att)


def _object_key_from_gcs_url(url: str) -> Optional[str]:
    # URL dạng: https://storage.googleapis.com/<bucket>/<object_key>
    try:
        parts = url.split("/", 4)
        return parts[4] if len(parts) >= 5 else None
    except Exception:
        return None

# ---- Pipeline ingest 1 folder ----
def process_cvs_sql(
    input_dir: str,
    output_file: str,
    db: Session,
    limit: int = 1,
    *,
    gcs_uploader: Callable[[str], str] = upload_pdf_and_get_url_gcs,
    single_file_path: Optional[str] = None,
    pre_public_url: Optional[str] = None,
    original_name: Optional[str] = None,
    pre_text: Optional[str] = None, 
    pre_info: Optional[dict] = None,  
) -> List[dict]:
    
    # create all tables if not exist (opt-in via AUTO_CREATE_DB)
    try:
        # acquire raw connection from the configured SessionLocal's engine
        with SessionLocal().get_bind().connect() as conn:
            # simple check: does 'candidates' table exist?
            res = conn.execute(sa_text("SELECT to_regclass('public.candidates')")).scalar()
            if res is None and os.getenv('AUTO_CREATE_DB', 'false').lower() == 'true':
                # create tables using project's helper; prefer explicit DATABASE_URL if provided
                url = os.getenv('DATABASE_URL')
                if url:
                    models_create_all(url)
                else:
                    models_create_all()
    except Exception:
        # ignore errors here — we'll surface real errors later during upload
        pass
    input_dir = str(input_dir)
    results: List[dict] = []

    if single_file_path:
        pdf_files = [Path(single_file_path).name]
        input_dir = str(Path(single_file_path).parent)
        limit = 1
    else:
        pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]

    for filename in pdf_files[:limit]:
        src = Path(input_dir) / filename
        print(f"Processing {src}...")

        # chỉ rút trích nếu chưa có pre_text / pre_info
        text = pre_text if (pre_text is not None and src.samefile(single_file_path or src)) else extract_text_from_pdf(str(src))
        info = pre_info if (pre_info is not None and src.samefile(single_file_path or src)) else (extract_info(text) or {})

        cand = insert_candidate_to_db(db, info)

        if pre_public_url and single_file_path and src.samefile(single_file_path):
            file_url = pre_public_url
        else:
            file_url = gcs_uploader(str(src))

        object_key = _object_key_from_gcs_url(file_url) or f"resumes/{uuid.uuid4().hex}.pdf"
        save_attachment_for_batch(
            db=db,
            candidate_id=cand.id,
            object_key=object_key,       # ví dụ: 'resumes/128a65c5.../01.pdf'
            original_name=filename,
            public_url=file_url,              # ví dụ: 'https://storage.googleapis.com/.../01.pdf'
            storage="gcs",
        )

        rec = dict(info)
        rec["source_file"]  = original_name or filename
        rec["resume_url"]   = file_url
        rec["candidate_id"] = cand.id
        results.append(rec)

    # 6) lưu JSON
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

    file_path = '../../raw/cvs/01.pdf'
    text = extract_text_from_pdf(file_path)
    info = extract_info(text) or {}

    # DB session cho test local
    engine = create_all("postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv")
    SessionLocal.configure(bind=engine)

    with SessionLocal() as db:
        out = process_cvs_sql(
            input_dir=r"E:\Scan-CV\Backend\raw",
            output_file=str(MEDIA_ROOT / "batch_result.json"),
            db=db,
            limit=10,
            single_file_path=file_path,     # test chỉ 1 file
            pre_text=text,                  # tái sử dụng text extract
            pre_info=info,                  # tái sử dụng JSON extract
        )
        print(out[:2])
# python process_cvs_sql.py