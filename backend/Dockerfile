# Python 3.12 is pinned deliberately: every dependency ships a wheel for it, so the
# image builds without a compiler toolchain.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copied first so dependency layers cache independently of source changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY entrypoint.sh /entrypoint.sh
# Strip CR so the image builds from a Windows checkout too: a CRLF shebang makes the
# kernel search for "/bin/sh\r" and fail with a misleading "no such file or directory".
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# --- runtime -----------------------------------------------------------------
FROM base AS runtime

# Run unprivileged: nothing here needs root at runtime.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- test --------------------------------------------------------------------
# Separate stage so pytest and ruff never ship in the runtime image.
# claude-agent-sdk IS in requirements.txt and therefore in the runtime image —
# Anthropic chat uses ClaudeAgentSDKRuntime. Used by:
#   docker compose --profile test run --rm tests
FROM base AS test

COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY pytest.ini ./
COPY tests ./tests

# No entrypoint: migrations are irrelevant here because the suite creates its own schema.
ENTRYPOINT []
CMD ["pytest"]
