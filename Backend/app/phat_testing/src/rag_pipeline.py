from langchain_google_genai import ChatGoogleGenerativeAI
import os
from langchain.prompts import ChatPromptTemplate
from qdrant_client import QdrantClient
from langchain_community.embeddings import GPT4AllEmbeddings

import re

os.environ["GOOGLE_API_KEY"] = "AIzaSyBJ86qCzZw5qIVhhdb_VB28OaQz42Oj6GU"

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

router_prompt = ChatPromptTemplate.from_template("""
Bạn là một bộ phân loại. Với câu hỏi sau, hãy trả lời 'SQL' nếu liên quan đến 
dữ liệu có cấu trúc (tên, email, trường, GPA), hoặc 'VECTOR' nếu liên quan đến 
kĩ năng/kinh nghiệm. 
Câu hỏi: {question}
""")

def route_query(question: str):
    response = llm.invoke(router_prompt.format(question=question))
    return response.content.strip()

from sqlalchemy import create_engine, text

# Thay đổi username, password, db_name theo config của bạn
engine = create_engine("postgresql://postgres:phatdeptrai123@localhost:5432/candidates")

sql_prompt = ChatPromptTemplate.from_template("""
Bạn là một hệ thống Text2SQL. 
Database schema:
candidates_info(id, full_name, email, phone, job_title)

Câu hỏi: {question}
Trả về câu lệnh SQL hợp lệ. Không cần thêm ```sql ``` vào giữa câu query. Giá trị cột nên để trong dấu '' chứ
không phải "".
""")

def generate_sql(question: str):
    response = llm.invoke(sql_prompt.format(question=question))
    return response.content.strip()

def fix_sql_quotes(query: str) -> str:
    fixed_query = re.sub(r'"([^"]*)"', r"'\1'", query)
    return fixed_query

qdrant = QdrantClient(path="../qdrant_initial_db2")
COLLECTION_NAME = "candidates_vectors"
embedding = GPT4AllEmbeddings()

def search_vector(query: str, embedding_model):
    query_vector = embedding_model.embed_query(query) 
    hits = qdrant.search(collection_name="candidates_vectors", query_vector=query_vector, limit=3)
    return [(hit.id, hit.score, hit.payload) for hit in hits]

print(search_vector("ứng viên có kinh nghiệm React"))

# q = "Email của JR Sabado là gì?"
# sql_query = generate_sql(q)
# # cleaned_query = fix_sql_quotes(sql_query)
# print("Generated SQL:", sql_query)

# with engine.connect() as conn:
#     result = conn.execute(text(sql_query)).fetchall()
#     print("Result:", result)