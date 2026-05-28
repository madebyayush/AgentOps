FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1

# Install systems dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install poetry manager
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Copy poetry configurations
COPY apps/api-gateway/pyproject.toml ./apps/api-gateway/

# Build virtual environment
WORKDIR /app/apps/api-gateway
RUN poetry install --no-root --only main

# --- PRODUCTION RUNNER STAGE ---
FROM python:3.11-slim AS runner
WORKDIR /app

ENV PATH="/app/apps/api-gateway/.venv/bin:$PATH"

COPY --from=builder /app/apps/api-gateway/.venv /app/apps/api-gateway/.venv
COPY apps/api-gateway/ /app/apps/api-gateway/

WORKDIR /app/apps/api-gateway
EXPOSE 8000

# Execute server reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
