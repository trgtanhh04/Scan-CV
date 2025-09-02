import os
from dotenv import load_dotenv
load_dotenv()

MONGO_URL = os.getenv('MONGO_URL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "models/gemini-embedding-exp-03-07")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "candidates")

GCS_BUCKET = os.getenv("GCS_BUCKET")
GCS_MAKE_PUBLIC = os.getenv("GCS_MAKE_PUBLIC", "false").lower() == "true"
GCS_PUBLIC_BASE = os.getenv("GCS_PUBLIC_BASE", "https://storage.googleapis.com").rstrip("/")
GCS_SIGNED_URL_EXPIRES = int(os.getenv("GCS_SIGNED_URL_EXPIRES", "604800"))

GCP_PROJECT = os.getenv("GCP_PROJECT", "interns-2025-467409")
GCP_REGION = os.getenv("GCP_REGION", "asia-southeast1")
GCP_RUN_SA = os.getenv("GCP_RUN_SA", "cv-uploader@interns-2025-467409.iam.gserviceaccount.com")