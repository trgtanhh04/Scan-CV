from langchain.prompts import ChatPromptTemplate

import re


def fix_sql_quotes(query: str) -> str:
    fixed_query = re.sub(r'"([^"]*)"', r"'\1'", query)
    return fixed_query

def route_query(question: str, llm):
    router_prompt = ChatPromptTemplate.from_template("""
        You are a classification system. For each user question. 
        Answer 'SQL' if it is related to structured data (full_name, email, phone, job_title) 
        that is stored in a Postgresql database.
        Answer 'VECTOR' if the user question is related to skill and experience.
        Question: {question}
        """)
    response = llm.invoke(router_prompt.format(question=question))
    return response.content.strip()



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


def search_vector(query: str, embedding_model, qdrant_db, collection, limit=3):
    query_vector = embedding_model.embed_query(query) 
    hits = qdrant_db.search(collection_name=collection, query_vector=query_vector, limit=limit)
    return [(hit.id, hit.score, hit.payload) for hit in hits]


