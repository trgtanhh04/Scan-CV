# E:\Scan-CV\Backend\app\api\main.py
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import tempfile, shutil, os, uuid


from app.models.models import SessionLocal
from app.rag_pipeline.workflow import enrich_final_answer 
from app.text2SQL.process_cvs_sql import process_cvs_sql     
from app.services.extract_cv import process_cv_rag
from app.services.get_cv_url_from_gcs import upload_pdf_and_get_url_gcs  
from app.services.extract_cv import extract_text_from_pdf, extract_info

from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY, QDRANT_COLLECTION, QDRANT_URL, EMBEDDING_MODEL_NAME, QDRANT_API_KEY
from config.storage import MEDIA_ROOT 
from langchain_deepseek import ChatDeepSeek
from qdrant_client import QdrantClient
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from sqlalchemy import text as sa_text
from fastapi import FastAPI, Depends


deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

embedding = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, api_key=GOOGLE_API_KEY, request_timeout=60)
qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

app = FastAPI(title="CV Manager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/cv/upload")
async def upload_cv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        # # --- Opt-in: auto-create DB schema when missing ---
        # # This is disabled by default. Set AUTO_CREATE_DB=true in env to enable (useful for testing).
        # import os
        # try:
        #     with SessionLocal().get_bind().connect() as conn:
        #         # simple check: does 'candidates' table exist?
        #         res = conn.execute(sa_text("SELECT to_regclass('public.candidates')")).scalar()
        #         if res is None and os.getenv('AUTO_CREATE_DB', 'false').lower() == 'true':
        #             # create tables using project's helper
        #             url = os.getenv('DATABASE_URL')
        #             models_create_all(url)
        # except Exception:
        #     # ignore errors here — we'll surface real errors later during upload
        #     pass

        # Lưu tạm file người dùng up
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, f"{uuid.uuid4().hex}.pdf")
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # (1) get url from gcs
        resume_url = upload_pdf_and_get_url_gcs(temp_path)
        

        # (2) Extract 1 lần
        text = extract_text_from_pdf(temp_path)
        info = extract_info(text) or {}

        # (3) RAG 
        rag_results = process_cv_rag(
            file_path=temp_path,
            vector_db=qdrant,
            embedding_model=embedding,
            collection_name=QDRANT_COLLECTION,
            pre_text=text,
            pre_info=info,
            resume_url=resume_url,
        )

        # (4) Text2SQL 
        sql_results = process_cvs_sql(
            input_dir=temp_dir,
            output_file=str(MEDIA_ROOT / "batch_result.json"),
            db=db,
            limit=1,
            single_file_path=temp_path,
            pre_public_url=resume_url,
            original_name=file.filename,
            pre_text=text,
            pre_info=info,
        )

        if not sql_results:
            return {"error": "Không xử lý được"}

        return sql_results[0]

    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

# --- Search / Query ---
class QueryRequest(BaseModel):
    question: str
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    links_only: bool = False   

# @app.post("/query")
# async def query_api(request: QueryRequest):
#     question = request.question.strip()
#     state = {"question": question}

#     # invoke flow
#     result = enrich_final_answer(state)

#     return {
#         "question": request.question,
#         "provider": request.provider,
#         "model": request.model,
#         "route": result.get("route"),
#         "final_answer": result.get("final_answer"),
#     }
from fastapi.responses import JSONResponse
from qdrant_client.models import CountRequest

@app.post("/query")
async def query_api(request: QueryRequest):
    try:
        question = (request.question or "").strip()
        if not question:
            return JSONResponse(status_code=400, content={"error": "question is empty"})

        # Smoke-check nhanh Qdrant trước khi gọi pipeline
        try:
            cnt = qdrant.count(QDRANT_COLLECTION, CountRequest(exact=True)).count
        except Exception as e:
            # Lỗi kết nối / auth Qdrant
            return JSONResponse(status_code=200, content={"error": f"Qdrant error: {e}"})

        # Gọi pipeline chính
        result = enrich_final_answer({"question": question})

        return {
            "question": request.question,
            "provider": request.provider,
            "model": request.model,
            "route": (result or {}).get("route"),
            "final_answer": (result or {}).get("final_answer"),
            "qdrant_count": cnt,
        }

    # Bắt mọi lỗi còn lại để trả JSON thay vì 500 text/plain
    except Exception as e:
        import traceback
        print("QUERY_ERROR\n", traceback.format_exc())  # sẽ thấy stacktrace trong Cloud Run logs
        return JSONResponse(
            status_code=200,
            content={
                "error": str(e),
                "hint": "Xem Cloud Run logs (ERROR) để thấy stacktrace chi tiết.",
            },
        )


