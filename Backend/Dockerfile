
# FROM python:3.10-slim AS base

# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     PIP_NO_CACHE_DIR=1

# # System deps (psycopg2, OCR, build)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     gcc \
#     libpq-dev \
#     tesseract-ocr \
#     tesseract-ocr-vie \
#     libtesseract-dev \
#     libleptonica-dev \
#     && rm -rf /var/lib/apt/lists/*

# # (Tuỳ code) Nếu dùng OpenCV hoặc pdf → bật thêm:
# # RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libsm6 libxrender1 libxext6 poppler-utils && rm -rf /var/lib/apt/lists/*

# WORKDIR /app

# # Cài deps trước để tận dụng cache
# # When docker-compose sets build context to ./Backend, the files are available at root of context
# COPY requirements.txt /app/requirements.txt
# RUN python -m pip install --upgrade pip && \
#     pip install -r requirements.txt

# # Copy code from build context into image
# COPY . /app/

# # Không chạy bằng root
# RUN useradd -m appuser && chown -R appuser:appuser /app
# USER appuser

# # Port & health (cloud thường đọc PORT)
# ENV PORT=8000
# EXPOSE 8000

# # Tesseract data path (nếu cần tuỳ chỉnh)
# # ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

# # Command để compose override cho gọn
# CMD ["bash", "-lc", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT}"]
# -------------
# FROM python:3.10-slim AS base
# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     PIP_NO_CACHE_DIR=1

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential gcc libpq-dev tesseract-ocr tesseract-ocr-vie libtesseract-dev libleptonica-dev \
#     && rm -rf /var/lib/apt/lists/*

# WORKDIR /app
# COPY requirements.txt /app/requirements.txt
# RUN python -m pip install --upgrade pip && pip install -r requirements.txt
# COPY . /app/

# RUN useradd -m appuser && chown -R appuser:appuser /app
# USER appuser

# # Cloud Run sẽ cấp PORT=8080; để mặc định là 8080 cho rõ ràng
# ENV PORT=8080
# EXPOSE 8080

# # Dùng shell form để chắc chắn expand biến môi trường PORT
# CMD ["sh","-c","uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

# -------------
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev \
    tesseract-ocr tesseract-ocr-vie libtesseract-dev libleptonica-dev \
    && rm -rf /var/lib/apt/lists/*

# Làm việc trong chính layer code BE
WORKDIR /app

# vì Dockerfile nằm trong Backend/, context = Backend/
# nên chỉ cần tên file, KHÔNG có tiền tố Backend/
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

# copy toàn bộ code của Backend/ vào /app
COPY . .

# Không chạy root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Cho FastAPI/uvicorn
ENV PORT=8080 \
    PYTHONPATH=/app
EXPOSE 8080

CMD ["sh","-c","uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --lifespan off"]
