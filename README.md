# Scan CV: Intelligent CV Analysis and Candidate Database System

## Overview
Scan CV is an AI-powered system for automated CV parsing, information extraction, and candidate database construction. It streamlines the recruitment process by enabling semantic search, QA and efficient candidate filtering.

---

## Project structure

---

## Workflow
<p align="center">
  <img src="https://raw.githubusercontent.com/trgtanhh04/Scan-CV/main/Images/workflow.png" width="100%" alt="Workflow">
</p>

### 1. CV Upload & Processing

- **POST /cv/upload (multipart):**  
  The user uploads PDF CV files via a FastAPI endpoint.
- **Extract Text:**  
  The system extracts raw text from each PDF CV.
- **LLM Parse to JSON:**  
  The extracted text is parsed using a Large Language Model (LLM), which outputs structured candidate data in JSON format.
- **Storage & Embedding:**  
  The structured JSON data is stored in PostgreSQL for relational queries, and simultaneously embedded into a vector database (Qdrant) for semantic search.

### 2. Candidate Search & Query

- **GET /search:**  
  Users submit queries to search candidate information.
- **Query Preprocessing:**  
  The incoming query is preprocessed (normalization, classification, etc.).
- **Judge:**  
  The system judges the type of query—whether it can be answered via structured SQL search or requires semantic vector search.
- **Router (Adaptive):**  
  - If the query is suitable for SQL:
    - **Text→SQL (with schema/examples):** The query is converted to SQL.
    - **SQL Guard:** Ensures only safe SELECT queries with LIMIT are executed.
    - **PostgreSQL:** The query is run against the relational database.
  - If the query requires semantic search:
    - **Query Rewrite/Expand:** The query is expanded or rewritten for semantic search.
    - **Embed:** Query is vectorized and sent to Qdrant.
    - **Qdrant:** Retrieves relevant candidate profiles and reranks the results.
- **Generation:**  
  Results from either branch are processed for output.
- **Judge:**  
  The system evaluates the generated results for accuracy and relevance.
- **Response:**  
  The final response is returned to the user.

- **Advanced:**  
  For complex queries, a query transformation/decomposition module may break down the query into manageable parts for multi-step generation.

---

## Text2Sql
<p align="center">
  <img src="https://raw.githubusercontent.com/trgtanhh04/Scan-CV/main/Images/text2Sql_pipeline.png" width="100%" alt="Workflow">
</p>

### 1. Selector

- **Input Query Parsing:**  
  The selector processes the incoming query using regex to identify relevant entities (skills, experience, education, language, certification, location, etc.).
- **Table Set Identification:**  
  Based on detected entities, it determines the set of database tables involved.
- **Hints Extraction:**  
  Generates hints (e.g., DISTINCT, EXISTS) to guide the SQL generation.

### 2. Introspection

- **Schema Loading:**  
  Loads schema information from the database engine.
- **Schema Summarization:**  
  Summarizes schema, mapping tables to their structure.
- **Schema Rendering:**  
  Renders the processed schema as text for prompt building.

### 3. Prompting

- **Prompt Construction:**  
  Builds a prompt for the LLM using:
  - Rendered schema text
  - Hints
  - User query
  - 2–3 example queries for guidance
- **LLM Generation:**  
  The LLM generates a candidate SQL query based on the prompt.

### 4. Safety

- **SQL Guard:**  
  Ensures only safe SQL statements are executed (SELECT only; forbids DDL/DML).

### 5. Post-Processing

- **SQL Parsing:**  
  Parses the generated SQL for rule checks.
  - Ensures proper use of JOINs, no improper GROUP BY or COUNT.
  - Applies SELECT DISTINCT or custom rules for candidate queries (e.g., ORDER BY candidate ID, start date DESC).
- **Prettify:**  
  Formats the SQL output for readability.

### 6. Execution

- **SQL Execution:**  
  Runs the generated SQL against the database engine.
- **Result Handling:**  
  - On success: Returns columns, rows, and formatted SQL.
  - On error or empty results: Invokes a refinement loop.

### 7. Refinement Loop

- **Error Handling & Retry:**  
  If the SQL fails or returns no results, the system refines the prompt using previous SQL attempts and error reasons, and retries the LLM generation.
