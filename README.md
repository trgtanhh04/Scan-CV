# Scan CV: Intelligent CV Analysis and Candidate Database System

## Overview
Scan CV is an AI-powered system for automated CV parsing, information extraction, and candidate database construction. It streamlines the recruitment process by enabling semantic search, QA and efficient candidate filtering.

## Project structure

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
