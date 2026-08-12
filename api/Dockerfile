FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# 가상환경을 /opt/venv에 두어, 소스를 /app에 볼륨 마운트해도 깨지지 않게 합니다
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
# PATH 등록으로 `docker compose exec api pytest` 처럼 venv 도구를 바로 부를 수 있습니다

WORKDIR /app

COPY pyproject.toml uv.lock ./
# dev 그룹(pytest)까지 설치 — `docker compose exec api uv run pytest` 시연을 위해
RUN uv sync --frozen

COPY . .

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
