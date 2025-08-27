import os
import sys

# === Third-party libraries ===
from sqlalchemy import create_engine, text
from qdrant_client import QdrantClient
from langchain_community.embeddings import GPT4AllEmbeddings
from langchain.embeddings import FakeEmbeddings
from langchain.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI

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
sys.path.append(os.path.abspath('../../'))
from config.config import DEEPSEEK_API_KEY, DATABASE_URL

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

# ---- State định nghĩa ----
class CandidateState(dict):
    question: str
    route: str
    sql_query: str
    sql_result: list
    vector_result: list
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

# def sql_node(state: CandidateState, llm, engine):
#     sql_query = generate_sql(state["question"], llm)
#     state["sql_query"] = sql_query

#     with engine.connect() as conn:
#         result = conn.execute(text(sql_query)).fetchall()
#         state["sql_result"] = [dict(row._mapping) for row in result]

#     state["final_answer"] = f"Kết quả SQL: {state['sql_result']}"
#     return state

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

def vector_node(state: CandidateState,llm, embedding_model, qdrant_db, collection):
    results = search_vector(state["question"], llm, embedding_model, qdrant_db, collection, limit=3)
    state["vector_result"] = results
    state["final_answer"] = f"Kết quả VectorDB: {results}"
    return state

def summarizer_node(state: CandidateState, llm):
    if state["route"] == "SQL":
        context = f"Kết quả SQL: {state.get('sql_result', [])}"
    else:
        context = f"Kết quả VectorDB: {state.get('vector_result', [])}"

    print(context)

    prompt = ChatPromptTemplate.from_template("""
    You are a recruiting assistant. 
    The admin will ask a question: {question}
    And the system (either Postgres or Qdrant vector database) will return a raw answer: {context}
    
    Answer to the admin only include the main context of the answer in a short, natural, and understandable way.
    """)
    response = llm.invoke(prompt.format(question=state["question"], context=context))
    state["final_answer"] = response.content.strip()
    return state

# ---- Build Flow ----
# def build_flow(llm, engine, embedding_model, qdrant_db, collection):
#     graph = StateGraph(CandidateState)

#     # Add nodes
#     graph.add_node("router", lambda state: router_node(state, llm))
#     graph.add_node("sql", lambda state: sql_node(state, llm, engine))
#     graph.add_node("vector", lambda state: vector_node(state,llm, embedding_model, qdrant_db, collection))
#     graph.add_node("summarizer", lambda state: summarizer_node(state, llm))

#     # Conditional edge từ router
#     graph.add_conditional_edges(
#         "router",
#         router_condition,  
#         {
#             "sql": "sql",
#             "vector": "vector",
#             END: END,
#         },
#     )

#     # Entry point
#     graph.add_edge("sql", "summarizer")
#     # Vector → summarizer
#     graph.add_edge("vector", "summarizer")

#     # summarizer → END
#     graph.add_edge("summarizer", END)

#     # Entry point
#     graph.set_entry_point("router")

#     return graph.compile()


# --- Build graph ---
def build_flow(embedding_model, qdrant_db: QdrantClient, collection: str, *, public_base_url: str | None = None):
    graph = StateGraph(CandidateState)

    graph.add_node("router", lambda state: router_node(state, llm_chat))
    graph.add_node("sql", lambda s: sql_node(s, base_url=public_base_url))
    graph.add_node("vector", lambda s: vector_node(s, embedding_model, qdrant_db, collection))
    graph.add_node("summarizer", lambda s: summarizer_node(s, llm_chat))

    graph.add_conditional_edges(
        "router",
        router_condition,
        {
            "sql": "sql",
            "vector": "vector",
            END: END,
        },
    )
    graph.add_edge("sql", "summarizer")
    graph.add_edge("vector", "summarizer")
    graph.add_edge("summarizer", END)
    graph.set_entry_point("router")

    return graph.compile()


embedding_model = FakeEmbeddings(size=768)  # thay cho GPT4AllEmbeddings()
qdrant = QdrantClient(url="http://localhost:6333")  # nếu chưa chạy cũng không sao, route có thể về SQL
public_base_url = None  # hoặc "http://localhost:8000"
app = build_flow(embedding_model, qdrant, collection="cvs", public_base_url=public_base_url)


if __name__ == "__main__":
    # Embedding + Qdrant (nếu chưa có thì dummy để test route SQL)
    # embedding_model = GPT4AllEmbeddings()  # hoặc model embeddings bạn dùng
    # qdrant = QdrantClient(url="http://localhost:6333")  # nếu chưa chạy Qdrant, route sẽ đi SQL
    # embedding_model = FakeEmbeddings(size=768)  # thay cho GPT4AllEmbeddings()
    # qdrant = QdrantClient(url="http://localhost:6333")  # nếu chưa chạy cũng không sao, route có thể về SQL

    # # Build graph (public_base_url: nếu đang chạy FastAPI serve /media, set http://localhost:8000)
    # public_base_url = None  # hoặc "http://localhost:8000"
    # app = build_flow(embedding_model, qdrant, collection="cvs", public_base_url=public_base_url)

    # Hỏi đáp
    state = {"question": "List candidates with the job title 'Software Engineer'."}
    result = app.invoke(state)

    print("Route:", result.get("route"))
    print("SQL:\n", result.get("sql_query"))
    print("Answer (final):", result.get("final_answer"))