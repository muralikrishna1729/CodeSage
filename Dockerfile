# Python 3.13 is required: tree-sitter==0.25.0 has no prebuilt wheel for 3.14,
# and the 0.26.x fallback native-crashes with the 0.25.x grammar packages
# during AST chunking (see README version note).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# git is required by GitPython when /ingest clones repos
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the CPU-only torch wheel first (much smaller than the default CUDA
# build); the unpinned `torch` line in requirements.txt then resolves as satisfied.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

# Bake the embedding model into the image so the first /ingest works even
# without Hugging Face access at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('jinaai/jina-embeddings-v2-base-code', trust_remote_code=True, cache_folder='/app/app/ingestion/.model_cache')"

EXPOSE 8010 8501

# Default target is the backend; docker-compose.prod.yml overrides the command
# for the frontend container.
CMD ["uvicorn", "app.api.routes:app", "--host", "0.0.0.0", "--port", "8010"]