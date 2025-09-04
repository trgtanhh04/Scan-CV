from langchain.prompts import ChatPromptTemplate
from qdrant_client.models import Filter, FieldCondition, MatchValue
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, text
import json
import re
from typing import Tuple, Literal

# import os  

# # from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY
# # from config.storage import MEDIA_ROOT, build_public_url 
# from langchain_deepseek import ChatDeepSeek
# from qdrant_client import QdrantClient
# from langchain_google_genai import  GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI


# DEEPSEEK_API_KEY='sk-700f6bb0b3b341bba6f9f7c4db53d028'


# deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

# GOOGLE_API_KEY = 'AIzaSyBJ86qCzZw5qIVhhdb_VB28OaQz42Oj6GU'
# embedding = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-exp-03-07", google_api_key=GOOGLE_API_KEY)
# # engine = create_engine("postgresql://postgres:phatdeptrai123@localhost:5432/candidates")

# db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../qdrant_gemini_db"))
# qdrant = QdrantClient(path=db_path)
# COLLECTION_NAME = "candidates"

def fix_sql_quotes(query: str) -> str:
    fixed_query = re.sub(r'"([^"]*)"', r"'\1'", query)
    return fixed_query

# def pre_retrieval_judge(question:str, llm):
#     pre_retrieval_prompt = ChatPromptTemplate.from_template("""
#     You are a classification system. From each admin's text:
#     Answer 'Casual' if it is a casual chat or greeting.
#     Answer 'HR' if the admin wants to find information about the candidates applying for the company.
#     Admin's text: {question}
#     """)
#     response = llm.invoke(pre_retrieval_prompt.format(question=question))
#     return response.content.strip()

# def post_retrieval_judge(question:str, information: str, llm):
#     post_retrieval_prompt = ChatPromptTemplate.from_template("""
#     You are a judgement system. For each user question and the information returned from the database:
#     Answer 'Satisfactory' if the information returned from the database is relevant and answers the question.
#     Answer 'Unsatisfactory' if there is no information returned.
#     Question: {question}
#     Information returned from vector database: {information}
#     """)
#     response = llm.invoke(post_retrieval_prompt.format(question=question, information=information))
#     return response.content.strip()

# def rewrite_query(question: str, llm):
#     prompt = ChatPromptTemplate.from_template("""
#     The user asked a question but the database returned no satisfactory result.
#     Please rewrite the question in a clearer and alternative way, keeping the intent the same.
#     Original question: {question}
#     """)
#     response = llm.invoke(prompt.format(question=question))
#     return response.content.strip()


from unidecode import unidecode

RAG_SOFT_SKILL_PATTERNS = [
    r"work\s+well\s+with\s+others",
    r"team\s*player",
    r"teamwork",
    r"lam\s+viec\s+nhom",
]

def _norm(q: str) -> str:
    return unidecode(q or "").lower().strip()

def _is_sql_hard(qn: str) -> bool:
    """Các câu nâng cao -> SQL: số năm, so sánh, đếm, top, khoảng thời gian, etc."""
    pats = [
        r"\b\d+\s*(years?|nam)\b",                # 3 years / 3 năm
        r"\b(>=|>|<=|<|more than|over|at least|toi thieu|tro len)\b",
        r"\b(count|so luong|bao nhieu|how many)\b",
        r"\b(top|max|min|average|avg|sum)\b",
        r"\bbetween\b|\bfrom\s+\d{4}\s+to\s+\d{4}\b",
        r"\b(in|within)\s+\d+\s*(years?|nam)\b",
        r"\bexperience\s*(?:of|>=|>|at least)\s*\d+\s*(years?)\b",
    ]
    return any(re.search(p, qn) for p in pats)

