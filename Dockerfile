FROM python:3.15-slim-bookworm AS build

RUN pip install --no-cache-dir uv==0.13.5

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev --no-install-project --no-cache


FROM python:3.15-slim-bookworm

RUN useradd --system --no-create-home app

WORKDIR /app

COPY --from=build /app/.venv ./.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# No access log: it would keep the IP of every visitor (see /datenschutz of the frontend).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000 --proxy-headers --no-access-log"]
