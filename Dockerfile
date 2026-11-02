# Kavach server for a cloud host (Render, Railway, Fly.io, any VM). Keys come from environment variables, never the image.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv/kavach
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY web ./web
COPY eval/results ./eval/results
COPY eval/scripts ./eval/scripts
ENV PATH="/srv/kavach/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
