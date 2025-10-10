# E:\Scan-CV\Backend\app\api\main.py
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
import tempfile, shutil, os, uuid
from fastapi import Form


from app.models.models import SessionLocal
from app.rag_pipeline.workflow import enrich_final_answer
from app.rag_pipeline.exp_workflow import build_flow
from app.text2SQL.process_cvs_sql import process_cvs_sql     
from app.services.extract_cv import process_cv_rag
from app.services.get_cv_url_from_gcs import upload_pdf_and_get_url_gcs  
from app.services.extract_cv import extract_text_from_pdf, extract_info
from app.services.filter_search import search_filter_sql
from app.models.ingest import get_unique_job_titles
from app.models.models import Candidate, Educations, candidate_skills, Skill, Attachment

from app.text2SQL.enrich import enrich_with_resume_urls

from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY, QDRANT_COLLECTION, QDRANT_URL, EMBEDDING_MODEL_NAME, QDRANT_API_KEY
from config.storage import MEDIA_ROOT 
from langchain_deepseek import ChatDeepSeek
from qdrant_client import QdrantClient
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from sqlalchemy import text as sa_text
from sqlalchemy import or_
from fastapi import FastAPI, Depends
from typing import List, Optional
from qdrant_client import models



deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

embedding = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, google_api_key=GOOGLE_API_KEY, request_timeout=60)
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

@app.get("/candidate/count")
def get_candidates(db: Session = Depends(get_db)):
    results = (
    db.query(Candidate.job_apply, func.count(Candidate.id))
    .group_by(Candidate.job_apply)
    .all()
    )

    # Chuyển kết quả thành dictionary
    output = {job: count for job, count in results}
    return output

@app.get("/jobs")
def get_jobs(db: Session = Depends(get_db)):
    jobs = get_unique_job_titles(db)
    return {"jobs": jobs}

@app.post("/job_apply/delete")
def delete_candidates_by_job(job_apply: str= Form(None), db: Session = Depends(get_db)):
    candidates = db.query(Candidate).filter(Candidate.job_apply == job_apply).all()
    count = len(candidates)
    for candidate in candidates:
        db.delete(candidate)
    db.commit()

    qdrant.delete(
    collection_name="candidates",
    points_selector=models.Filter(
        must=[models.FieldCondition(key="job_apply", match=models.MatchValue(value=job_apply))]
    )
    )
    return {"deleted_count": count}

@app.get("/candidate/by_job/{job_apply}")
def get_candidates_by_job(job_apply: str, db: Session = Depends(get_db)):
    results = (
        db.query(
            Candidate.full_name,
            Candidate.email,
            Attachment.public_url
        )
        .join(Attachment, Candidate.id == Attachment.candidate_id)
        .filter(Candidate.job_apply == job_apply)
        .all()
    )

    return [
        {"name": r.full_name, "email": r.email, "public_url": r.public_url}
        for r in results
    ]
@app.post("/cv/upload")
async def upload_cv(file: UploadFile = File(...), job_apply: str = Form(None), db: Session = Depends(get_db)):
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

        if job_apply:
            info["job_apply"] = job_apply

        # if "education" in info:
        #     for edu in info["education"]:
        #         gpa = edu.get("gpa")
        #         print("📌 GPA:", gpa)   # log ra console
                
        # if "certifications" in info:
        #     print("📌 Certifications:", info["certifications"])
        
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
    ori_question: str
    question: str
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    links_only: bool = False   


@app.post("/query")
async def query_api(request: QueryRequest):
    try:
        question = request.question.strip()
        ori_question = request.ori_question.strip()
        state = {"question": question}
        result = enrich_final_answer(state)

        # insert_log(question=ori_question, route=result.get("route")) #hàm insert_log để lưu memory
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
    
@app.get("/suggestions")
def get_suggestions(job: str, db: Session = Depends(get_db)):
    # Gợi ý các trường học
    schools = (
        db.query(Educations.university)
        .join(Candidate, Educations.candidate_id == Candidate.id)
        .filter(Candidate.job_apply == job)
        .distinct()
        .all()
    )

    # Gợi ý các kỹ năng
    skills = (
        db.query(Skill.name)
        .join(candidate_skills, Skill.id == candidate_skills.c.skill_id)
        .join(Candidate, candidate_skills.c.candidate_id == Candidate.id)
        .filter(Candidate.job_apply == job)
        .distinct()
        .all()
    )

    # Gợi ý các ngôn ngữ (nếu cần)

    return {
        "job": job,
        "schools": [s[0] for s in schools if s[0]],
        "skills": [s[0] for s in skills if s[0]],
    }

class QueryFilterPayload(BaseModel):
    job_apply: Optional[str] = None
    school: Optional[str] = None
    gpa: Optional[float] = None
    english_cert_only: Optional[bool] = False
    skills: Optional[List[str]] = None
    exp_detail: Optional[str] = None
    project_detail: Optional[str] = None

