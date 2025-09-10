import sys
import pandas as pd
import fitz
import os
import json
import re
import uuid
from dotenv import load_dotenv
from langchain_qdrant import Qdrant
import hashlib
from typing import List, Tuple
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from qdrant_client.models import Distance, VectorParams, PointStruct
from qdrant_client.models import Filter, FieldCondition, MatchValue
# from qdrant_client.models import t, VectorParams, Distance
from langchain_deepseek import ChatDeepSeek
# from langchain_community.embeddings import GPT4AllEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.schema import HumanMessage
from langchain.schema import Document

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from services.get_cv_url_from_gcs import upload_pdf_and_get_url_gcs


load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
llm = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)


def extract_text_from_pdf(file_path: str) -> str:
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text.strip()

prompt_template = """
Extract the following candidate information fields from the CV content (as plain text) below in the exact JSON format:
{{
"full_name": "...",
"email": "...",
"phone": "...",
"job_title": "...",
"education": [
    {{
    "degree": "...",
    "university": "...",
    "start_year": ...,
    "end_year": ...
    }}
],
"experience": [
    {{
    "job_title": "...",
    "company": "...",
    "start_date": "...",
    "end_date": "...",
    "description": "..."
    }}
],

"skills": ["...", "..."],
"certifications": [
    {{
    "certificate_name": "...",
    "organization": "..."
    }}
],
"languages": ["...", "..."]
}}

Only include **real work experience** (e.g. internships, jobs at companies, freelance work) in the "experience" field.  
**Do not include personal, academic, or side projects** in the experience section.

Only return the JSON content. Do not include any explanation.  
If any field cannot be found, set it to null or empty array.

CV content:
{text}
"""

def extract_info(text: str) -> dict:
    prompt = prompt_template.format(text=text)
    messages = [HumanMessage(content=prompt)]
    response = llm.invoke(messages)
    raw_content = response.content

    
    cleaned_data = re.sub(r"^```json\s*|\s*```$", "", raw_content.strip(), flags=re.MULTILINE)
    # candidate_info = json.loads(response.content)
    
    try:
        candidate_info = json.loads(cleaned_data)

        # Lọc experience: bỏ các mục có company = None hoặc ""
        if "experience" in candidate_info and isinstance(candidate_info["experience"], list):
            filtered_exp = []
            for exp in candidate_info["experience"]:
                company = exp.get("company")
                if company not in [None, ""]:
                    filtered_exp.append(exp)
            candidate_info["experience"] = filtered_exp

    except Exception as e:
        print(f"Error parsing JSON: {e}\nLLM output: {cleaned_data}")
        candidate_info = {}
    return candidate_info


def make_id(text: str) -> int:
    # Sinh int id từ string bằng hash
    return int(hashlib.md5(text.encode()).hexdigest(), 16) % (10**12)

# Chuẩn hóa email + Check duplicate
def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    e = email.strip().lower()
    return e if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e) else None

# ---------------- Dedup helpers ----------------
def _clean_skill(s: str) -> str:
    return s.strip()

def _dedup_skills(skills_in) -> List[str]:
    if not skills_in:
        return []
    # chấp nhận cả string hoặc list
    if isinstance(skills_in, str):
        skills_in = [skills_in]
    cleaned = []
    seen = set()
    for s in skills_in:
        if not isinstance(s, str):
            continue
        cs = _clean_skill(s)
        if not cs:  # rỗng
            continue
        key = cs.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(cs)
    return cleaned

def exists_email(qdrant, collection: str, email: str) -> bool:
    flt = Filter(must=[FieldCondition(key="email", match=MatchValue(value=email))])
    for param in ("filter", "query_filter", "scroll_filter"):
        try:
            pts, _ = qdrant.scroll(
                collection_name=collection,
                limit=1,
                with_payload=False,
                **{param: flt}
            )
            return len(pts) > 0
        except AssertionError:
            continue
    return False

def _exp_signature(exp: dict) -> Tuple[str, str, str, str, str]:
    # tạo khóa nhận diện để lọc trùng experience
    jt = (exp.get("job_title") or "").strip().lower()
    cp = (exp.get("company") or "").strip().lower()
    sd = (exp.get("start_date") or "").strip().lower()
    ed = (exp.get("end_date") or "").strip().lower()
    ds = (exp.get("description") or "").strip().lower()
    return (cp, jt, sd, ed, ds)

