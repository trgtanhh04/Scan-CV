import os
from dotenv import load_dotenv
load_dotenv()

MONGO_URL = os.getenv('MONGO_URL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "mistral-embed")
# print(MONGO_URL)
# print(OPENAI_API_KEY)