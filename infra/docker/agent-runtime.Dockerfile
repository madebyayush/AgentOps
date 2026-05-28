FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

COPY apps/agent-runtime/pyproject.toml ./apps/agent-runtime/

WORKDIR /app/apps/agent-runtime
RUN poetry install --no-root --only main

# --- PRODUCTION RUNNER STAGE ---
FROM python:3.11-slim AS runner
WORKDIR /app

ENV PATH="/app/apps/agent-runtime/.venv/bin:$PATH"

COPY --from=builder /app/apps/agent-runtime/.venv /app/apps/agent-runtime/.venv
COPY apps/agent-runtime/ /app/apps/agent-runtime/

# Also bring in required internal workspace libraries as mounted dependencies
COPY packages/ /app/packages/

WORKDIR /app/apps/agent-runtime

CMD ["python", "agent/main.py"]
