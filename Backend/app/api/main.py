# E:\Scan-CV\Backend\app\api\main.py
from fastapi import FastAPI, Request, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import tempfile, shutil, os, uuid
from fastapi.staticfiles import StaticFiles

from app.models.models import SessionLocal
from app.rag_pipeline.workflow import build_flow 
from app.text2SQL.process_cvs_sql import process_cvs_sql     
from app.services.extract_cv import process_cv_rag
from app.services.get_cv_url_from_gcs import upload_pdf_and_get_url_gcs  
from app.services.extract_cv import extract_text_from_pdf, extract_info

from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY, QDRANT_COLLECTION, QDRANT_URL, EMBEDDING_MODEL_NAME
from config.storage import MEDIA_ROOT 
from langchain_deepseek import ChatDeepSeek
from qdrant_client import QdrantClient
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from sqlalchemy import text as sa_text
from fastapi import FastAPI, Depends

deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

embedding = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, api_key=GOOGLE_API_KEY, request_timeout=60)
qdrant = QdrantClient(url=QDRANT_URL)
flow = build_flow(deepseek, embedding, qdrant, QDRANT_COLLECTION, limit=10)

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
        # return {
        #     "rag_info": info,      # JSON từ bước RAG
        #     "sql_info": results[0] # JSON từ bước Text2SQL
        # }

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


@app.post("/query")
async def query_api(request: QueryRequest):
    question = request.question.strip()
    print("Received question:", question)
    state = {"question": question}
    result = flow.invoke(state)

    # print('result:', result)
    if request.links_only:
        route = result.get("route")
        cv_links = []

        if route == "SQL":
            cols = result.get("columns") or []
            rows = result.get("sql_result") or []

            for r in rows:
                if "resume_url" in cols:
                    resume_url = r[cols.index("resume_url")]
                elif len(r) > len(cols):
                    resume_url = r[-1]   
                else:
                    resume_url = None

                rec = dict(zip(cols, r[:len(cols)]))

                cv_links.append({
                    "candidate_id": rec.get("id") or rec.get("candidate_id"),
                    "full_name": rec.get("full_name"),
                    "email": rec.get("email"),
                    "resume_url": resume_url,
                })

        elif route == "VECTOR":
            for item in result.get("vector_result") or []:
                p = item.get("payload", item)
                cv_links.append({
                    "candidate_id": None,
                    "full_name": p.get("candidate_name"),
                    "email": p.get("email"),
                    "resume_url": p.get("resume_url"),
                })

        return {"route": route, "cv_links": cv_links}

    return {
        "question": request.question,
        "provider": request.provider,
        "model": request.model,
        "route": result.get("route"),
        "sql": result.get("sql_query"),
        "columns": result.get("columns"),
        "rows": result.get("sql_result"),
        "trials": result.get("trials"),
        "final_answer": result.get("final_answer"),
        "vector_query": result.get("vector_query"),
        "vector_result": result.get("vector_result"),
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

# giao diện Qdrant: http://localhost:6333/dashboard
# uvicorn app.api.main:app --reload --port 8000