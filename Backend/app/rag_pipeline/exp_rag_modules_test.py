from langchain.prompts import ChatPromptTemplate
from qdrant_client.models import Filter, FieldCondition, MatchValue
from qdrant_client import QdrantClient
from unidecode import unidecode
import json
import re


def fix_sql_quotes(query: str) -> str:
    fixed_query = re.sub(r'"([^"]*)"', r"'\1'", query)
    return fixed_query
  
def route_query(question: str, llm):
    router_prompt = ChatPromptTemplate.from_template("""
    You are a **query classifier** for questions about candidates' work experience.

    Decide whether the question should be handled by:
    - "SQL" → when the question is about **quantitative or structured experience data** (e.g., number of years, number of companies, duration).
    - "VECTOR" → when the question is about **semantic or descriptive experience details** (e.g., job roles, tasks, company names, technologies used).
    - "HYBRID" → when it combines both structured (numeric) and unstructured (semantic) requirements.

    Rules:
    - Choose **SQL** for phrases like "at least 3 years", "more than 2 companies", "worked for 5 years", "minimum duration".
    - Choose **VECTOR** for phrases like "worked as Data Analyst", "experience in React", "developed AI model", "interned at Shopee".
    - Choose **HYBRID** for mixed queries, e.g. "at least 2 years as Data Engineer", "worked for 3 years using Python".

    Answer with only one word:
    `SQL`, `VECTOR`, or `HYBRID`.

    Question: {question}
    """)

    response = llm.invoke(router_prompt.format(question=question))
    return response.content.strip().upper()


def split_hybrid_query(question: str, llm):
    prompt = ChatPromptTemplate.from_template("""
        You are a query decomposition system.
        Given a user question, split it into 2 sub-questions in natural language:
    - "sql_query": focuses on **structured numeric conditions** about experience (e.g., number of years, number of companies, duration).
    - "vector_query": focuses on **semantic experience content** (e.g., job roles, technologies, responsibilities, company names).

        Output format must be strictly JSON:
        {{"sql_query": "...", "vector_query": "..."}}

        If a part is not needed, return "" for it.

        Example:
        User: "Find candidates who have more than 2 years experince as a Software Engineer and experience developing chatbots"
        Output: {{"sql_query": "Find people who have more than 2 years experince as a Software Engineer", 
                  "vector_query": "Find people who developed chatbots"}}

        Note: Return the output in English.

            Question: {question}
        """)
    response = llm.invoke(prompt.format(question=question))
    return json.loads(response.content)


# def generate_sql(question: str, llm):
#     sql_prompt = ChatPromptTemplate.from_template("""
#         You are a TEXT2SQL system. Your job is to translate user question into a SQL query. 
#         This is your database schema:
#         candidates_info(id, full_name, email, phone, job_title)

#         Question: {question}
#         Return a valid SQL query. You don't have to add ```sql ``` in between the query. 
#         The value should be put in '', not "".
#         """)
#     response = llm.invoke(sql_prompt.format(question=question))
#     return response.content.strip()



def generate_vector_query(question: str, llm, collection_name: str, job_apply:str, limit: int = 10):
    vector_prompt = ChatPromptTemplate.from_template("""
    You are an intelligent query generation system for semantic candidate search.

    You receive a natural language question about candidate **work experience** and must translate it into a JSON-based vector search query for a vector database (like Qdrant).

    The database contains candidate experience information with the following structure:
    Each record (point) has a payload with fields:
    - type: "exp_position" or "exp_description"
    - exp_company: company name (string)
    - exp_job_title: job title (string)
    - exp_description: text describing experience or achievements (string)
    - candidate_name, email, resume_url
    - job_apply: the job they applied for (string)
    - job_title: the current or intended job title

    You should output one or more JSON objects that describe the semantic search query, with this structure:
                                                     
    [
    {{
        "action": "search",
        "collection_name": "<collection name, e.g. 'candidates'>",
        "query_text": "<text to embed for semantic search>",
        "limit": 10,
        "query_filter": {{
        "must": [
            {{ "key": "type", "match": {{ "value": "exp_description" }} }},
            {{ "key": "exp_company", "match": {{ "value": "<company in the experience>" }} }},
            {{ "key": "exp_job_title", "match": {{ "value": "<role or title keyword>" }} }},
            {{ "key": "job_apply", "match": {{ "value": "<specific applied job>" }} }}
        ]
        }}
    }}
    ]
                                                     
    Guidelines:
    - If the question is about **roles or titles**, set `"type": "exp_position"`.
    - If it’s about **tasks, skills, or achievements**, set `"type": "exp_description"`.
    - If both are relevant, output **two or more JSON objects**, for each type.
    - Always infer meaningful filters if the question contains company names, roles, or applied positions.
    - The `"query_text"` should be a concise embedding text that best captures the intent of the search.
    - You also need to filter based on "job_apply" on the "job_apply" key in the metadata.
    - Return only valid JSON (no Markdown formatting, no explanations).

    Example 1:
    User: "Find candidates who have experiences as Software Engineer "
    Output:
    [
    {{
        "action": "search",
        "collection_name": "...",
        "query_text": "Software Engineer",
        "limit": 10,
        "query_filter": {{
        "must": [
            {{ "key": "type", "match": {{ "value": "exp_position" }} }},
            {{ "key": "job_apply", "match": {{ "value": "{job_apply}" }},                                      
        }}
        ]
        }}
    }}
    ]
                                                     
    Example 2:
    User: "Find candidates who worked as Data Scientist at Shopee"
    Output:
    [
    {{
        "action": "search",
        "collection_name": "...",
        "query_text": "Data Scientist at Shopee",
        "limit": 10,
        "query_filter": {{
        "must": [
            {{ "key": "type", "match": {{ "value": "exp_position" }} }},
            {{ "key": "exp_company", "match": {{ "value": "Shopee" }} }},
            {{ "key": "job_apply", "match": {{ "value": "{job_apply}" }},  
        }}
        ]
        }}
    }}
    ]

    Example 3:
    User: "Find people who developed web applications using React"
    Output:
    [
    {{
        "action": "search",
        "collection_name": "...",
        "query_text": "developed web applications using React",
        "limit": 10,
        "query_filter": {{
        "must": [
            {{ "key": "type", "match": {{ "value": "exp_description" }} }},
            {{ "key": "job_apply", "match": {{ "value": "{job_apply}" }},  
        ]
        }}
    }}
    ]


    Now generate the JSON query for:
    Question: {question}
    collection_name: {collection_name}
    job_apply: {job_apply}
    limit: {limit}
    """)

    response = llm.invoke(vector_prompt.format(
        question=question,
        collection_name=collection_name,
        limit=limit
    ))
    
    # Làm sạch output
    cleaned = re.sub(r"^```json\s*|\s*```$", "", response.content.strip())
    return cleaned.strip()


