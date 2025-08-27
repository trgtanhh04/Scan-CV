import pandas as pd
import fitz
import os
import json
import re
import uuid
from dotenv import load_dotenv
from langchain_qdrant import Qdrant
import hashlib
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from qdrant_client.models import Filter, FieldCondition, MatchValue
# from qdrant_client.models import t, VectorParams, Distance
from langchain_deepseek import ChatDeepSeek
# from langchain_community.embeddings import GPT4AllEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.schema import HumanMessage
from langchain.schema import Document

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

def process_cv(
    file_path: str,
    vector_db,
    embedding_model,
    collection_name: str,
) -> dict:
    """
    Xử lý 1 file CV PDF, trích xuất thông tin ứng viên và lưu vào Qdrant.
    Trả về dict thông tin ứng viên.
    """
    filename = os.path.basename(file_path)
    print(f"Processing {filename}...")

    # Trích xuất text từ PDF
    text = extract_text_from_pdf(file_path)
    if not text:
        print(f"⚠️ No text extracted from {filename}, skipping.")
        return {}

    # Trích xuất thông tin từ LLM
    info = extract_info(text) or {}
    info["source_file"] = filename

    # Chuẩn hóa skills
    skills = info.get("skills", [])
    if isinstance(skills, str):
        skills = [skills]
    elif skills is None:
        skills = []

    # Chuẩn hóa experiences
    experiences = info.get("experience") or []

    # Gom tất cả point vào list
    points = []

    # Xử lý skills
    for skill in skills:
        vector = embedding_model.embed_query(skill)
        points.append(
            PointStruct(
                id=make_id(f"skill-{filename}-{skill}-{uuid.uuid4().hex[:8]}"),
                vector=vector,
                payload={
                    "type": "skill",
                    "skill": skill,
                    "job_title": info.get("job_title"),
                    "source_file": filename,
                    "candidate_name": info.get("full_name"),
                },
            )
        )

    # Xử lý experiences
    for i, exp in enumerate(experiences):
        exp_text = f"{exp.get('job_title', '')} at {exp.get('company', '')} ({exp.get('start_date', '')} - {exp.get('end_date', '')}) {exp.get('description', '')}"
        vector = embedding_model.embed_query(exp_text)
        points.append(
            PointStruct(
                id=make_id(f"exp-{filename}-{exp.get('company', 'unknown')}-{i}-{uuid.uuid4().hex[:8]}"),
                vector=vector,
                payload={
                    "type": "experience",
                    "experience": exp_text,
                    "experience_detail": exp,  # lưu cả dict gốc
                    "job_title": info.get("job_title"),
                    "source_file": filename,
                    "candidate_name": info.get("full_name"),
                },
            )
        )

    # Upsert vào Qdrant
    if points:
        vector_db.upsert(
            collection_name=collection_name,
            points=points
        )

    return info

