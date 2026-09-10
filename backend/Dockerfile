# Multi-stage: `dev` runs uvicorn --reload against a bind-mounted backend/
# (see docker-compose.yml); `prod` copies the source in and runs without
# reload or a mount, as a non-root user. Both stages install the exact same
# requirements.txt that CI and a native venv install, so behaviour does not
# fork between docker and non-docker runs.
FROM python:3.12-slim AS base

# Needed to build a couple of scientific-Python wheels (numpy/pandas) on
# platforms with no prebuilt wheel; slim images ship neither by default.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── dev ──────────────────────────────────────────────────────────────
# Source is bind-mounted over this in compose; the COPY here only makes the
# image runnable standalone (e.g. `docker build --target dev`) without a mount.
FROM base AS dev
COPY . .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── prod ─────────────────────────────────────────────────────────────
FROM base AS prod
COPY . .
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
