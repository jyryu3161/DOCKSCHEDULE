FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libxrender1 libxext6 tini && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.9.7
# GNINA's CUDA 12.8 static build still loads cuDNN 9 and CUDA runtime libraries at startup, even for CPU-only runs.
# They are installed outside the app venv (not in pyproject/uv.lock) and registered with ldconfig. No GPU is used.
RUN pip install --no-cache-dir --target /opt/gnina-libs nvidia-cudnn-cu12==9.10.2.21 nvidia-cuda-runtime-cu12==12.8.90 nvidia-cublas-cu12==12.8.4.1 nvidia-cufft-cu12==11.3.3.83 nvidia-cusparse-cu12==12.5.8.93 nvidia-cusolver-cu12==11.7.3.90 nvidia-nvjitlink-cu12==12.8.93 \
    && ls -d /opt/gnina-libs/nvidia/*/lib > /etc/ld.so.conf.d/gnina-cuda.conf && ldconfig
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
RUN uv sync --frozen --no-dev
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts/download-qvina.py ./scripts/download-qvina.py
RUN .venv/bin/python scripts/download-qvina.py /app/tools/qvina2.1
COPY scripts/download-gnina.py ./scripts/download-gnina.py
RUN .venv/bin/python scripts/download-gnina.py /app/tools/gnina
COPY scripts ./scripts
COPY third_party ./third_party
ENV PATH="/app/.venv/bin:$PATH" STORAGE_ROOT=/app/storage QVINA_BINARY=/app/tools/qvina2.1 GNINA_BINARY=/app/tools/gnina CUDA_VISIBLE_DEVICES= PYTHONUNBUFFERED=1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "dockschedule.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
