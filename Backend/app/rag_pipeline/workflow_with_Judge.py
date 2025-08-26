from rag_modules import route_query, generate_sql, search_vector, pre_retrieval_judge, post_retrieval_judge, rewrite_query

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from sqlalchemy import text
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from qdrant_client import QdrantClient
from langchain_community.embeddings import GPT4AllEmbeddings
from langchain.prompts import ChatPromptTemplate
from sqlalchemy import create_engine, text
from langgraph.graph import END

# ---- State định nghĩa ----
class CandidateState(dict):
    question: str
    pre_judge: str
    post_judge: str
    route: str
    sql_query: str
    sql_result: list
    vector_result: list
    final_answer: str

def pre_judge_condition(state):
    if state["pre_judge"] == "Casual":
        return "casual"
    elif state["pre_judge"] == "HR":
        return "hr"     
    return END

def post_judge_condition(state):
    if state["post_judge"] == "Satisfactory":
        return "satisfactory"
    elif state["post_judge"] == "Unsatisfactory":
        return "unsatisfactory"     
    return END

def pre_judge_node(state: CandidateState, llm):
    result = pre_retrieval_judge(state["question"], llm)
    state["pre_judge"] = result
    return state

def post_judge_node(state: CandidateState, llm, max_rewrites=2):
    result = post_retrieval_judge(state["question"], 
                                  str(state.get("sql_result", [])) + str(state.get("vector_result", [])), 
                                  llm)
    state["post_judge"] = result

    if result == "Unsatisfactory":
        if state.get("rewrite_count", 0) < max_rewrites:
            new_q = rewrite_query(state["question"], llm)
            state["question"] = new_q
            state["rewrite_count"] = state.get("rewrite_count", 0) + 1
        else:
            # Nếu vượt quá số lần rewrite thì trả về "I don't know"
            state["final_answer"] = "I don't know."
    return state


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

def vector_node(state: CandidateState,llm, embedding_model, qdrant_db, collection, limit, search_threshold):
    results = search_vector(state["question"], llm, embedding_model, qdrant_db, collection, limit, search_threshold)
    state["vector_result"] = results
    state["final_answer"] = f"Kết quả VectorDB: {results}"
    return state

def summarizer_node(state: CandidateState, llm):
    # Nếu pre_judge là Casual thì chỉ cần trả lời small-talk
    if state.get("pre_judge") == "Casual":
        prompt = ChatPromptTemplate.from_template("""
            You are a normal chatbot. 
            The admin wants to chat and send you a text: {question}
            You should just respond naturally like a common friend, make a casual chat and small talk.
            """)
        response = llm.invoke(prompt.format(question=state["question"]))
        state["final_answer"] = response.content.strip()
        return state
    # elif state.get("route") == "SQL":
    #     context = f"SQL result: {state.get('sql_result', [])}"
    # elif state.get("route") == "VECTOR":
    #     context = f"VectorDB result: {state.get('vector_result', [])}"
    # else:
    #     context = "No context"
    route = state.get("route", None)
    if route == "SQL":
        context = f"SQL result: {state.get('sql_result', [])}"
    elif route == "VECTOR":
        context = f"VectorDB result: {state.get('vector_result', [])}"
    else:
        context = "No context"
    
    prompt = ChatPromptTemplate.from_template("""
    You are a recruiting assistant. 
    The admin will ask a question: {question}
    And the system (either Postgres or Qdrant vector database) will return a raw answer: {context}
    
    Answer to the admin only include the main context of the answer in a short, natural, and understandable way.
    If there is no answer returned, just say "I don't know".
    """)
    response = llm.invoke(prompt.format(question=state["question"], context=context))
    state["final_answer"] = response.content.strip()
    return state


# ---- Build Flow ----
def build_flow(llm, engine, embedding_model, qdrant_db, collection, limit, search_threshold=0.75, max_rewrites=2):
    graph = StateGraph(CandidateState)

    # Add nodes
    graph.add_node("pre_judge_node", lambda state: pre_judge_node(state, llm))
    graph.add_node("router", lambda state: router_node(state, llm))
    graph.add_node("sql", lambda state: sql_node(state, llm, engine))
    graph.add_node("vector", lambda state: vector_node(state,llm, embedding_model, qdrant_db, collection, limit, search_threshold))
    graph.add_node("post_judge_node", lambda state: post_judge_node(state, llm, max_rewrites))
    graph.add_node("summarizer", lambda state: summarizer_node(state, llm))

    # Flow: pre_judge → (casual or hr)
    graph.add_conditional_edges(
        "pre_judge_node",
        pre_judge_condition,
        {
            "casual": "summarizer",
            "hr": "router",
            END: END,
        }
    )

    # Router: chọn sql hay vector
    graph.add_conditional_edges(
        "router",
        router_condition,  
        {
            "sql": "sql",
            "vector": "vector",
            END: END,
        },
    )

    # sql/vector → post_judge
    graph.add_edge("sql", "post_judge_node")
    graph.add_edge("vector", "post_judge_node")

    # post_judge → summarizer hoặc quay lại router
    graph.add_conditional_edges(
        "post_judge_node",
        post_judge_condition,
        {
            "satisfactory": "summarizer",
            "unsatisfactory": "router",
            END: END,
        },
    )

    # summarizer → END
    graph.add_edge("summarizer", END)

    # Entry point
    graph.set_entry_point("pre_judge_node")

    return graph.compile()