def build_filter(filter_json: dict):
    """
    Convert filter JSON (must, should, must_not) into Qdrant Filter object
    """
    if not filter_json:
        return None

    must_conditions, should_conditions, must_not_conditions = [], [], []

    for cond in filter_json.get("must", []):
        if "key" in cond and "match" in cond:
            must_conditions.append(
                FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
            )
    for cond in filter_json.get("should", []):
        if "key" in cond and "match" in cond:
            should_conditions.append(
                FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
            )
    for cond in filter_json.get("must_not", []):
        if "key" in cond and "match" in cond:
            must_not_conditions.append(
                FieldCondition(key=cond["key"], match=MatchValue(value=cond["match"]["value"]))
            )

    return Filter(
        must=must_conditions or None,
        should=should_conditions or None,
        must_not=must_not_conditions or None
    )


def execute_vector_query(plan, client: QdrantClient, embedding_model, limit=None, search_threshold=0.75):
    if isinstance(plan, list):  # nhiều query cần chạy rồi join
        results_per_query = []
        for subplan in plan:
            results = execute_vector_query(subplan, client, embedding_model, 30, search_threshold)
            results_per_query.append(results)
        
        # join theo candidate_name (chỉ giữ những người có mặt ở tất cả queries)
        sets = [set([r["payload"]["candidate_name"] for r in res if "payload" in r]) for res in results_per_query]
        common_candidates = set.intersection(*sets)
        
        # gom full payload theo candidate
        final = []
        for res in results_per_query:
            for r in res:
                if r["payload"]["candidate_name"] in common_candidates:
                    final.append(r)
        return final
    
    # -------- trường hợp chỉ 1 query như cũ ----------
    action = plan["action"]
    collection_name = plan["collection_name"]
    limit = limit or plan.get("limit", 10)
    scroll_limit = 30
    if action == "scroll":
        qdrant_filter = build_filter(plan.get("scroll_filter", {}))
        points, _ = client.scroll(
            collection_name=collection_name,
            limit=scroll_limit,
            scroll_filter=qdrant_filter
        )
        return [p.payload for p in points]

    elif action == "search":
        qdrant_filter = build_filter(plan.get("query_filter", {}))  # chú ý đổi thành query_filter
        query_text = plan["query_text"]
        query_vector  = embedding_model.embed_query(query_text) 

        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            score_threshold=search_threshold,
            limit=limit,
            query_filter=qdrant_filter
        )
        return [{"payload": r.payload, "score": r.score} for r in results]

    else:
        raise ValueError(f"Unknown action type: {action}")


def format_rag_output(results):
    columns = ["name", "email", "resume_url"]
    rows = []
    for r in results:
        payload = r.get("payload", r)
        row = [
            payload.get("candidate_name"),
            payload.get("email"),
            payload.get("resume_url"),
        ]
        rows.append(row)
    return {"columns": columns, "rows": rows}

def search_vector(query: str, job_apply:str, llm, embedding_model, qdrant_db, collection, limit=30, search_threshold=0.72):
    output = generate_vector_query(query, llm, collection, job_apply, limit)
    plan = json.loads(output)
    print("Generated vector query plan:", plan)
    results = execute_vector_query(plan, qdrant_db, embedding_model, search_threshold=search_threshold)
    # print("Raw results:", results)
    formatted = format_rag_output(results)
    return formatted, plan
