from rag_pipeline import route_query, generate_sql, search_vector

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from sqlalchemy import text
from langchain.prompts import ChatPromptTemplate
import os
from sqlalchemy import create_engine, text

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

def sql_node(state: CandidateState, llm, engine):
    sql_query = generate_sql(state["question"], llm)
    state["sql_query"] = sql_query

    with engine.connect() as conn:
        result = conn.execute(text(sql_query)).fetchall()
        state["sql_result"] = [dict(row._mapping) for row in result]

    state["final_answer"] = f"Kết quả SQL: {state['sql_result']}"
    return state

def vector_node(state: CandidateState, embedding_model, qdrant_db, collection):
    results = search_vector(state["question"], embedding_model, qdrant_db, collection, limit=3)
    state["vector_result"] = results
    state["final_answer"] = f"Kết quả VectorDB: {results}"
    return state

def summarizer_node(state: CandidateState, llm):
    if state["route"] == "SQL":
        context = f"Kết quả SQL: {state.get('sql_result', [])}"
    else:
        context = f"Kết quả VectorDB: {state.get('vector_result', [])}"

    prompt = ChatPromptTemplate.from_template("""
    You are a recruiting assistant. 
    The admin will as a question: {question}
    And the system (either Postgres or Qdrant vector database) will return a raw answer: {context}
    
    Answer to the admin only include the main context of the answer in a short, natural, and understandable way.
    """)
    response = llm.invoke(prompt.format(question=state["question"], context=context))
    state["final_answer"] = response.content.strip()
    return state

# ---- Build Flow ----
def build_flow(llm, engine, embedding_model, qdrant_db, collection):
    graph = StateGraph(CandidateState)

    # Add nodes
    graph.add_node("router", lambda state: router_node(state, llm))
    graph.add_node("sql", lambda state: sql_node(state, llm, engine))
    graph.add_node("vector", lambda state: vector_node(state, embedding_model, qdrant_db, collection))
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
