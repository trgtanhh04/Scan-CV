from rag_pipeline import route_query, generate_sql, search_vector

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from sqlalchemy import text
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from qdrant_client import QdrantClient
from langchain_community.embeddings import GPT4AllEmbeddings
from sqlalchemy import create_engine, text

# ---- State định nghĩa ----
class CandidateState(dict):
    question: str
    route: str
    sql_query: str
    sql_result: list
    vector_result: list
    final_answer: str

# ---- Node functions ----
def router_node(state: CandidateState, llm):
    route = route_query(state["question"], llm)
    state["route"] = route
    return state

def sql_node(state: CandidateState, llm, engine):
    sql_query = generate_sql(state["question"], llm)
    state["sql_query"] = sql_query

    with engine.connect() as conn:
        result = conn.execute(text(sql_query)).fetchall()
        state["sql_result"] = [dict(row._mapping) for row in result]

    # format lại kết quả
    state["final_answer"] = f"Kết quả SQL: {state['sql_result']}"
    return state

def vector_node(state: CandidateState, embedding_model, qdrant_db, collection):
    results = search_vector(state["question"], embedding_model, qdrant_db, collection, limit=3)
    state["vector_result"] = results
    state["final_answer"] = f"Kết quả VectorDB: {results}"
    return state

# ---- Build Flow ----
def build_flow(llm, engine, embedding_model, qdrant_db, collection):
    graph = StateGraph(CandidateState)

    # Add nodes
    graph.add_node("router", lambda state: router_node(state, llm))
    graph.add_node("sql", lambda state: sql_node(state, llm, engine))
    graph.add_node("vector", lambda state: vector_node(state, embedding_model, qdrant_db, collection))

    # Add edges
    graph.add_edge("router", "sql", condition=lambda state: state["route"] == "SQL")
    graph.add_edge("router", "vector", condition=lambda state: state["route"] == "VECTOR")

    # Entry point
    graph.set_entry_point("router")

    # Finish
    graph.add_edge("sql", END)
    graph.add_edge("vector", END)

    return graph.compile()

# ---- Run thử ----
if __name__ == "__main__":
    os.environ["GOOGLE_API_KEY"] = "AIzaSyBJ86qCzZw5qIVhhdb_VB28OaQz42Oj6GU"

    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")



    # Thay đổi username, password, db_name theo config của bạn
    engine = create_engine("postgresql://postgres:phatdeptrai123@localhost:5432/candidates")


    qdrant = QdrantClient(path="../qdrant_initial_db2")
    COLLECTION_NAME = "candidates_vectors"
    embedding = GPT4AllEmbeddings()
    # giả sử bạn đã có llm, engine, embedding_model, qdrant_db
    flow = build_flow(llm, engine, embedding, qdrant, "candidates_skills")

    # test câu hỏi
    result = flow.invoke({"question": "GPA của Nguyễn Văn A là bao nhiêu?"})
    print(result["final_answer"])

    result = flow.invoke({"question": "Ứng viên nào có kinh nghiệm React?"})
    print(result["final_answer"])