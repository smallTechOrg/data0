# ── Frontend build stage ─────────────────────────────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /build/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ── App stage ─────────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ ./src/
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
COPY --from=frontend /build/frontend/out ./frontend/out

ENV PYTHONPATH=/app/src
ENV AGENT_DATABASE_URL=sqlite:////tmp/agent.db

EXPOSE 8080
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}"]
