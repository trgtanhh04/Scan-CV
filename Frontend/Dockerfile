FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cài deps trước để cache
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy code
COPY . /app/

# Không chạy root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=8501
EXPOSE 8501

# Streamlit headless chuẩn cloud
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

CMD ["bash", "-lc", "streamlit run admin/main.py --server.port ${PORT} --server.address 0.0.0.0"]