@app.get("/__debug/qenv")
def dbg_qenv():
    import os
    return {
      "has_url": bool(os.getenv("QDRANT_URL")),
      "has_key": bool(os.getenv("QDRANT_API_KEY")),
      "collection": os.getenv("QDRANT_COLLECTION"),
    }


@app.get("/__debug/db")
def debug_db():
    engine = SessionLocal().get_bind()
    with engine.connect() as conn:
        info = conn.execute(sa_text("""
            SELECT
              current_database()  AS db,
              current_user        AS user,
              inet_server_addr()  AS host,
              inet_server_port()  AS port,
              current_schema      AS schema,
              (SELECT setting FROM pg_settings WHERE name='search_path') AS search_path
        """)).mappings().first()

        cands = conn.execute(sa_text("SELECT COUNT(*) AS n FROM candidates")).scalar() or 0
        exps  = conn.execute(sa_text("SELECT COUNT(*) AS n FROM experiences")).scalar() or 0

        # Test câu SQL đang lỗi
        test_sql = """
        SELECT DISTINCT c.id, c.full_name
        FROM candidates c
        WHERE EXISTS (
            SELECT 1 FROM candidate_skills cs1
            JOIN skills s1 ON s1.id = cs1.skill_id
            WHERE cs1.candidate_id = c.id AND s1.name ILIKE '%Python%'
        )
        AND EXISTS (
            SELECT 1 FROM candidate_skills cs2
            JOIN skills s2 ON s2.id = cs2.skill_id
            WHERE cs2.candidate_id = c.id AND s2.name ILIKE '%Java%'
        )
        AND (
            SELECT COUNT(DISTINCT company) 
            FROM experiences 
            WHERE candidate_id = c.id
        ) >= 2
        LIMIT 10;
        """
        rows = conn.execute(sa_text(test_sql)).fetchall()

    return {
        "engine_url_used": str(engine.url),   # xem API đang trỏ DB nào
        "info": dict(info) if info else None,
        "counts": {"candidates": cands, "experiences": exps},
        "test_query_rows": [dict(r._mapping) for r in rows],
    }
from google.cloud import storage
import google.auth
@app.get("/__debug/gcs")
def debug_gcs():
    info = {}
    # 1) In ra SA đang chạy
    try:
        import requests
        email = requests.get(
            "http://metadata/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor":"Google"},
            timeout=2
        ).text
        info["runtime_service_account"] = email
    except Exception as e:
        info["runtime_service_account"] = f"unknown: {e}"

    # 2) Thử upload 1 object nhỏ
    bucket = os.getenv("GCS_BUCKET", "cv-uploads-prod")
    key = f"debug/{uuid.uuid4().hex}.txt"
    try:
        client = storage.Client()
        blob = client.bucket(bucket).blob(key)
        blob.upload_from_string("hello-from-cloud-run", content_type="text/plain")
        public_url = f"https://storage.googleapis.com/{bucket}/{key}"
        return {"ok": True, "sa": info["runtime_service_account"], "bucket": bucket, "key": key, "url": public_url}
    except Exception as e:
        import traceback
        return {
            "ok": False,
            "sa": info.get("runtime_service_account"),
            "bucket": bucket,
            "key": key,
            "error": str(e),
            "trace": traceback.format_exc(),
        }
@app.get("/__debug/qdrant")
def dbg_qdrant():
    try:
        return qdrant.get_collections().dict()
    except Exception as e:
        return {"error": str(e)}
    
@app.get("/__debug/qcount")
def qcount():
    from qdrant_client.models import CountRequest
    try:
        return qdrant.count(os.getenv("QDRANT_COLLECTION"), CountRequest(exact=True)).dict()
    except Exception as e:
        return {"error": str(e)}


from fastapi import Header, HTTPException
from app.models.models import create_all

ADMIN_INIT_TOKEN = os.getenv("ADMIN_INIT_TOKEN")  # đặt secret này ở Cloud Run

@app.post("/__admin/init-db")
def admin_init_db(x_token: str = Header(None)):
    if not ADMIN_INIT_TOKEN or x_token != ADMIN_INIT_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")
    url = os.getenv("DATABASE_URL")
    create_all(url)
    return {"ok": True}

@app.get("/__debug/query-smoke")
def query_smoke():
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    try:
        # 1) test embed
        _ = embedding.embed_query("hello world")

        # 2) test Qdrant search (không filter nếu bạn chưa có payload phù hợp)
        res = qdrant.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=embedding.embed_query("data engineer 3 years"),
            limit=3
        )
        return {"ok": True, "hits": len(res)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# giao diện Qdrant: http://localhost:6333/dashboard
# uvicorn app.api.main:app --reload --port 8000
