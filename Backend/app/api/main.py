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

@app.post("/query")
async def query_api(request: QueryRequest):
    try:
        question = request.question.strip()
        state = {"question": question}
        result = enrich_final_answer(state)
        return {
            "question": request.question,
            "provider": request.provider,
            "model": request.model,
            "route": result.get("route"),
            "final_answer": result.get("final_answer"),
        }
    except Exception as e:
        import traceback
        print("QUERY_ERROR:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/__debug/qdrant")
def dbg_qdrant():
    try:
        return qdrant.get_collections().dict()
    except Exception as e:
        return {"error": str(e)}
    
@app.get("/__debug/qcount")
def qcount():
    try:
        # Count whole collection (no filter). Construct CountRequest with only `exact`.
        from qdrant_client.models import CountRequest
        req = CountRequest(exact=True)
        return qdrant.count(QDRANT_COLLECTION, req).dict()
    except Exception as e:
        return {"error": f"qcount failed: {e}"}


# from fastapi import Header, HTTPException
# from app.models.models import create_all

# ADMIN_INIT_TOKEN = os.getenv("ADMIN_INIT_TOKEN")  # đặt secret này ở Cloud Run

# @app.post("/__admin/init-db")
# def admin_init_db(x_token: str = Header(None)):
#     if not ADMIN_INIT_TOKEN or x_token != ADMIN_INIT_TOKEN:
#         raise HTTPException(status_code=403, detail="forbidden")
#     url = os.getenv("DATABASE_URL")
#     create_all(url)
#     return {"ok": True}

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

@app.get("/__debug/qinfo")
def dbg_qinfo():
    try:
        info = qdrant.get_collection(QDRANT_COLLECTION).dict()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        dim = len(embedding.embed_query("hello"))
    except Exception as e:
        dim = f"embed_error: {e}"
    return {
        "ok": True,
        "collection": QDRANT_COLLECTION,
        "collection_info": info,  # sẽ thấy vectors_config
        "embedding_dim": dim,
    }


# giao diện Qdrant: http://localhost:6333/dashboard
# uvicorn app.api.main:app --reload --port 8000