def _is_rag_simple(qn: str) -> bool:
    """Những câu cơ bản cho RAG (VECTOR)."""
    # 1) Find all skills of candidate <name>
    if re.search(r"\b(find|list|liet\s*ke|tim)\b.*\b(all\s+)?skills?\b.*\b(of|cua)\b", qn):
        return True
    # 2) Find all experience of candidate <name>
    if re.search(r"\b(find|list|liet\s*ke|tim)\b.*\b(all\s+)?experiences?\b.*\b(of|cua)\b", qn):
        return True
    # 3) Find candidates that know <skill> (Python, Java, …)
    if re.search(r"\b(find|tim)\b.*\bcandidates?\b.*\b(know|ky\s*nang|skill|thanh\s*thao)\b", qn):
        return True
    # 4) Find candidates that know Java (trường hợp riêng cũng đã cover bởi (3), giữ cho rõ ràng)
    if re.search(r"\b(find|tim)\b.*\bcandidates?\b.*\bknow\b.*\bjava\b", qn):
        return True
    # 5) Soft skill "work well with others" / teamwork
    if any(re.search(p, qn) for p in RAG_SOFT_SKILL_PATTERNS):
        return True
    # 6) Have experience in Software (keyword trong experience)
    if re.search(r"\bhave\s+experience\s+in\s+software\b", qn) or re.search(r"kinh\s*nghiem\s+.*software", qn):
        return True
    # 7) Kết hợp: biết Python AND có experience in Software
    if re.search(r"know\s+python.*have\s+experience\s+in\s+software", qn) or \
       re.search(r"ky\s*nang\s+python.*kinh\s*nghiem\s+.*software", qn):
        return True

    return False

def route_query(question: str, llm=None) -> str:
    """
    Quy tắc định tuyến:
    - Nếu là câu RAG cơ bản -> 'VECTOR'
    - Nếu là câu SQL khó (năm kinh nghiệm, so sánh, đếm, top, …) -> 'SQL'
    - Mặc định -> 'SQL' (Text2SQL mạnh hơn ở câu phức tạp/không rõ)
    """
    qn = _norm(question)

    # Hard/advanced → SQL
    if _is_sql_hard(qn):
        return "SQL"

    # Simple RAG intents → VECTOR
    if _is_rag_simple(qn):
        return "VECTOR"

    return "SQL"


# def route_query(question: str, llm):
#     router_prompt = ChatPromptTemplate.from_template("""
#         You are a classification system. For each user question. 
#         Answer 'SQL' if it is related to structured data (full_name, email, phone, job_title, certifications, languages, degree, ) 
#         that is stored in a Postgresql database.
#         Answer 'VECTOR' if the user question is related to skill and experience.
#         Question: {question}
#         """)
#     response = llm.invoke(router_prompt.format(question=question))
#     print(response.content.strip())
#     return response.content.strip()


def generate_sql(question: str, llm):
    sql_prompt = ChatPromptTemplate.from_template("""
        You are a TEXT2SQL system. Your job is to translate user question into a SQL query. 
        This is your database schema:
        candidates_info(id, full_name, email, phone, job_title)

        Question: {question}
        Return a valid SQL query. You don't have to add ```sql ``` in between the query. 
        The value should be put in '', not "".
        """)
    response = llm.invoke(sql_prompt.format(question=question))
    return response.content.strip()


def generate_vector_query(question: str, llm, collection_name, limit):
    vector_prompt = ChatPromptTemplate.from_template("""
        You are a TEXT2VECTORQUERY system. 
        Translate user questions into a valid Qdrant query in JSON format. 
        Use one of two actions: "search" or "scroll".

        Rules:
        - If the question asks for attributes of a specific candidate (skills or experiences),
          use "scroll" with a filter on candidate_name and type.
        - If the question asks to find candidates by skill OR experience, 
          use "search" with query_text and type filter (only one type per query).
        - If the question asks to combine skills AND experiences 
          (e.g., "candidates with Python skill and worked at Google"),
          return an array of multiple queries, one for skills and one for experiences.
        - Never mix type=skill and type=experience in the same query_filter.
        - Always return raw JSON only, no explanation.
        - If you're using scroll, the filter argument is "scroll_filter".
        - If you're using search, the filter argument is "query_filter".
                                                                                                      

        collection_name: {collection_name}
        limit: {limit}

        Question: {question}
        Output format: JSON object OR array of JSON objects
    """)
    response = llm.invoke(vector_prompt.format(question=question, collection_name=collection_name, limit=limit))
    response = response.content.strip()
    cleaned = re.sub(r"^```json\s*|\s*```$", "", response.strip())
    return cleaned.strip()

