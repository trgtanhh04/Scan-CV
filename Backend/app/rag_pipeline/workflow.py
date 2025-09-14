import os, sys

import os, sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)
import re
# === Third-party libraries ===
from sqlalchemy import create_engine
from qdrant_client import QdrantClient
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from unidecode import unidecode
from typing import List

from sqlalchemy.orm import Session
from app.models.models import SessionLocal, Candidate, Skill, Educations

# === LangGraph ===
from langgraph.graph import StateGraph, END

from app.rag_pipeline.rag_modules_test import search_vector, route_query, split_hybrid_query
from app.text2SQL.t2sql_core import LLM, answer_sql

# === Config ===
# sys.path.append(os.path.abspath('../../'))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY, QDRANT_COLLECTION, QDRANT_URL, EMBEDDING_MODEL_NAME, DATABASE_URL

# === Engine & LLM setup ===
deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

# == Set up cho Text2SQL ===
engine = create_engine(DATABASE_URL, future=True)
def _invoke(prompt: str) -> str:
    resp = deepseek.invoke([HumanMessage(content=prompt)])
    return resp.content
llm_sql = LLM(_invoke)

# === Set up Qdrant cho RAG ===
embedding = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, api_key=GOOGLE_API_KEY, request_timeout=60)
qdrant = QdrantClient(url=QDRANT_URL)

# ==== WORKFLOW ====
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
# from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY

class CandidateState(dict):
    question: str
    pre_judge: str
    post_judge: str
    route: str
    sql_query: str
    sql_result: list
    vector_result: list
    vector_query: dict
    final_answer: str

def router_condition(state):
    if state["route"] == "SQL":
        return "sql"
    elif state["route"] == "VECTOR":
        return "vector"
    elif state["route"] == "HYBRID":
        return "hybrid"
    return END

# ---- Node functions ----
def router_node(state: CandidateState, llm):
    route = route_query(state["question"], llm)
    state["route"] = route
    return state

def sql_node(state: CandidateState, limit: int):
    try:
        result = answer_sql(engine, llm_sql, state["question"], max_refine=1, limit=limit)
        state["sql_result"] = result.get("rows") or []

        state["final_answer"] = {
            "type": "table",
            "sql_query": result.get("sql") or "",
            "columns": result.get("columns") or [],
            "rows": result.get("rows") or [],
        }

        return state
    except Exception as e:
        state["sql_query"]   = None
        state["sql_result"]  = []
        state["final_answer"]= {"type": "error", "message": f"Text2SQL failed: {e}"}
        return state


def vector_node(state: CandidateState,llm, embedding_model, qdrant_db, collection, limit, search_threshold):
    results, plan = search_vector(state["question"], llm, embedding_model, qdrant_db, collection, limit, search_threshold)
    state["vector_result"] = results

    state["final_answer"] = {
        "type": "vector",
        "rag_query": plan,
        "columns": results['columns'] or [],
        "rows": results['rows'] or [],
    }
    return state

