FROM python:3.13-slim

# uv, copied from its official image (pinned to the version you use locally)
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Dependencies only: this layer is cached until pyproject.toml or uv.lock change
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# 2) Our code
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev

# Don't run as root inside the container
RUN useradd --create-home appuser
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
CMD ["notion-mcp"]