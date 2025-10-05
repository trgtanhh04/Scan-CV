import os
from dotenv import load_dotenv
load_dotenv()

DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
LOGS_DATABASE_URL = os.getenv('LOGS_DATABASE_URL', 'sqlite:///./logs.db')
DRIVE_API_KEY = os.getenv("DRIVE_API_KEY", "")