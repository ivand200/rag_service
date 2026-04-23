FROM ghcr.io/astral-sh/uv:python3.12-bookworm

WORKDIR /app

ENV UV_HTTP_TIMEOUT=120
ENV UV_HTTP_RETRIES=5

COPY backend /app
RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
