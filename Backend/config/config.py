import os
from dotenv import load_dotenv
load_dotenv()

MONGO_URL = os.getenv('MONGO_URL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
print(MONGO_URL)
print(OPENAI_API_KEY)