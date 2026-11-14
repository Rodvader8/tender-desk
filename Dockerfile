# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
# Bake the embedding model into the image so the container never downloads anything at start-up.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN /app/.venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home app && mkdir /data && chown app /data
COPY --from=build /app/.venv /app/.venv
COPY --from=build /opt/fastembed /opt/fastembed
COPY scripts /app/scripts
ENV PATH=/app/.venv/bin:$PATH FASTEMBED_CACHE_PATH=/opt/fastembed PYTHONUNBUFFERED=1 TENDER_DESK_LEDGER=/data/ledger.jsonl
WORKDIR /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "tender_desk.api:build_default_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
