FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
# Only the UI dependency group: the UI talks to the API over HTTP and needs no ML stack.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --only-group ui

FROM python:3.12-slim
RUN useradd --create-home --uid 50000 rag
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv
COPY app ./app
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
USER rag
EXPOSE 8501
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
