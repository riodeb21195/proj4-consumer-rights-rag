# Airflow with the RAG package in a separate virtualenv: the pipeline's dependencies
# (torch, sentence-transformers, its own FastAPI) never mix with Airflow's pinned ones.
FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM apache/airflow:3.4.0-python3.12
COPY --from=uv /uv /usr/local/bin/uv
USER root
RUN mkdir -p /opt/rag-venv /hf-cache && chown airflow /opt/rag-venv /hf-cache
USER airflow
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python UV_PROJECT_ENVIRONMENT=/opt/rag-venv \
    UV_CACHE_DIR=/tmp/uv-cache HF_HOME=/hf-cache
WORKDIR /opt/rag-src
COPY --chown=airflow pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra ml --no-install-project && rm -rf /tmp/uv-cache
COPY --chown=airflow src ./src
RUN uv sync --frozen --no-dev --extra ml --no-editable && rm -rf /tmp/uv-cache
COPY --chown=airflow db /opt/rag-src/db
WORKDIR /opt/airflow
