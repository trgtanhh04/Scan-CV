import pandas as pd
import fitz
import os
import json
import re
from langchain.schema import HumanMessage
from langchain.schema import Document
from langchain_deepseek import ChatDeepSeek
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config.config import DEEPSEEK_API_KEY

llm = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

def extract_text_from_pdf(file_path: str) -> str:
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text.strip()

def extract_info(text: str, llm) -> dict:
    prompt_template = """
    Extract the following candidate information fields from the CV content (as plain text) below in the exact JSON format:
    {{
    "full_name": "...",
    "email": "...",
    "phone": "...",
    "job_title": "...",
    "education": [
        {{
        "degree": "...",
        "university": "...",
        "start_year": ...,
        "end_year": ...
        }}
    ],
    "experience": [
        {{
        "job_title": "...",
        "company": "...",
        "start_date": "...",
        "end_date": "...",
        "description": "..."
        }}
    ],

    "skills": ["...", "..."],
    "certifications": [
        {{
        "certificate_name": "...",
        "organization": "..."
        }}
    ],
    "languages": ["...", "..."]
    }}

    Only include **real work experience** (e.g. internships, jobs at companies, freelance work) in the "experience" field.  
    **Do not include personal, academic, or side projects** in the experience section.

    Only return the JSON content. Do not include any explanation.  
    If any field cannot be found, set it to null or empty array.

    CV content:
    {text}
    """
    prompt = prompt_template.format(text=text)
    messages = [HumanMessage(content=prompt)]
    response = llm.invoke(messages)
    raw_content = response.content

    
    cleaned_data = re.sub(r"^```json\s*|\s*```$", "", raw_content.strip(), flags=re.MULTILINE)
    # candidate_info = json.loads(response.content)
    
    try:
        candidate_info = json.loads(cleaned_data)

        # Lọc experience: bỏ các mục có company = None hoặc ""
        if "experience" in candidate_info and isinstance(candidate_info["experience"], list):
            filtered_exp = []
            for exp in candidate_info["experience"]:
                company = exp.get("company")
                if company not in [None, ""]:
                    filtered_exp.append(exp)
            candidate_info["experience"] = filtered_exp

    except Exception as e:
        print(f"Error parsing JSON: {e}\nLLM output: {cleaned_data}")
        candidate_info = {}
    return candidate_info

def process_cvs(input_dir: str, output_file: str, limit: int = 10):
    results = []

    # Lấy danh sách file pdf 
    pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]
    pdf_files = pdf_files[:limit]

    for filename in pdf_files:
        file_path = os.path.join(input_dir, filename)
        print(f"Processing {file_path}...")

        # trích xuất text từ PDF
        text = extract_text_from_pdf(file_path)

    # trích xuất thông tin từ LLM
    info = extract_info(text, llm)

        # Thêm tên file để dễ đối chiếu
    info["source_file"] = filename
    results.append(info)

    # B3: lưu kết quả thành JSON (list of objects)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    print(f"Saved {len(results)} CVs into {output_file}")


if __name__ == "__main__":
    input_directory = "../../raw/cvs/01.pdf"
    text = extract_text_from_pdf(input_directory)
    info = extract_info(text, llm)
    print(info)
    output_json = "extracted_candidates.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=4)