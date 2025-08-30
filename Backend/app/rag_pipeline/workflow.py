import os, sys
import sys

# === Third-party libraries ===
from sqlalchemy import create_engine, text
from qdrant_client import QdrantClient
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# === LangGraph ===
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

# === Local modules ===
# from rag_modules import route_query, generate_sql, search_vector
from app.rag_pipeline.rag_modules import route_query, generate_sql, search_vector

# === text2SQL modules ===
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from text2SQL.llm_adapter import LLM
from text2SQL.main import gen_sql_query
from text2SQL.enrich import enrich_with_resume_urls

# === Config ===
# sys.path.append(os.path.abspath('../../'))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.config import DEEPSEEK_API_KEY, DATABASE_URL, GOOGLE_API_KEY

# === Engine & LLM setup ===
engine = create_engine(DATABASE_URL, future=True)
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

def sql_node(state: CandidateState, *, base_url: str | None = None):
    """
    Giữ nguyên format state cũ: điền sql_query / columns / sql_result / trials.
    Thêm 'resume_url' bằng cách join attachments (latest file).
    """
    try:
        result = gen_sql_query(engine, llm_sql, state["question"], max_refine=1)

        state["sql_query"] = result["sql"]
        state["columns"] = result["columns"]

        enriched_rows = enrich_with_resume_urls(
            engine, result["columns"], result["rows"], base_url=base_url
        )
        state["sql_result"] = enriched_rows
        state["trials"] = result.get("trials", [])

        # nếu UI của bạn đang đọc final_answer = bảng, giữ nguyên định dạng
        state["final_answer"] = {
            "type": "table",
            "columns": (
                result["columns"] if "resume_url" in result["columns"]
                else result["columns"] + ["resume_url"]
            ),
            "rows": enriched_rows,
        }
        return state

    except Exception as e:
        state["sql_query"] = None
        state["columns"] = []
        state["sql_result"] = []
        state["trials"] = []
        state["final_answer"] = {"type": "error", "message": f"Text2SQL failed: {e}"}
        return state


def vector_node(state: CandidateState,llm, embedding_model, qdrant_db, collection, limit, search_threshold):
    results, plan = search_vector(state["question"], llm, embedding_model, qdrant_db, collection, limit, search_threshold)
    # results, plan = search_vector(state["question"], llm, embedding_model, qdrant_db, collection, limit, search_threshold)
    state["vector_result"] = results
    state["vector_query"] = plan
    # state["final_answer"] = f"Kết quả VectorDB: {results}"
    state["vector_query"] = plan
    # state["final_answer"] = f"Kết quả VectorDB: {results}"
    return state

    
def summarizer_node(state: CandidateState, llm=None):
    sql_result = state.get("sql_result", [])
    vector_result = state.get("vector_result", [])

    if sql_result:  # Ưu tiên SQL
        state["final_answer"] = sql_result
    elif vector_result:  # Nếu không có SQL thì trả Vector
        state["final_answer"] = vector_result
    else:
        state["final_answer"] = "I don't know"

    return state

# ---- Build Flow ----
def build_flow(llm, embedding_model, qdrant_db, collection, limit, search_threshold=0.3, public_base_url: str | None = None):
    graph = StateGraph(CandidateState)

    # Add nodes
    graph.add_node("router", lambda state: router_node(state, llm))
    # graph.add_node("sql", lambda state: sql_node(state, llm, engine))
    graph.add_node("sql", lambda s: sql_node(s, base_url=public_base_url))
    graph.add_node("vector", lambda state: vector_node(state,llm, embedding_model, qdrant_db, collection, limit, search_threshold))
    graph.add_node("summarizer", lambda state: summarizer_node(state, llm))

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
    # Vector → summarizer
    graph.add_edge("vector", "summarizer")

    # summarizer → END
    graph.add_edge("summarizer", END)

    # Entry point
    graph.set_entry_point("router")

    return graph.compile()


# embedding_model = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-exp-03-07", api_key=GOOGLE_API_KEY)
# db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../qdrant_gemini_db"))
# qdrant = QdrantClient(path=db_path)
# COLLECTION_NAME = "candidates"
# public_base_url = None  # hoặc "http://localhost:8000"
# flow = build_flow(llm_chat, embedding_model, qdrant, COLLECTION_NAME, limit=50, public_base_url=public_base_url)

# result = flow.invoke({"question": "List all candidate names."})
# # source_files = [item["payload"].get("source_file") for item in result["final_answer"] if "payload" in item]
# if isinstance(result["final_answer"], list) and result.get("sql_result"):
#     print("SQL result:", result["sql_result"])
# elif isinstance(result["final_answer"], list) and result.get("vector_result"):
#     print("Vector result:", result["vector_result"])
# elif result["final_answer"] == "I don't know":
#     print("No result found.")
# else:
#     print(result["final_answer"])
# qdrant.close()