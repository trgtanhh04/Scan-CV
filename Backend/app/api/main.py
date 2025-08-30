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
from app.services.extract_cv import process_cv     

from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY
from config.storage import MEDIA_ROOT, build_public_url 
from langchain_deepseek import ChatDeepSeek
from qdrant_client import QdrantClient
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from sqlalchemy import create_engine

deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)


embedding = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-exp-03-07", api_key=GOOGLE_API_KEY)
# engine = create_engine("postgresql://postgres:phatdeptrai123@localhost:5432/candidates")

db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../qdrant_gemini_db"))
qdrant = QdrantClient(path=db_path)
COLLECTION_NAME = "candidates"
public_base_url = None  # hoặc "http://localhost:8000"
flow = build_flow(deepseek, embedding, qdrant, COLLECTION_NAME, limit=50, public_base_url=public_base_url)

app = FastAPI(title="CV Manager API")
app.mount("/cvs", StaticFiles(directory="raw/cvs"), name="cvs")


# Ensure MEDIA_ROOT exists before mounting static files
import os
os.makedirs(str(MEDIA_ROOT), exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")

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

        # 1) process_cvs của RAG
        # info = process_cv(
        #     file_path=temp_path,
        #     vector_db=qdrant,   
        #     embedding_model=embedding,
        #     collection_name="candidates"
        # )
        # 2) process_cvs của Text2Sql
        results = process_cvs_sql(
            input_dir=temp_dir,
            # output_file chỉ là log/tổng hợp – đặt ra ngoài Backend luôn cho thống nhất
            output_file=str(MEDIA_ROOT / "batch_result.json"),
            db=db, llm=deepseek, limit=1,
        )

        if not results:
            return {"error": "Không xử lý được"}
        # return {
        #     "rag_info": info,      # JSON từ bước RAG
        #     "sql_info": results[0] # JSON từ bước Text2SQL
        # }

        return results[0]

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


# uvicorn app.api.main:app --reload --port 8000