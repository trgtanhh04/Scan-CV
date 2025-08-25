# =========================
# 6) Plug DeepSeek + run
# =========================
from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek
from llm_adapter import LLM
import os
from pipeline import answer_sql
from sqlalchemy import create_engine, text as sa_text
import sys
import dotenv

sys.path.append(os.path.abspath('../../'))
from config.config import DEEPSEEK_API_KEY, DATABASE_URL


if __name__ == "__main__":

    # 1) Postgres engine
    engine = create_engine(DATABASE_URL, future=True)

    # 2) DeepSeek client (LangChain)
    deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

    def _invoke(prompt: str) -> str:
        resp = deepseek.invoke([HumanMessage(content=prompt)])
        return resp.content

    llm = LLM(_invoke) 

    # 3) Hỏi thử
    q = "List candidates with the job title 'Software Engineer'."
    result = answer_sql(engine, llm, q, max_refine=1)
    print("SQL:\n", result["sql"])
    print("Columns:", result["columns"])
    print("Results:", result["rows"])
    print("Trials:", result["trials"])
