FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_INSTALL_DIR=/usr/local/bin

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv (fast Python packaging)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# Ensure uv and the project venv are on PATH
ENV PATH="/usr/local/bin:/root/.local/bin:/root/.cargo/bin:${UV_PROJECT_ENVIRONMENT}/bin:${PATH}"

# Install dependencies into a project-local virtualenv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
