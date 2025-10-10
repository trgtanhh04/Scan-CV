import os
from translate import Translator
import re
from difflib import get_close_matches
from langchain_deepseek import ChatDeepSeek

from sqlalchemy import create_engine, Column, Integer, Text, String, TIMESTAMP, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import DEEPSEEK_API_KEY, LOGS_DATABASE_URL


deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)


from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import requests

from googleapiclient.discovery import build
from google.auth.credentials import AnonymousCredentials
from googleapiclient.http import MediaIoBaseDownload
import streamlit as st
import io
    

MIME_TYPE_FOLDER = "application/vnd.google-apps.folder"


def extract_folder_id(drive_url: str) -> str:
    """Trích xuất folder_id từ link Google Drive public"""
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", drive_url)
    if match:
        return match.group(1)
    raise ValueError("❌ Không tìm thấy folder ID trong link Drive")

def get_drive_service(API_KEY):
    """Tạo service kết nối Google Drive API bằng API key"""
    return build("drive", "v3", developerKey=API_KEY, credentials=AnonymousCredentials())

def list_files_in_folder(service, folder_id: str):
    """Liệt kê file/folder trong thư mục public"""
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get("files", [])




# def list_files_in_folder(folder_id):
#     url = "https://www.googleapis.com/drive/v3/files"
#     params = {
#         "q": f"'{folder_id}' in parents and trashed=false",
#         "fields": "files(id, name, mimeType)",
#         "key": API_KEY
#     }
#     res = requests.get(url, params=params)
#     if res.status_code != 200:
#         raise Exception(res.json())
#     return res.json().get("files", [])

# SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# import os
# import json

# CONFIG_FILE = "drive_config.json"

# def save_drive_link(link):
#     with open(CONFIG_FILE, "w") as f:
#         json.dump({"drive_link": link}, f)

# def load_drive_link():
#     if os.path.exists(CONFIG_FILE):
#         with open(CONFIG_FILE, "r") as f:
#             data = json.load(f)
#             return data.get("drive_link")
#     return None

# #============= MAIN =============



# def extract_folder_id(drive_link: str) -> str:
#     match = re.search(r"/folders/([a-zA-Z0-9_-]+)", drive_link)
#     if match:
#         return match.group(1)
#     else:
#         raise ValueError("Không tìm thấy folder_id trong link.")


# def list_files_in_folder(service, folder_id: str):
#     response = service.files().list(
#         q=f"'{folder_id}' in parents and trashed=false",
#         fields="files(id, name, mimeType)",
#     ).execute()
#     return response.get("files", [])


#============= HELPERS =============

# Convert job description to English if needed
def translate_to_english(query):
    translator = Translator(to_lang="en", from_lang="vi")
    return translator.translate(query)

# Fine-tune job description to a precise search query
def convert_job_to_question(job_description):
    search_query_prompt = f"""
        You are an assistant that converts job descriptions into precise search queries for finding candidates.
        - For simple queries like "Find candidates that know Python", keep them as is.
        - For complex job descriptions, convert them into a clear search query highlighting skills, experience, and job-specific keywords.
        - Output the result in English, question only, no explanations.
        - Expand abbreviations if they appear:
            * PM -> Project Manager (not Product Manager unless context clearly says otherwise)
            * DE -> Data Engineer
            * SE -> Software Engineer
            * BA -> Business Analyst
            * QA -> Quality Assurance Engineer
            * FE -> Frontend Engineer
            * BE -> Backend Engineer
            * AI -> Artificial Intelligence
            - Always output **only one sentence**, starting with "Find candidates ...".

        Examples:
        Input: "Find candidates that know Python."
        Output: "Find candidates that know Python."

        Input: "Find candidates that know Java."
        Output: "Find candidates that know Java."

        Input: "5+ years as a Fullstack Engineer, AI Specialist, or similar, with a strong track record of deploying scalable, AI-integrated applications."
        Output: "Find candidates with 5+ years of fullstack engineer or AI specialist experience and a proven track record of deploying scalable, AI-integrated applications."

        Input: "Find candidates with PM experience"
        Output: "Find candidates with experience as a Project Manager."

        Input: "Find candidates with DE experience"
        Output: "Find candidates with experience as a Data Engineer."
    """
    response = deepseek.invoke(search_query_prompt + f"\nInput: '{job_description}'\nOutput:")
    return response.content.strip()

# def convert_job_to_question(job_description):
#     search_query_prompt = f"""
#         You are an assistant that converts job descriptions into precise English search queries for finding candidates.

#         Rules:
#         - If the input is already a simple English query like "Find candidates that know Python", keep it as is.
#         - If the input is in another language (e.g., Vietnamese), always translate and convert it into English.
#         - Expand abbreviations if they appear:
#         * PM → Project Manager (not Product Manager unless context clearly says otherwise)
#         * DE → Data Engineer
#         * SE → Software Engineer
#         * BA → Business Analyst
#         * QA → Quality Assurance Engineer
#         * FE → Frontend Engineer
#         * BE → Backend Engineer
#         * AI → Artificial Intelligence
#         - Always output **only one sentence**, starting with "Find candidates ...".
#         - Do not add explanations, notes, or code fences.

#         Examples:

#         Input: "Find candidates that know Python."
#         Output: "Find candidates that know Python."