def hybrid_node(state: CandidateState, llm, embedding_model, qdrant_db, collection, limit, search_threshold):
    subqueries = split_hybrid_query(state["question"], llm)
    # if isinstance(subqueries.get("sql_query"), str):
    #     print("SQL:", subqueries.get("sql_query"))
    # if isinstance(subqueries.get("vector_query"), str):
    #     print("Vector:", subqueries.get("vector_query"))
    sql_q = subqueries.get("sql_query", "")
    vector_q = subqueries.get("vector_query", "")

    # Initialize locals so every path has defined variables
    sql = ""
    vector = {}
    sql_result, vector_result = [], {}
    sql_rows, vector_rows = [], []
    sql_columns, vector_columns = [], []
    merged_columns = []
    merged_rows = []
    limit = 100

    # --- SQL ---
    if sql_q:
        try:
            print("Executing SQL query:", sql_q)
            result = answer_sql(engine, llm_sql, sql_q, max_refine=1, limit=limit)
            sql = result.get("sql") or ""
            sql_result = result.get("rows") or []
            sql_columns = ["id", "email", "resume_url"]  # biết trước cột
            sql_rows = [dict(zip(sql_columns, row)) for row in sql_result]
        except Exception as e:
            print("SQL error:", e)

    # --- VECTOR ---
    if vector_q:
        try:
            results, plan = search_vector(vector_q, llm, embedding_model, qdrant_db, collection, limit, search_threshold)
            vector_result = results or {}
            vector = plan
            vector_columns = vector_result.get("columns", [])
            vrows = vector_result.get("rows", [])
            vector_rows = [dict(zip(vector_columns, row)) for row in vrows]
            unique_vector = {}
            for vrow in vector_rows:
                email = vrow.get("email")
                if email and email not in unique_vector:
                    unique_vector[email] = vrow
            vector_rows = list(unique_vector.values())
        except Exception as e:
            print("Vector error:", e)

    # --- JOIN (intersection by email) ---
    merged = []
    if sql_rows and vector_rows:
        sql_dict = {row.get("email"): row for row in sql_rows if row.get("email")}
        for vrow in vector_rows:
            email = vrow.get("email")
            if email and email in sql_dict:
                # merge keeping both sides (SQL fields may overwrite duplicates)
                merged_row = {**vrow, **sql_dict[email]}
                merged.append(merged_row)
    else:
        merged = sql_rows or vector_rows or []

    # print("Merged rows:", merged)

    # --- Chuẩn hoá columns ---
    # --- Normalize columns deterministically ---
    desired_order = ["id", "email", "resume_url", "job_title", "skills", "educations"]
    if merged:
        seen_cols = []
        for row in merged:
            for col in row.keys():
                if col not in seen_cols:
                    seen_cols.append(col)
        merged_columns = seen_cols
    else:
        merged_columns = list(sql_columns or vector_columns or [])

    # Apply desired ordering first, keep remaining columns afterwards
    merged_columns = [col for col in desired_order if col in merged_columns] + [col for col in merged_columns if col not in desired_order]
    merged_rows = [[row.get(col) for col in merged_columns] for row in merged]
    merged_rows = merged_rows[:10]

    state["sql_result"] = sql_rows
    state["vector_result"] = vector_rows
    state["final_answer"] = {
        "type": "hybrid",
        "sql_query": sql_q,
        "sql_result": sql,
        "sql_rows": sql_rows,
        "vector_query": vector_q,
        "vector_result": vector,
        "vector_rows": vector_rows,
        "columns": merged_columns,
        "rows": merged_rows,   # luôn là list[dict]
    }
    return state

def summarizer_node(state: CandidateState):
    sql_result = state.get("sql_result", [])
    vector_result = state.get("vector_result", [])

    if sql_result:               # Ưu tiên SQL
        return state
    elif vector_result:          # chỉ xét vector nếu không có SQL
        return state
    else:
        state["final_answer"] = "I don't know"
    return state


def build_flow(llm, embedding_model, qdrant_db, collection, limit=10, search_threshold=0.72):
    graph = StateGraph(CandidateState)

    graph.add_node("router", lambda state: router_node(state, llm))
    graph.add_node("sql", lambda state: sql_node(state, limit))
    graph.add_node("vector", lambda state: vector_node(state,llm, embedding_model, qdrant_db, collection, limit, search_threshold))
    graph.add_node("hybrid", lambda state: hybrid_node(state,llm, embedding_model, qdrant_db, collection, limit, search_threshold))
    graph.add_node("summarizer", lambda state: summarizer_node(state))

    graph.add_conditional_edges(
        "router",
        router_condition,  
        {
            "sql": "sql",
            "vector": "vector",
            "hybrid": "hybrid",   # thêm HYBRID
            END: END,
        },
    )

    graph.add_edge("sql", "summarizer")
    graph.add_edge("vector", "summarizer")
    graph.add_edge("hybrid", "summarizer")
    graph.add_edge("summarizer", END)

    graph.set_entry_point("router")

    return graph.compile()

