
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

# WORKDIR /app


# COPY requirements.txt /app/requirements.txt
# RUN python -m pip install --upgrade pip && \
#     pip install -r requirements.txt

# COPY . /app/

# RUN useradd -m appuser && chown -R appuser:appuser /app
# USER appuser

# ENV PORT=8000
# EXPOSE 8000

# CMD ["bash", "-lc", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT}"]

# ---------------------------------
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev \
    tesseract-ocr tesseract-ocr-vie libtesseract-dev libleptonica-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser


ENV PORT=8080 \
    PYTHONPATH=/app
EXPOSE 8080

CMD ["sh","-c","uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --lifespan off"]
