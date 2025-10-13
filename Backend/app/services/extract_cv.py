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
from qdrant_client import QdrantClient, models as qm
from qdrant_client.http import models as rest
from qdrant_client.models import Distance, VectorParams, PointStruct
from qdrant_client.models import Filter, FieldCondition, MatchValue
# from qdrant_client.models import t, VectorParams, Distance
from langchain_deepseek import ChatDeepSeek
# from langchain_community.embeddings import GPT4AllEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.schema import HumanMessage
from langchain.schema import Document

from qdrant_client.http.models import PointStruct, SparseVector

from collections import defaultdict

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
"location": "...",
"education": [
    {{
    "degree": "...",
    "university": "...",
    "gpa": "...",
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
    "organization": "...",
    "score": "..."
    }}
],
"project": [
    {{
    "project_name": "...",
    "project_description": "..."
    }}
]
"languages": ["...", "..."]
}}

- Include ALL English language certifications (TOEIC, IELTS, TOEFL, etc.) in the "certifications" section.
- Always capture their score if available (e.g., "TOEIC 850", "IELTS 7.5", "TOEFL iBT 95").
- If the certificate is mentioned without a score, set "score" to null.

- Only include **real work experience** (e.g. internships, jobs at companies, freelance work) in the "experience" field.  
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
        except Exception as e:
            # Qdrant may return 400 if there's no payload index for this key (eg. 'email').
            # Fall back to a one-time payload scan (less efficient) to avoid failing the whole upload.
            msg = str(e)
            if "Index required" in msg or "Index required but not found" in msg or "index required" in msg.lower():
                try:
                    pts, _ = qdrant.scroll(collection_name=collection, limit=1000, with_payload=True)
                    for p in pts:
                        payload = getattr(p, 'payload', None) or (p.payload if hasattr(p, 'payload') else p.get('payload', {}))
                        if not payload:
                            continue
                        if payload.get('email') == email:
                            return True
                    return False
                except Exception:
                    # If even fallback fails, err on the side of allowing upload (avoid blocking users).
                    return False
            # Not the specific missing-index error -> re-raise
            raise
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



REQUIRED_INDEXES = [
    ("type", qm.PayloadSchemaType.KEYWORD),
    ("candidate_name", qm.PayloadSchemaType.KEYWORD),
    ("email", qm.PayloadSchemaType.KEYWORD),
    ("exp_company", qm.PayloadSchemaType.KEYWORD),
    ("exp_job_title", qm.PayloadSchemaType.KEYWORD),
    # (tùy chọn) nếu bạn lọc theo skill/value:
    ("skill", qm.PayloadSchemaType.KEYWORD),
]

def ensure_collection(client: QdrantClient, collection: str, embedding_dim=3072):
    # 1) Tạo collection nếu chưa có
    try:
        client.get_collection(collection)
    except Exception:
        client.recreate_collection(
            collection_name=collection,
            vectors_config=qm.VectorParams(size=embedding_dim, distance=qm.Distance.COSINE),
            optimizers_config=qm.OptimizersConfigDiff(memmap_threshold=20000),
            # ghi bền hơn một chút trên prod
            replication_factor=1, write_consistency_factor=1
        )

    # 2) Tạo index cho các trường cần lọc
    for field, schema in REQUIRED_INDEXES:
        try:
            client.create_payload_index(
                collection_name=collection,
                field_name=field,
                field_schema=schema,
                wait=True
            )
        except Exception as e:
            if "already exists" in str(e).lower():
                continue
            raise

def dedup_sparse(indices, values):
    agg = defaultdict(float)
    for i, v in zip(indices, values):
        agg[i] += v
    new_indices, new_values = zip(*agg.items())
    return list(new_indices), list(new_values)

