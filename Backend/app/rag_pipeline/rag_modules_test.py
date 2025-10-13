from langchain.prompts import ChatPromptTemplate
from qdrant_client.models import Filter, FieldCondition, MatchValue
from qdrant_client import QdrantClient
from unidecode import unidecode
import json
import re


def fix_sql_quotes(query: str) -> str:
    fixed_query = re.sub(r'"([^"]*)"', r"'\1'", query)
    return fixed_query
  
# ------------------ Router Agent ------------------
router_prompt = ChatPromptTemplate.from_template("""
    You are a query router for a candidate search system.

    Classify the question into one of these categories:
    - "SQL": if it asks about structured fields (name, degree, job title, applied position, university, gpa, certifications, languages, etc.)
    - "VECTOR": if it asks about skills, technologies, past experiences, or project descriptions.
    - "HYBRID": if it requires both structured data and unstructured (skills/experience) data.
    - "SQL": also choose SQL if the question involves numeric or logical reasoning over structured data, mainly about past experience (e.g., "at least 3 years as Software Engineer", "worked at at least 2 companies").

    Question: {question}

    Answer ONLY with one label: SQL, VECTOR, or HYBRID.
    """)




# ------------------ Evaluator Agent ------------------
evaluator_prompt = ChatPromptTemplate.from_template("""
    You are an evaluation agent checking the routing decision.

    Rules for correctness:
    1. VECTOR if about skills, past work experience, or projects.
    2. SQL if about other structured fields (name, degree, language, university, gpa, certifications, current job title, applied position for this company,  etc.)
    3. SQL if numeric reasoning about experience (e.g. "at least 3 years", "worked in 2 companies")
    4. HYBRID if question mixes structured + unstructured requirements.

    Question: {question}
    Router Decision: {decision}

    Evaluate whether the decision follows these rules.
    Respond in JSON format:
    {{
    "evaluation": "CORRECT" or "INCORRECT",
    "reason": "<brief explanation>"
    }}
    """)


def split_hybrid_query(question: str, llm):
    prompt = ChatPromptTemplate.from_template("""
        You are a query decomposition system.
        Given a user question, split it into 2 sub-questions in natural language:
        - "sql_query": a natural language sub-question about structured fields 
          (full_name, email, phone, job_title, certifications, languages, degree, education (university...)
          numeric filters like 'at least 2 companies', 'more than 3 years', etc.)
        - "vector_query": a natural language sub-question about unstructured fields 
          (skills, experience descriptions, project details).

        Output format must be strictly JSON:
        {{"sql_query": "...", "vector_query": "..."}}

        If a part is not needed, return "" for it.

        Example:
        User: "Find candidates who are Software Engineers and know Python"
        Output: {{"sql_query": "Find people who is Software Engineer", 
                  "vector_query": "Find people who know Python"}}

        Note: Return the output in English.

            Question: {question}
        """)
    response = llm.invoke(prompt.format(question=question))
    return json.loads(response.content)


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



