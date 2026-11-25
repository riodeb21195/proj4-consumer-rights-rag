# API + pipeline image (also used for ingest CLI, evaluation and demo scripts).
FROM ghcr.io/astral-sh/uv:0.13.10 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ml --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ml --no-editable

FROM python:3.12-slim
# Same UID as the Airflow image so both can share the model cache volume.
RUN useradd --create-home --uid 50000 rag && mkdir /hf-cache && chown rag /hf-cache
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY db ./db
ENV PATH=/opt/venv/bin:$PATH HF_HOME=/hf-cache PYTHONUNBUFFERED=1
USER rag
EXPOSE 8000
CMD ["uvicorn", "rag.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
