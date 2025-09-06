import os
from translate import Translator
import re
from difflib import get_close_matches
from langchain_deepseek import ChatDeepSeek
from config import DEEPSEEK_API_KEY

deepseek = ChatDeepSeek(model="deepseek-chat", api_key=DEEPSEEK_API_KEY)

#============= HELPERS =============

# Convert job description to English if needed
def translate_to_english(query):
    translator = Translator(to_lang="en", from_lang="vi")
    return translator.translate(query)

# Fine-tune job description to a precise search query
def convert_job_to_question(job_description):
    search_query_prompt = f"""
        You are an assistant that converts job descriptions into precise search queries for finding candidates.
        - For simple queries like "Find candidates that know Python", keep them as is.
        - For complex job descriptions, convert them into a clear search query highlighting skills, experience, and job-specific keywords.
        - Output the result in English, question only, no explanations.

        Examples:
        Input: "Find candidates that know Python."
        Output: "Find candidates that know Python."

        Input: "Find candidates that know Java."
        Output: "Find candidates that know Java."

        Input: "5+ years as a Fullstack Engineer, AI Specialist, or similar, with a strong track record of deploying scalable, AI-integrated applications."
        Output: "Find candidates with 5+ years of fullstack engineer or AI specialist experience and a proven track record of deploying scalable, AI-integrated applications."

        Input: "Tìm ứng viên có kinh nghiệm 5 năm trong lĩnh vực data engineer, biết python và java, và có GPA xuất sắc."
        Output: "Find candidates with 5 years of experience in data engineer, knowledge of Python and Java, and an excellent GPA."
    """
    response = deepseek.invoke(search_query_prompt + f"\nInput: '{job_description}'\nOutput:")
    return response.content.strip()

# Decision to fine-tune or not based on clarity/complexity of job description
def needs_finetune(job_description: str) -> bool:
    """
    Quyết định có cần fine-tune hay không dựa trên độ rõ ràng / độ phức tạp của job description.
    """
    job_description_lower = job_description.lower()

    simple_keywords = [
        "python", "java", "javascript", "typescript", "c++", "c#", "ruby", "go", "php",
        "react", "angular", "vue", "node.js", "django", "flask", "spring", "express",
        "sql", "nosql", "excel", "python scripting", "html", "css", "rest api", 'software',
        "developer", "engineer", "data", "database", "cloud", "aws", "azure", "gcp",
    ]
    simple_count = sum(kw in job_description_lower for kw in simple_keywords)
    
    complex_keywords = [
        "deploy", "scalable", "ai", "artificial intelligence",
        "machine learning", "deep learning", "fullstack", "devops", "cloud",
        "kubernetes", "lead", "architect", "microservices", "ci/cd", "production", "production-ready", "distributed systems",
        "team management", "project management"
    ]

    is_complex = len(job_description.split()) > 12 or any(x in job_description_lower for x in complex_keywords)

    if simple_count <= 2 and not is_complex:
        return False

    return True

# Validate if query is suitable for candidate search
def validate_candidate_query(query: str, cutoff: float = 0.8) -> bool:
    """
    Kiểm tra xem câu truy vấn có hợp lệ để tìm ứng viên hay không.
    - Loại bỏ spam / câu vô nghĩa
    - Check từ khóa hợp lệ (có fuzzy matching để xử lý typo)
    - Cho qua câu chứa các động từ tìm kiếm phổ biến ("find", "search", "know")
    """
    query_lower = query.lower()

    valid_keywords = [
        "skills", "skill", "experience", "cv", "resume", "candidate", "email",
        "database", "knowledge", "years of experience", "project", "role", "position",
        "tech", "technology", "programming", "python", "java", "javascript",
        "sql", "nosql", "aws", "cloud", "deployment", "machine learning", "ai", "fullstack",
        "data engineer", "software", "development", "teamwork", "communication", "leadership",
        'chatbot', 'llm', 'gpt', 'deepseek', 'openai', 'langchain', 'university', 'degree', 'education', 'certification',
        'location', 'language', 'vietnamese', 'english', 'japanese', 'role', 'company', 'work', 'worked', 'working',
    ]

    invalid_patterns = [
        r"^[\W_]+$",                 
        r"^\s*$",                   
        r"\b(?:haha|hehe|hihi|hahaha|hoho|lmao|lol)\b", 
        r"\b(?:beauty|travel|vacation|holiday|shopping|love|friendship|handsome|happy|xinh đẹp)\b" 
    ]

    if any(re.search(pattern, query_lower) for pattern in invalid_patterns):
        return False

    words = re.findall(r'\w+', query_lower)
    for kw in valid_keywords:
        if kw.lower() in words:
            return True
        if get_close_matches(kw.lower(), words, cutoff=cutoff):
            return True

    if any(re.search(pattern, query_lower) for pattern in ["find", "search", "know", "list"]):
        return True

    return False