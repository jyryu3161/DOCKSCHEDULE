FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libxrender1 libxext6 tini && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.9.7
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
RUN uv sync --frozen --no-dev
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts/download-qvina.py ./scripts/download-qvina.py
RUN .venv/bin/python scripts/download-qvina.py /app/tools/qvina2.1
COPY scripts ./scripts
COPY third_party ./third_party
ENV PATH="/app/.venv/bin:$PATH" STORAGE_ROOT=/app/storage QVINA_BINARY=/app/tools/qvina2.1 PYTHONUNBUFFERED=1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "dockschedule.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
