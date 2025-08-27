from rag_modules import route_query, generate_sql, search_vector
# from app.rag_pipeline.rag_modules import route_query, generate_sql, search_vector
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from sqlalchemy import text
import os, sys
from langchain_google_genai import ChatGoogleGenerativeAI
from qdrant_client import QdrantClient
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.prompts import ChatPromptTemplate
from sqlalchemy import create_engine, text
from langgraph.graph import END

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.config import DEEPSEEK_API_KEY, GOOGLE_API_KEY

# ---- State định nghĩa ----
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
    results, plan = search_vector(state["question"], llm, embedding_model, qdrant_db, collection, limit, search_threshold)
    state["vector_result"] = results
    state["vector_query"] = plan
    # state["final_answer"] = f"Kết quả VectorDB: {results}"
    return state

# def summarizer_node(state: CandidateState, llm):
#     if state["route"] == "SQL":
#         context = f"SQL result: {state.get('sql_result', [])}"
#     else:
#         context = f"VectorDB result: {state.get('vector_result', [])}"

#     prompt = ChatPromptTemplate.from_template("""
#     You are a recruiting assistant. 
#     The admin will ask a question: {question}
#     And the system (either Postgres or Qdrant vector database) will return a raw answer: {context}
    
#     Answer to the admin only include the main context of the answer in a short, natural, and understandable way.
#     If there is no answer returned, just say "I don't know".
#     """)
#     response = llm.invoke(prompt.format(question=state["question"], context=context))
#     state["final_answer"] = response.content.strip()
#     return state
    
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
def build_flow(llm, engine, embedding_model, qdrant_db, collection, limit, search_threshold=0.3):
    graph = StateGraph(CandidateState)

    # Add nodes
    graph.add_node("router", lambda state: router_node(state, llm))
    graph.add_node("sql", lambda state: sql_node(state, llm, engine))
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

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=GOOGLE_API_KEY)
# embedding = GPT4AllEmbeddings()
embedding = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-exp-03-07", api_key=GOOGLE_API_KEY)
# engine = create_engine("postgresql://postgres:phatdeptrai123@localhost:5432/candidates")

# qdrant = QdrantClient(path="../qdrant_gemini_db")
# print("Collections hiện có:", qdrant.get_collections())


db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../qdrant_gemini_db"))
qdrant = QdrantClient(path=db_path)
COLLECTION_NAME = "candidates"



flow = build_flow(llm, engine, embedding, qdrant, COLLECTION_NAME, limit=50)

result = flow.invoke({"question": "Who has experience in Software Engineer?"})
# source_files = [item["payload"].get("source_file") for item in result["final_answer"] if "payload" in item]
print(result["final_answer"])
print(result["vector_query"])

qdrant.close()