def build_filter(filter_json: dict):
    """
    Convert filter JSON (must, should, must_not) into Qdrant Filter object
    """
    if not filter_json:
        return None

    must_conditions, should_conditions, must_not_conditions = [], [], []

    for cond in filter_json.get("must", []):
        if "key" in cond and "match" in cond:
            must_conditions.append(
                FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
            )
    for cond in filter_json.get("should", []):
        if "key" in cond and "match" in cond:
            should_conditions.append(
                FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
            )
    for cond in filter_json.get("must_not", []):
        if "key" in cond and "match" in cond:
            must_not_conditions.append(
                FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
            )

    return Filter(
        must=must_conditions or None,
        should=should_conditions or None,
        must_not=must_not_conditions or None
    )


def execute_vector_query(plan, client: QdrantClient, embedding_model, limit=None, search_threshold=0.75):
    if isinstance(plan, list):  # nhiều query cần chạy rồi join
        results_per_query = []
        for subplan in plan:
            results = execute_vector_query(subplan, client, embedding_model, 30, search_threshold)
            results_per_query.append(results)
        
        # join theo candidate_name (chỉ giữ những người có mặt ở tất cả queries)
        sets = [set([r["payload"]["candidate_name"] for r in res if "payload" in r]) for res in results_per_query]
        common_candidates = set.intersection(*sets)
        
        # gom full payload theo candidate
        final = []
        for res in results_per_query:
            for r in res:
                if r["payload"]["candidate_name"] in common_candidates:
                    final.append(r)
        return final
    
    # -------- trường hợp chỉ 1 query như cũ ----------
    action = plan["action"]
    collection_name = plan["collection_name"]
    limit = limit or plan.get("limit", 10)
    scroll_limit = 30
    if action == "scroll":
        qdrant_filter = build_filter(plan.get("scroll_filter", {}))
        points, _ = client.scroll(
            collection_name=collection_name,
            limit=scroll_limit,
            scroll_filter=qdrant_filter
        )
        return [p.payload for p in points]

    elif action == "search":
        qdrant_filter = build_filter(plan.get("query_filter", {}))  # chú ý đổi thành query_filter
        query_text = plan["query_text"]
        query_vector  = embedding_model.embed_query(query_text) 

        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            score_threshold=search_threshold,
            limit=limit,
            query_filter=qdrant_filter
        )
        return [{"payload": r.payload, "score": r.score} for r in results]

    else:
        raise ValueError(f"Unknown action type: {action}")

# def generate_vector_query(question: str, llm, collection_name, limit):
#     vector_prompt = ChatPromptTemplate.from_template("""
#         You are a TEXT2VECTORQUERY system. 
#         Your job is to translate user questions into a valid Qdrant query in JSON format. 
#         Use one of two actions: "search" or "scroll".

#         Rules:
#         - If the question is asking to list attributes of a specific candidate (skills or experiences),
#           use "scroll" with a filter on candidate_name and type.
#         - If the question is asking to find candidates by skill, experience, or semantic content,
#           use "search" with query_text and type filter.
#         - Always return a valid JSON object only, no extra text.
                                                     
#         collection_name: {collection_name}
#         limit: {limit}

#         Schema:
                                                     
#         Skill points schema (per-skill embedding).
#         Skill vector stores one vector per individual skill term (e.g., “Python”), 
#         with lightweight candidate/context metadata for fast semantic search on skills.. 
#         Example schema for skill point schema:
#         {{
#             "id": "skill-15.pdf-{{skill}}-{{uuid.uuid4().hex[:8]}}", 
#             "vector": embed_query(skill),          
#             "payload": {{
#                 "type": "skill",
#                 "skill": skill,
#                 "job_title": "Data Engineer",
#                 "source_file": "15.pdf",                               
#                 "candidate_name": "Pooya Karimian"
#             }}
#         }}
#         Experience points schema (per-experience embedding).
#         Embeds a composed experience string (role, company, time range, description to enable semantic retrieval of rich work history, plus detailed metadata for display. 
#         Don't confuse the job_title in the payload with the job_title in experience_detail. The former is the candidate's current job title, while the latter is part of the experience                                    
#         Example schema for experience:
#         Given exp_text as "{{exp.get('job_title', '')}} at {{exp.get('company', '')}} ({{exp.get('start_date', '')}} - {{exp.get('end_date', '')}}) {{exp.get('description', '')}}"
#         {{
#             "id": "exp-{{filename}}-{{exp.get('company', 'unknown')}}--{{uuid.uuid4().hex[:8]}}",  
#             "vector": embed_query(exp_text),          
#             "payload": {{
#                 "type": "experience",   
#                 "experience": exp_text,    
#                 "experience_detail": exp dict,  
#                 "job_title": "Data Enginner",
#                 "source_file": "15.pdf",                                                         
#                 "candidate_name": "Pooya Karimian"
#             }}
#         }}