def _dedup_experiences(exps_in) -> List[dict]:
    if not exps_in:
        return []
    uniq = []
    seen = set()
    for exp in exps_in:
        if not isinstance(exp, dict):
            continue
        sig = _exp_signature(exp)
        if sig not in seen:
            seen.add(sig)
            uniq.append(exp)
    return uniq


def ensure_collection(qdrant: QdrantClient, collection_name: str, embedding_model) -> None:
    try:
        if not qdrant.collection_exists(collection_name):  
            dim = len(embedding_model.embed_query("dimension_probe"))  
            qdrant.create_collection(                       
                collection_name=collection_name,
                vectors_config=rest.VectorParams(size=dim, distance=rest.Distance.COSINE),
                on_disk_payload=True,
            )
    except Exception as e:
        print(f"[WARN] ensure_collection failed: {e}")


def process_cv_rag(
    file_path: str,
    vector_db,
    embedding_model,
    collection_name: str,
    *,
    pre_text: str | None = None,
    pre_info: dict | None = None,
    resume_url: str | None = None, 
) -> dict:
    filename = os.path.basename(file_path)
    print(f"Processing {filename}...")

    # dùng text có sẵn nếu được truyền, nếu không thì mới đọc PDF
    text = pre_text if pre_text is not None else extract_text_from_pdf(file_path)
    if not text:
        print(f"No text extracted from {filename}, skipping.")
        return {}

    # dùng info có sẵn nếu được truyền, nếu không thì mới gọi LLM
    info = pre_info if pre_info is not None else (extract_info(text) or {})
    info["source_file"] = filename

    if resume_url:           
        info["resume_url"] = resume_url

    # Chuẩn hoá + duplicate email
    email_norm = normalize_email(info.get("email"))
    if email_norm and exists_email(vector_db, collection_name, email_norm):
        print(f"Duplicate email {email_norm}, skip {filename}")
        return {"skipped": "duplicate_email", "email": email_norm}

    skills = _dedup_skills(info.get("skills"))
    experiences = _dedup_experiences(info.get("experience"))

    points = []
    for skill in skills:
        vec = embedding_model.embed_query(skill)
        points.append(PointStruct(
            id=make_id(f"skill-{filename}-{skill}-{uuid.uuid4().hex[:8]}"),
            vector=vec,
            payload={
                "type": "skill", 
                "skill": skill,
                "job_title": info.get("job_title"),
                "source_file": filename,
                "candidate_name": info.get("full_name"),
                "email": email_norm,
                "resume_url": resume_url, 
            },
        ))

    for i, exp in enumerate(experiences):
        exp_text = f"{exp.get('job_title','')} at {exp.get('company','')} ({exp.get('start_date','')} - {exp.get('end_date','')}) {exp.get('description','')}"
        vec = embedding_model.embed_query(exp_text)
        points.append(PointStruct(
            id=make_id(f"exp-{filename}-{exp.get('company','unknown')}-{i}-{uuid.uuid4().hex[:8]}"),
            vector=vec,
            payload={
                "type": "experience",
                "experience": exp_text,
                "experience_detail": exp,
                "job_title": info.get("job_title"),
                "source_file": filename,
                "candidate_name": info.get("full_name"),
                "email": email_norm,
                "resume_url": resume_url, 
            },
        ))


    if points:
        vector_db.upsert(collection_name=collection_name, points=points)

    return info

if __name__ == "__main__":
    qdrant = QdrantClient(url="http://localhost:6333", check_compatibility=False)
    embedding = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-exp-03-07", api_key=GOOGLE_API_KEY)

    file_path = '../../raw/cvs/02.pdf'
    text = extract_text_from_pdf(file_path)
    info = extract_info(text) or {}
    resume_url = upload_pdf_and_get_url_gcs(file_path)
    # Gọi thử
    result = process_cv_rag(
        file_path,
        qdrant,
        embedding,
        "candidates",
        pre_text=text,
        pre_info=info,
        resume_url=resume_url
    )
    print(result)

# python extract_cv.py