@app.post("/filter_query")
def search_candidates(payload: QueryFilterPayload, db: Session = Depends(get_db)):
    job_apply = payload.job_apply
    school = payload.school
    gpa = payload.gpa
    english_cert_only = payload.english_cert_only or False
    skills = payload.skills or []
    exp_detail = payload.exp_detail or ""
    project_detail = payload.project_detail or ""

    # Tập kết quả theo từng phương thức
    sql_emails, exp_emails, proj_emails = set(), set(), set()
    sql_info, exp_info, proj_info = {}, {}, {}

    # 1️⃣ Tìm theo SQL filter
    has_sql_filter = any([school, gpa is not None, english_cert_only, skills])
    if has_sql_filter:
        sql_results = search_filter_sql(job_apply, school, gpa, english_cert_only, skills, db)
        print("SQL results:", sql_results)
        engine = db.get_bind()

        columns = list(sql_results[0].keys()) if sql_results else []
        rows = [tuple(c.values()) for c in sql_results]
        sql_results = enrich_with_resume_urls(
            engine=engine,
            columns=columns,
            rows=rows,
            base_url="http://localhost:8000",
            id_column="id"
        )

        for r in sql_results:
            email = r["email"]
            sql_emails.add(email)
            sql_info[email] = {
                "full_name": r["full_name"],
                "email": email,
                "resume_url": r.get("resume_url"),
            }

    # 2️⃣ Tìm theo exp_detail (semantic search kinh nghiệm)
    if exp_detail:
        state = {"question": exp_detail}
        flow = build_flow(deepseek, embedding, qdrant, QDRANT_COLLECTION, limit=10, search_threshold=0.3)
        answer = flow.invoke(state)
        print("DeepSeek answer:", answer)

        final_answer = answer.get("final_answer", {})
        columns = final_answer.get("columns", [])
        rows = final_answer.get("rows", [])

        for row in rows:
            item = dict(zip(columns, row))
            email = item.get("email")
            if email:
                exp_emails.add(email)
                exp_info[email] = {
                    "full_name": item.get("name", ""),
                    "email": email,
                    "resume_url": item.get("resume_url", "")
                }

    # 3️⃣ Tìm theo project_detail (semantic search project)
    if project_detail:
        embedded_project_detail = embedding.embed_query(project_detail)
        project_hits = qdrant.search(
            collection_name="candidates",
            query_vector=embedded_project_detail,
            limit=10,
            score_threshold=0.5,
            with_payload=True,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="type",
                        match=models.MatchValue(value="project")
                    )
                ]
            ),
        )

        for hit in project_hits:
            payload = hit.payload
            if payload and "email" in payload:
                email = payload["email"]
                proj_emails.add(email)
                proj_info[email] = {
                    "full_name": payload.get("candidate_name", ""),
                    "email": email,
                    "resume_url": payload.get("resume_url", "")
                }

    # 🧮 Lấy giao các tập email (chỉ giữa những cái có dữ liệu)
    sets = [s for s in [sql_emails, exp_emails, proj_emails] if s]
    if sets:
        intersection = set.intersection(*sets)
    else:
        intersection = set()  # không có bộ lọc nào được dùng

    print("📊 Intersection emails:", intersection)

    # 4️⃣ Gộp thông tin theo email giao nhau
    final_results = []
    for email in intersection:
        info = sql_info.get(email) or exp_info.get(email) or proj_info.get(email)
        if info:
            final_results.append(info)

    print("✅ Final intersection results:", final_results)
    return final_results


# app/api/main.py
@app.post("/__admin/ensure-indexes")
def ensure_indexes():
    from qdrant_client import models as qm
    created = []
    for field, schema in [
        ("type", qm.PayloadSchemaType.KEYWORD),
        ("candidate_name", qm.PayloadSchemaType.KEYWORD),
        ("email", qm.PayloadSchemaType.KEYWORD),
        ("exp_company", qm.PayloadSchemaType.KEYWORD),
        ("exp_job_title", qm.PayloadSchemaType.KEYWORD),
        ("skill", qm.PayloadSchemaType.KEYWORD),
    ]:
        try:
            qdrant.create_payload_index(QDRANT_COLLECTION, field, schema, wait=True)
            created.append(field)
        except Exception as e:
            if "already exists" not in str(e).lower():
                return {"ok": False, "failed": field, "error": str(e)}
    return {"ok": True, "created": created}



@app.get("/__debug/qdrant")
def dbg_qdrant():
    try:
        return qdrant.get_collections().dict()
    except Exception as e:
        return {"error": str(e)}
    


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

# giao diện Qdrant: http://localhost:6333/dashboard
# uvicorn app.api.main:app --reload --port 8000
