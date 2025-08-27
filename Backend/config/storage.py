import os
from pathlib import Path

# Có thể set qua biến môi trường:
#   MEDIA_ROOT=E:/CV-MEDIA
#   PUBLIC_BASE_URL=http://localhost:8000
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "./CV-MEDIA")).resolve()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

# Subfolder chứa CV
CV_DIR = MEDIA_ROOT / "cv"
CV_DIR.mkdir(parents=True, exist_ok=True)

def build_public_url(rel_path: str) -> str:
    """http://localhost:8000/media/<rel_path>"""
    return f"{PUBLIC_BASE_URL.rstrip('/')}/media/{rel_path.lstrip('/')}"