#         Input: "5+ years as a Fullstack Engineer, AI Specialist, or similar, with a strong track record of deploying scalable, AI-integrated applications."
#         Output: "Find candidates with 5+ years of fullstack engineer or AI specialist experience and a proven track record of deploying scalable, AI-integrated applications."

#         Input: "Tìm ứng viên có kinh nghiệm 5 năm trong lĩnh vực data engineer, biết python và java, và có GPA xuất sắc."
#         Output: "Find candidates with 5 years of experience in data engineer, knowledge of Python and Java, and an excellent GPA."

#         Input: "Tìm ứng viên có kinh nghiệm làm PM"
#         Output: "Find candidates with experience as a Project Manager."

#         ---

#         Input: '{job_description}'
#         Output:
#     """

# Decision to fine-tune or not based on clarity/complexity of job description
def needs_finetune(job_description: str) -> bool:
    """
    Quyết định có cần fine-tune hay không dựa trên độ rõ ràng / độ phức tạp của job description.
    """
    job_description_lower = job_description.lower()

    simple_keywords = [
        "python", "java", "javascript", "typescript", "c++", "c#", "ruby", "go", "php",
        "react", "angular", "vue", "node.js", "django", "flask", "spring", "express",
        "sql", "nosql", "excel", "python scripting", "html", "css", "rest api", 'software',
        "developer", "engineer", "data", "database", "cloud", "aws", "azure", "gcp",
    ]
    simple_count = sum(kw in job_description_lower for kw in simple_keywords)
    
    complex_keywords = [
        "deploy", "scalable", "ai", "artificial intelligence",
        "machine learning", "deep learning", "fullstack", "devops", "cloud",
        "kubernetes", "lead", "architect", "microservices", "ci/cd", "production", "production-ready", "distributed systems",
        "team management", "project management"
    ]

    is_complex = len(job_description.split()) > 12 or any(x in job_description_lower for x in complex_keywords)

    if simple_count <= 2 and not is_complex:
        return False

    return True

# Validate if query is suitable for candidate search
def validate_candidate_query(query: str, cutoff: float = 0.8) -> bool:
    """
    Kiểm tra xem câu truy vấn có hợp lệ để tìm ứng viên hay không.
    - Loại bỏ spam / câu vô nghĩa
    - Check từ khóa hợp lệ (có fuzzy matching để xử lý typo)
    - Cho qua câu chứa các động từ tìm kiếm phổ biến ("find", "search", "know")
    """
    query_lower = query.lower()

    valid_keywords = [
        "skills", "skill", "experience", "cv", "resume", "candidate", "email",
        "database", "knowledge", "years of experience", "project", "role", "position",
        "tech", "technology", "programming", "python", "java", "javascript",
        "sql", "nosql", "aws", "cloud", "deployment", "machine learning", "ai", "fullstack",
        "data engineer", "software", "development", "teamwork", "communication", "leadership",
        'chatbot', 'llm', 'gpt', 'deepseek', 'openai', 'langchain', 'university', 'degree', 'education', 'certification',
        'location', 'language', 'vietnamese', 'english', 'japanese', 'role', 'company', 'work', 'worked', 'working',
    ]

    invalid_patterns = [
        r"^[\W_]+$",                 
        r"^\s*$",                   
        r"\b(?:haha|hehe|hihi|hahaha|hoho|lmao|lol)\b", 
        r"\b(?:beauty|travel|vacation|holiday|shopping|love|friendship|handsome|happy|xinh đẹp)\b" 
    ]

    if any(re.search(pattern, query_lower) for pattern in invalid_patterns):
        return False

    words = re.findall(r'\w+', query_lower)
    for kw in valid_keywords:
        if kw.lower() in words:
            return True
        if get_close_matches(kw.lower(), words, cutoff=cutoff):
            return True

    if any(re.search(pattern, query_lower) for pattern in ["find", "search", "know", "list"]):
        return True

    return False

#Gợi ý câu truy vấn từ lịch sử tìm kiếm

# engine_logs = create_engine(LOGS_DATABASE_URL)

# SessionLocalLogs = sessionmaker(autocommit=False, autoflush=False, bind=engine_logs)
# Base = declarative_base()

# class QuestionLog(Base):
#     __tablename__ = "question_logs"

#     id = Column(Integer, primary_key=True, index=True)
#     question = Column(Text, nullable=False)
#     route = Column(String, nullable=True)
#     created_at = Column(TIMESTAMP, server_default=func.now())

# def insert_log(question: str):
#     """Lưu log vào database logs"""
#     db = SessionLocalLogs()
#     try:
#         log_entry = QuestionLog(
#             question=question,
#         )
#         db.add(log_entry)
#         db.commit()
#         db.refresh(log_entry)
#         return log_entry
#     except Exception as e:
#         db.rollback()
#         raise e
#     finally:
#         db.close()

# def get_top_questions(limit: int = 3):
#     """Trả ra N câu hỏi được hỏi nhiều nhất"""
#     db = SessionLocalLogs()
#     try:
#         results = (
#             db.query(
#                 QuestionLog.question,
#                 func.count(QuestionLog.id).label("frequency")
#             )
#             .group_by(QuestionLog.question)
#             .order_by(func.count(QuestionLog.id).desc())
#             .limit(limit)
#             .all()
#         )
#         return [str(r[0]) for r in results if r[0] is not None]
#     finally:
#         db.close()