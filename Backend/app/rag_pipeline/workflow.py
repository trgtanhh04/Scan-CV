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

# === LangGraph ===
from langgraph.graph import StateGraph, END

# === Local modules ===
# from rag_modules import route_query, search_vector
# from app.rag_pipeline.rag_modules import route_query, generate_sql, search_vector

# === text2SQL modules ===
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# from text2SQL.enrich import enrich_with_resume_urls
# from text2SQL.t2sql_core import LLM, answer_sql
from app.rag_pipeline.rag_modules_test import search_vector, route_query
from app.text2SQL.t2sql_core import LLM, answer_sql

# === Config ===
# sys.path.append(os.path.abspath('../../'))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY, QDRANT_COLLECTION, QDRANT_URL, EMBEDDING_MODEL_NAME, DATABASE_URL

# === Engine & LLM setup ===
llm_chat = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

# == LLM cho Text2SQL ===
engine = create_engine(DATABASE_URL, future=True)
def _invoke(prompt: str) -> str:
    resp = llm_chat.invoke([HumanMessage(content=prompt)])
    return resp.content
llm_sql = LLM(_invoke)

# === WORKFLOW ===

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY

class CandidateState(dict):
    question: str
    pre_judge: str
    post_judge: str
    route: str
    sql_query: str
    sql_result: list
    vector_result: list
    vector_query: dict
    vector_query: dict
    final_answer: str


# def is_sql(question: str) -> bool:
#     q = unidecode(question.lower())             # "3 nam kinh nghiem tro len"
#     patterns = [
#         r"\b\d+\s*nam\b",                       # 3 nam
#         r">=?\s*\d+\s*nam",                     # >= 3 nam, > 5 nam
#         r"\bat\s*least\b.*\d+\s*year",          # at least 3 years
#         r"\btroi?\s*len\b",                     # trở lên / tro len
#         r"\btoi\s*thieu\b",                     # tối thiểu / toi thieu
#         r"\bkinh\s*nghiem\b.*\d+\s*nam",        # kinh nghiem 3 nam

#     ]
#     if any(re.search(p, q) for p in patterns):
#         return True
#     # if re.search(r"(python|java|aws|spark|golang|skill|ky\s*nang)", q) and \
#     #    re.search(r"(experience|kinh\s*nghiem|job|vi\s*tri|position|software|engineer)", q):
#     #     return True

#     return False

# def is_rag(question: str) -> bool:
#     q = unidecode(question.lower())
#     # cho RAG khi chỉ hỏi skill/experience listing, không có ràng buộc số/so sánh
#     has_skill = bool(re.search(r"\b(skill|ky\s*nang|python|java|aws|spark|golang)\b", q))
#     has_list_exp = bool(re.search(r"(liet\s*ke|ke)\s*.*(experience|kinh\s*nghiem)", q))
#     return (has_skill or has_list_exp) and not is_sql(question)


# def router_node(state: CandidateState):
#     if is_rag(state["question"]):   # match pattern skill/exp
#         state["route"] = "VECTOR"
#         state["rag_mode"] = {"type": "skill_or_exp"}
#     elif is_sql(state["question"]):
#         state["route"] = "SQL"
#         state["rag_mode"] = {"type": None}
#     else:
#         state["route"] = "SQL"
#         state["rag_mode"] = {"type": None}
#     return state

def router_condition(state):
    if state["route"] == "SQL":
        return "sql"
    elif state["route"] == "VECTOR":
        return "vector"
    return END


# ---- Node functions ----
def router_node(state: CandidateState, llm):
    route = route_query(state["question"], llm)
    state["route"] = route
    return state



def sql_node(state: CandidateState, limit: int):
    try:
        result = answer_sql(engine, llm_sql, state["question"], max_refine=1, limit=limit)
        print('result:', result)

        state["sql_query"] = result.get("sql")
        state["columns"]  = result.get("columns") or []
        state["sql_result"] = result.get("rows") or []
        state["trials"]     = result.get("trials", [])

        # (optional) nếu UI đọc final_answer
        state["final_answer"] = {
            "type": "table",
            "columns": state["columns"],
            "rows": state["sql_result"],
        }
        return state
    except Exception as e:
        state["sql_query"]   = None
        state["columns"]     = []
        state["sql_result"]  = []
        state["trials"]      = []
        state["final_answer"]= {"type": "error", "message": f"Text2SQL failed: {e}"}
        return state


def vector_node(state: CandidateState,llm, embedding_model, qdrant_db, collection, limit, search_threshold):
    results, plan = search_vector(state["question"], llm, embedding_model, qdrant_db, collection, limit, search_threshold)
    state["vector_result"] = results
    state["vector_query"] = plan
    # return state
    state["final_answer"] = {
        "type": "vector",
        "rows": results,
    }
    return state

    
def summarizer_node(state: CandidateState):
    sql_result = state.get("sql_result", [])
    vector_result = state.get("vector_result", [])

    if sql_result:               # Ưu tiên SQL
        state["final_answer"] = sql_result
    elif vector_result:          # chỉ xét vector nếu không có SQL
        state["final_answer"] = vector_result
    else:
        state["final_answer"] = "I don't know"

    return state

# ---- Build Flow ----
def build_flow(llm, embedding_model, qdrant_db, collection, limit=10, search_threshold=0.72):
    graph = StateGraph(CandidateState)

    # Add nodes
    graph.add_node("router", lambda state: router_node(state, llm))
    graph.add_node("sql", lambda state: sql_node(state, limit))
    graph.add_node("vector", lambda state: vector_node(state,llm, embedding_model, qdrant_db, collection, limit, search_threshold))
    graph.add_node("summarizer", lambda state: summarizer_node(state))

    # Conditional edge từ router
    graph.add_conditional_edges(
        "router",
        router_condition,  
        {
            "sql": "sql",
            "vector": "vector",
            END: END,
        },
    )

    # Entry point
    graph.add_edge("sql", "summarizer")
    graph.add_edge("vector", "summarizer")
    graph.add_edge("summarizer", END)
    graph.set_entry_point("router")

    return graph.compile()


# Test local
if __name__ == "__main__":
    embedding_model = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, api_key=GOOGLE_API_KEY)
    qdrant = QdrantClient(url=QDRANT_URL, check_compatibility=False)
    flow = build_flow(llm_chat, embedding_model, qdrant, QDRANT_COLLECTION, limit=10, search_threshold=0.3)

    result = flow.invoke({"question": "Find candidates that know both Python and Java, and have experience in at least 2 different companies."})
    if isinstance(result["final_answer"], list) and result.get("sql_result"):
        print("SQL result:", result["sql_result"])
    elif isinstance(result["final_answer"], list) and result.get("vector_result"):
        print("Vector result:", result["vector_result"])
    elif result["final_answer"] == "I don't know":
        print("No result found.")
    else:
        print(result["final_answer"])