# ---- Enrich Education, Skills, Job Title ----
def enrich_with_skills_and_edu(session: Session, candidate_emails: List[str]):
    """
    Trả về dict:
    {
        candidate_id: {
            "job_title": ...,
            "skills": [...],
            "educations": [{"degree":..., "university":...}, ...]
        }
    }
    """
    # Lấy map email -> id
    email_id_map = {}
    if candidate_emails:
        rows = session.query(Candidate.id, Candidate.email).filter(Candidate.email.in_(candidate_emails)).all()
        for cid, email in rows:
            email_id_map[email] = cid

    candidate_ids = list(email_id_map.values())
    result_map = {cid: {"skills": [], "educations": [], "job_title": None} for cid in candidate_ids}

    # Lấy job_title
    if candidate_ids:
        job_rows = (
            session.query(Candidate.id, Candidate.job_title)
            .filter(Candidate.id.in_(candidate_ids))
            .all()
        )
        for cid, job_title in job_rows:
            result_map[cid]["job_title"] = job_title

    # Lấy skills
    if candidate_ids:
        skill_rows = (
            session.query(Candidate.id, Skill.name)
            .join(Candidate.skills)
            .filter(Candidate.id.in_(candidate_ids))
            .all()
        )
        for cid, sname in skill_rows:
            result_map[cid]["skills"].append(sname)

    # Lấy educations
    if candidate_ids:
        edu_rows = (
            session.query(Candidate.id, Educations.degree, Educations.university)
            .join(Candidate.educations)
            .filter(Candidate.id.in_(candidate_ids))
            .all()
        )
        for cid, degree, uni in edu_rows:
            result_map[cid]["educations"].append({"degree": degree, "university": uni})

    # Trả về map id -> info, và map email -> id
    return result_map, email_id_map


def enrich_final_answer(state: dict) -> dict:
    flow = build_flow(deepseek, embedding, qdrant, QDRANT_COLLECTION, limit=10, search_threshold=0.3)
    answer = flow.invoke(state)

    print("Route chosen:", answer.get("route"))

    if isinstance(answer.get("sql_query"), str):
        print("SQL query:", answer.get("sql_query"))
    if isinstance(answer.get("vector_query"), str):
        print("Vector query:", answer.get("vector_query"))

    # Lấy danh sách email từ kết quả
    try:
        final = answer.get("final_answer", {})
        # Nếu final không phải dict (ví dụ: str "I don't know"), trả về luôn
        if not isinstance(final, dict):
            return answer
        rows = final.get("rows", [])
        columns = final.get("columns", [])
        email_idx = None
        for idx, col in enumerate(columns):
            if col == "email":
                email_idx = idx
                print("Email index:", email_idx)
                break
        candidate_emails = [row[email_idx] for row in rows if email_idx is not None and row[email_idx]] if email_idx is not None else []
        
        # Enrich thêm thông tin from DB. If DB is unavailable, log and continue without enrichment.
        enrich_map = {}
        email_id_map = {}
        try:
            with SessionLocal() as session:
                enrich_map, email_id_map = enrich_with_skills_and_edu(session, candidate_emails)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"Warning: enrichment skipped due to DB error: {e}")

        # Mount thêm vào từng row
        id_idx = None
        email_idx = None
        for idx, col in enumerate(columns):
            if col == "id":
                id_idx = idx
            if col == "email":
                email_idx = idx
        new_rows = []
        for row in rows:
            cid = row[id_idx] if id_idx is not None else None
            email = row[email_idx] if email_idx is not None else None
            # Nếu id không có, thử lấy từ email
            if not cid and email:
                cid = email_id_map.get(email)
            enrich = enrich_map.get(cid, {}) if cid is not None else {}
            row_dict = {col: row[i] for i, col in enumerate(columns)}
            row_dict["job_title"] = enrich.get("job_title")
            row_dict["skills"] = enrich.get("skills", [])
            row_dict["educations"] = enrich.get("educations", [])
            new_rows.append(row_dict)

        # Update final_answer
        final["rows"] = new_rows
        for col in ["job_title", "skills", "educations"]:
            if col not in final.get("columns", []):
                final["columns"].append(col)
        answer["final_answer"] = final
        return answer
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"error": str(e)}


# Test local
if __name__ == "__main__":
    embedding_model = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, api_key=GOOGLE_API_KEY)
    qdrant = QdrantClient(url=QDRANT_URL, check_compatibility=False)
    flow = build_flow(deepseek, embedding_model, qdrant, QDRANT_COLLECTION, limit=10, search_threshold=0.3)

    result = flow.invoke({"question": "Find candidates that know both Python and Java, and have experience in at least 2 different companies."})
    if isinstance(result["final_answer"], list) and result.get("sql_result"):
        print("SQL result:", result["sql_result"])
    elif isinstance(result["final_answer"], list) and result.get("vector_result"):
        print("Vector result:", result["vector_result"])
    elif result["final_answer"] == "I don't know":
        print("No result found.")
    else:
        print(result["final_answer"])
