from langchain.prompts import ChatPromptTemplate

import re


def fix_sql_quotes(query: str) -> str:
    fixed_query = re.sub(r'"([^"]*)"', r"'\1'", query)
    return fixed_query

def route_query(question: str, llm):
    router_prompt = ChatPromptTemplate.from_template("""
        Bạn là một bộ phân loại. Với câu hỏi sau, hãy trả lời 'SQL' nếu liên quan đến 
        dữ liệu có cấu trúc (tên, email, trường, GPA), hoặc 'VECTOR' nếu liên quan đến 
        kĩ năng/kinh nghiệm. 
        Câu hỏi: {question}
        """)
    response = llm.invoke(router_prompt.format(question=question))
    return response.content.strip()



def generate_sql(question: str, llm):
    sql_prompt = ChatPromptTemplate.from_template("""
        Bạn là một hệ thống Text2SQL. 
        Database schema:
        candidates_info(id, full_name, email, phone, job_title)

        Câu hỏi: {question}
        Trả về câu lệnh SQL hợp lệ. Không cần thêm ```sql ``` vào giữa câu query. Giá trị cột nên để trong dấu '' chứ
        không phải "".
        """)
    response = llm.invoke(sql_prompt.format(question=question))
    return response.content.strip()


def search_vector(query: str, embedding_model, qdrant_db, collection, limit):
    query_vector = embedding_model.embed_query(query) 
    hits = qdrant_db.search(collection_name=collection, query_vector=query_vector, limit=limit)
    return [(hit.id, hit.score, hit.payload) for hit in hits]