def get_sparse_vector(text: str, vocab_size: int = 1000) -> SparseVector:
    tokens = text.lower().split()
    indices = [abs(hash(t)) % vocab_size for t in tokens]
    values = [1.0] * len(tokens)

    indices, values = dedup_sparse(indices, values)

    return SparseVector(indices=indices, values=values)

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

    # ensure collection exists
    ensure_collection(vector_db, collection_name)

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
    projects = info.get("project", [])

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
                "job_apply": info.get("job_apply"),
                "source_file": filename,
                "candidate_name": info.get("full_name"),
                "email": email_norm,
                "resume_url": resume_url, 
            },
        ))


    for i, exp in enumerate(experiences):
        job_title = exp.get("job_title", "")
        company = exp.get("company", "")
        description = exp.get("description", "")
        
        exp_position = f"Job Title: {job_title} | Company: {company}" if job_title and company else ""

        exp_description = f"Description: {description}" if description else ""

        vec_exp_pos = embedding_model.embed_query(exp_position)
        vec_exp_des = embedding_model.embed_query(exp_description)

        points.append(PointStruct(
                id=make_id(f"exp-{filename}-{job_title}-{company}-{i}-{uuid.uuid4().hex[:8]}"),
                vector=vec_exp_pos,
                payload={
                    "type": "exp_position",
                    "exp_company": company,
                    "exp_job_title": job_title,
                    "job_title": info.get("job_title"),
                    "job_apply": info.get("job_apply"),
                    "source_file": filename,                    
                    "candidate_name": info.get("full_name"),
                    "email": email_norm,
                    "resume_url": resume_url,
                },
        ))        
        points.append(PointStruct(
                id=make_id(f"exp-{filename}-{exp_description}-{i}-{uuid.uuid4().hex[:8]}"),
                vector=vec_exp_des,
                payload={
                    "type": "exp_description",
                    "exp_company": company,
                    "exp_job_title": job_title,
                    "exp_description": exp_description,
                    "job_title": info.get("job_title"),
                    "job_apply": info.get("job_apply"),
                    "source_file": filename,                    
                    "candidate_name": info.get("full_name"),
                    "email": email_norm,
                    "resume_url": resume_url,
                },
        ))

    for i, proj in enumerate(projects):
        name = proj.get("project_name", "")
        description = proj.get("project_description", "")
        
        project_text = f"Project name: {name} \nProject description: {description}" if name and description else ""

        project_emb = embedding_model.embed_query(project_text)
        points.append(PointStruct(
                id=make_id(f"proj-{filename}-{name}-{description}-{i}-{uuid.uuid4().hex[:8]}"),
                vector=project_emb,
                payload={
                    "type": "project",
                    "project_name": name,
                    "project_description": description,
                    "job_apply": info.get("job_apply"),
                    "source_file": filename,                    
                    "candidate_name": info.get("full_name"),
                    "email": email_norm,
                    "resume_url": resume_url,
                },
        ))        

    if points:
        vector_db.upsert(collection_name=collection_name, points=points)

    return info

def test_cv_rag(
    file_path: str,
    pre_text: str | None = None,
    pre_info: dict | None = None,
) -> dict:
    filename = os.path.basename(file_path)
    print(f"Processing {filename}...")

    # ensure collection exists

    # dùng text có sẵn nếu được truyền, nếu không thì mới đọc PDF
    text = pre_text if pre_text is not None else extract_text_from_pdf(file_path)
    if not text:
        print(f"No text extracted from {filename}, skipping.")
        return {}

    # dùng info có sẵn nếu được truyền, nếu không thì mới gọi LLM
    info = pre_info if pre_info is not None else (extract_info(text) or {})
    info["source_file"] = filename

    # Chuẩn hoá + duplicate email
    email_norm = normalize_email(info.get("email"))


    skills = _dedup_skills(info.get("skills"))
    experiences = _dedup_experiences(info.get("experience"))
    projects = info.get("project", [])

    for i, proj in enumerate(projects):
        name = proj.get("project_name", "")
        description = proj.get("project_description", "")
        
        project_text = f"Project name: {name} \nProject description: {description}" if name and description else ""

        print(f"Project text: {project_text}")

if __name__ == "__main__":
    # honor QDRANT_API_KEY from config if present
    # from config.config import QDRANT_URL, QDRANT_API_KEY
    # qdrant = QdrantClient(url=QDRANT_URL or "http://localhost:6333", api_key=QDRANT_API_KEY, check_compatibility=False)
    # embedding = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-exp-03-07", api_key=GOOGLE_API_KEY)

    file_path = 'CV/BA/DinhNguyetQuynh_InternQAQC.pdf'
    text = extract_text_from_pdf(file_path)
    info = extract_info(text) or {}
    # print(info["project"])
    # resume_url = upload_pdf_and_get_url_gcs(file_path)
    # Gọi thử
    result = test_cv_rag(
        file_path,
        pre_text=text,
        pre_info=info,
    )
    # print(result)

# python extract_cv.py