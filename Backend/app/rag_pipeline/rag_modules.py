from langchain.prompts import ChatPromptTemplate
from qdrant_client.models import Filter, FieldCondition, MatchValue
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, text
import json
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


def generate_vector_query(question: str, llm, collection_name):
    vector_prompt = ChatPromptTemplate.from_template("""
        You are a TEXT2VECTORQUERY system. 
        Your job is to translate user questions into a valid Qdrant query in JSON format. 
        Use one of two actions: "search" or "scroll".

        Rules:
        - If the question is asking to list attributes of a specific candidate (skills or experiences),
          use "scroll" with a filter on candidate_name and type.
        - If the question is asking to find candidates by skill, experience, or semantic content,
          use "search" with query_text and type filter.
        - Always return a valid JSON object only, no extra text.
                                                     
        collection_name: {collection_name}

        Schema:
        Example schema for skill :
        {{
            "id": "skill-{{candidate_id}}-{{skill}}", 
            "vector": embed_query(skill),          
            "payload": {{
                "type": "skill",                   
                "candidate_id": "123",             
                "candidate_name": "Pooya Karimian"
            }}
        }}
                                                     
        Example schema for experience:
        Given exp_text as "{{exp.get('job_title', '')}} at {{exp.get('company', '')}} ({{exp.get('start_date', '')}} - {{exp.get('end_date', '')}}) {{exp.get('description', '')}}"
        {{
            "id": "exp-{{candidate_id}}-{{hash(exp_text)}}",  
            "vector": embed_query(exp_text),          
            "payload": {{
                "type": "experience",   
                "experience": exp_text,                
                "candidate_id": "123",             
                "candidate_name": "Pooya Karimian"
            }}
        }}

        Format:
        {{
          "action": "scroll",
          "collection_name": collection_name,
          "scroll_filter": {{
            "must": [
              {{"key": "candidate_name", "match": {{"value": "Pooya Karimian"}}}},
              {{"key": "type", "match": {{"value": "skill"}}}}
            ]
          }},
          "limit": 5
        }}
        or
        {{
          "action": "search",
          "collection_name": collection_name,
          "query_text": "Python",
          "query_filter": {{
            "must": [
              {{"key": "type", "match": {{"value": "skill"}}}}
            ]
          }},
          "limit": 5
        }}

        Question: {question}
        Return only raw JSON, no explanation.
    """)

    response = llm.invoke(vector_prompt.format(question=question, collection_name=collection_name))
    response = response.content.strip()
    cleaned = re.sub(r"^```json\s*|\s*```$", "", response.strip())
    return cleaned.strip()


def build_filter(filter_json: dict) -> Filter:
    """
    Convert filter JSON (must, should, must_not) into Qdrant Filter object
    """
    must_conditions, should_conditions, must_not_conditions = [], [], []

    for cond in filter_json.get("must", []):
        must_conditions.append(
            FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
        )
    for cond in filter_json.get("should", []):
        should_conditions.append(
            FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
        )
    for cond in filter_json.get("must_not", []):
        must_not_conditions.append(
            FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
        )

    return Filter(must=must_conditions or None,
                  should=should_conditions or None,
                  must_not=must_not_conditions or None)

def execute_vector_query(plan: dict, client: QdrantClient, embedding_model):
    """
    Execute a vector DB query based on JSON plan (search or scroll)
    plan format ví dụ:
    {
      "action": "search" | "scroll",
      "collection_name": "candidates",
      "query_vector": [...],         # chỉ cần cho search
      "search_filter": {...},        # filter cho search
      "scroll_filter": {...},        # filter cho scroll
      "limit": 5
    }
    """
    action = plan["action"]
    collection_name = plan["collection_name"]
    limit = plan.get("limit", 10)

    if action == "scroll":
        qdrant_filter = build_filter(plan.get("scroll_filter", {}))
        points, next_page = client.scroll(
            collection_name=collection_name,
            limit=limit,
            scroll_filter=qdrant_filter
        )
        return [p.payload for p in points]

    elif action == "search":
        qdrant_filter = build_filter(plan.get("search_filter", {}))
        query_text = plan["query_vector"]
        query_vector = query_vector = embedding_model.embed_query(query_text) 

        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=qdrant_filter
        )
        return [{"payload": r.payload, "score": r.score} for r in results]

    else:
        raise ValueError(f"Unknown action type: {action}")
    
def search_vector(query: str, llm, embedding_model, qdrant_db, collection, limit=3):
    output = generate_vector_query(query, llm, collection)
    plan = json.loads(output)
    # print(plan)
    results = execute_vector_query(plan, qdrant_db, embedding_model)
    return results


