# E:\Scan-CV\Backend\app\api\main.py
from fastapi import FastAPI, Request, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import tempfile, shutil, os, uuid
from fastapi.staticfiles import StaticFiles

from app.models.models import SessionLocal
# from app.rag_pipeline.workflow import flow   # graph build sẵn
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


deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

embedding = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, api_key=GOOGLE_API_KEY)
qdrant = QdrantClient(url=QDRANT_URL)
flow = build_flow(deepseek, embedding, qdrant, QDRANT_COLLECTION, limit=50)

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

        # process_cvs của RAG
        # _ = process_cv(
        #     file_path=temp_path,
        #     vector_db=qdrant,   
        #     embedding_model=embedding,
        #     collection_name="candidates"
        # )

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

@app.post("/query")
async def query_api(request: QueryRequest):
    state = {"question": request.question}
    result = flow.invoke(state)
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
        "final_answer": result.get("final_answer"),
    }

# giao diện Qdrant: http://localhost:6333/dashboard
# uvicorn app.api.main:app --reload --port 8000