def generate_vector_query(question: str, llm, collection_name, limit):
    vector_prompt = ChatPromptTemplate.from_template("""
        You are a TEXT2VECTORQUERY system.
        Translate user questions into valid Qdrant queries in JSON format.
        Use one of two actions: "search" or "scroll".
        ALWAYS RETURN RAW JSON (a single JSON object OR an array of JSON objects) — NO EXPLANATION.

        Collection: {collection_name}
        Default limit: {limit}

        Types available in the collection:
          - "skill"            -> skill vectors
          - "exp_position"     -> vectors built from "Job Title + Company"
          - "exp_description"  -> vectors built from description text
        Payload fields useful for filtering:
          - "candidate_name"
          - "exp_company"      (company name stored in description/position payload)
          - "exp_job_title"
          - "type"             (one of the types above)

        RULES (use these to choose action/type/filter):

        1) Specific candidate attribute requests:
           - If the question asks about a particular candidate (e.g. "What did X do?", "Show Mohamad El Ghali's descriptions"),
             use "scroll" with scroll_filter containing candidate_name and optionally type.
           - Example: 
            {{
            "action": "scroll", "collection_name": "candidates", "limit": 50, "scroll_filter": 
            {{"must":[{{"key":"candidate_name","match":{{"value":"Mohamad El Ghali"}}}}, 
                    {{"key":"type","match":{{"value":"exp_description"}}}}]}}
            }}

        2) Skill queries:
           - If the question asks to find candidates by skill (e.g. "who knows Python?"),
             use "search" with query_text equal to the skill phrase and query_filter where type="skill".
           - Example: 
            {{
            "action":"search","collection_name":"...","query_text":"Python","limit":10,"query_filter":
                {{"must":[{{"key":"type","match":{{"value":"skill"}}}}]}}
            }}


        3) Experience queries (company or job title only):
           - If the question focuses on company or job title only (e.g. "worked at Google", "was Software Engineer"),
             use "search" with type="exp_position" (semantic on job+company).
           - Example:
            {{
            "action":"search","collection_name":"...","query_text":"worked at Google","limit":10,"query_filter":
            {{"must":[{{"key":"type","match":{{"value":"exp_position"}}}}]}}
            }}

                                                     
        4) Experience description queries (what they did / technologies / responsibilities):
           - If the question asks about what they did in a role (e.g. "microservices", "built CI/CD"),
             use "search" with type="exp_description" and query_text describing the task/tech.
           - Example: 
            {{
            "action":"search","collection_name":"...","query_text":"microservices","limit":10,"query_filter":
            {{"must":[{{"key":"type","match":{{"value":"exp_description"}}}}]}}
            }}
                                
        5) EXPERIENCE + COMPANY (must be true in the SAME experience) — IMPORTANT:
           - If the user requires that the description match AND the company be the same experience
             (phrases like "Data Scientist at Google", "built microservices at Amazon"),
             produce **a single "search"** on type="exp_description" with:
               - query_text = the part about role/task (e.g. "Data Scientist", "microservices")
               - query_filter MUST include type="exp_description" AND exp_company match the company value.
           - This ensures the description match is constrained to experiences at that company.
           - Example: 
            {{
            "action":"search","collection_name":"...","query_text":"Data Scientist","limit":10,"query_filter":
            {{"must":[{{"key":"type","match":{{"value":"exp_description"}}}},{{"key":"exp_company","match":{{"value":"Google"}}}}]}}
            }}
        
        6) COMBINED CONDITIONS (INDEPENDENT) — return an ARRAY of queries:
           - If the question requests independent conditions that can be satisfied by different experiences
             and you will later intersect candidates (e.g. "candidates with Python skill and worked at Google"),
             return an array of queries, one per atomic condition (skill OR exp_position OR exp_description).
           - For multiple companies (e.g. "worked at Google and Amazon"), return separate exp_position queries for each company.
           - NEVER mix different types inside the same query_filter; use separate queries instead.
           - Example array:
             [
               {{"action":"search","collection_name":"...","query_text":"Python","limit":10,"query_filter":{{"must":[{{"key":"type","match":{{"value":"skill"}}}}]}}}},
               {{"action":"search","collection_name":"...","query_text":"Google","limit":10,"query_filter":{{"must":[{{"key":"type","match":{{"value":"exp_position"}}}}]}}}}
             ]

        7) AMBIGUOUS COMPANY NAMES:
           - If the question contains a company name, use that literal string as exp_company in the filter.
           - If the company in the question is ambiguous or not explicit, DO NOT invent a company filter — instead prefer exp_position semantic search.

        8) FORMATTING / OUTPUT:
           - For "search" queries include: action, collection_name, query_text, limit, query_filter (must: list of field-match objects).
           - For "scroll" queries include: action, collection_name, limit, scroll_filter.
           - Use the payload keys exactly: "type", "exp_company", "candidate_name", ...
           - Output only JSON (object or array). No markdown, no commentary.

        collection_name: {collection_name}
        limit: {limit}

        Question: {question}
        Output: JSON object OR array of JSON objects
    """)
    response = llm.invoke(vector_prompt.format(question=question, collection_name=collection_name, limit=limit))
    response = response.content.strip()
    cleaned = re.sub(r"^```json\\s*|\\s*```$", "", response.strip())
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
    columns = ["id", "email", "resume_url"]
    rows = []
    for r in results:
        payload = r.get("payload", r)
        row = [
            payload.get("id"),
            payload.get("email"),
            payload.get("resume_url"),
        ]
        rows.append(row)
    return {"columns": columns, "rows": rows}

def search_vector(query: str, llm, embedding_model, qdrant_db, collection, limit=30, search_threshold=0.72):
    output = generate_vector_query(query, llm, collection, limit)
    plan = json.loads(output)
    results = execute_vector_query(plan, qdrant_db, embedding_model, search_threshold=search_threshold)
    print("Raw results:", results)
    formatted = format_rag_output(results)
    return formatted, plan