#         Format:
#         {{
#           "action": "scroll",
#           "collection_name": collection_name,
#           "scroll_filter": {{
#             "must": [
#               {{"key": "candidate_name", "match": {{"value": "Pooya Karimian"}}}},
#               {{"key": "type", "match": {{"value": "skill"}}}}
#             ]
#           }},
#           "limit": {limit}
#         }}
#         or
#         {{
#           "action": "search",
#           "collection_name": collection_name,
#           "query_text": "Python",
#           "query_filter": {{
#             "must": [
#               {{"key": "type", "match": {{"value": "skill"}}}}
#             ]
#           }},
#           "limit": {limit}
#         }}
                                                     
#         If the user require a specific number of results ("Find 3 candidates who..."), you can override the predefined limit value (3 in the example).

#         Question: {question}
#         Return only raw JSON, no explanation.
#     """)

#     response = llm.invoke(vector_prompt.format(question=question, collection_name=collection_name, limit=limit))
#     response = response.content.strip()
#     cleaned = re.sub(r"^```json\s*|\s*```$", "", response.strip())
#     return cleaned.strip()


# def build_filter(filter_json: dict) -> Filter:
#     """
#     Convert filter JSON (must, should, must_not) into Qdrant Filter object
#     """
#     must_conditions, should_conditions, must_not_conditions = [], [], []

#     for cond in filter_json.get("must", []):
#         must_conditions.append(
#             FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
#         )
#     for cond in filter_json.get("should", []):
#         should_conditions.append(
#             FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
#         )
#     for cond in filter_json.get("must_not", []):
#         must_not_conditions.append(
#             FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
#         )

#     return Filter(must=must_conditions or None,
#                   should=should_conditions or None,
#                   must_not=must_not_conditions or None)

# def execute_vector_query(plan: dict, client: QdrantClient, embedding_model, search_threshold=0.75):

#     action = plan["action"]
#     collection_name = plan["collection_name"]
#     limit = plan.get("limit", 10)

#     if action == "scroll":
#         scroll_limit = 30
#         qdrant_filter = build_filter(plan.get("scroll_filter", {}))
#         points, next_page = client.scroll(
#             collection_name=collection_name,
#             limit=scroll_limit,
#             scroll_filter=qdrant_filter
#         )
#         return [p.payload for p in points]

#     elif action == "search":
#         qdrant_filter = build_filter(plan.get("query_filter", {}))
#         query_text = plan["query_text"]
#         query_vector  = embedding_model.embed_query(query_text) 

#         results = client.search(
#             collection_name=collection_name,
#             query_vector=query_vector,
#             score_threshold=search_threshold,
#             limit=limit,
#             query_filter=qdrant_filter
#         )
#         return [{"payload": r.payload, "score": r.score} for r in results]

#     else:
#         raise ValueError(f"Unknown action type: {action}")

def search_vector(query: str, llm, embedding_model, qdrant_db, collection, limit=30, search_threshold=0.72):
    output = generate_vector_query(query, llm, collection, limit)
    plan = json.loads(output)
    print(plan)
    results = execute_vector_query(plan, qdrant_db, embedding_model, search_threshold=search_threshold)
    return results, plan




# results, plan = search_vector(
#     query="Find candidates with Python skill and had experience in Software",
#     llm=deepseek,
#     embedding_model=embedding,
#     qdrant_db=qdrant,
#     collection="candidates",
#     limit=5
# )

# print("Query plan:", json.dumps(plan, indent=2))
# for r in results:
#     print(r)

# qdrant.close()