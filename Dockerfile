# FanFit web app. Multi-arch: Spark is arm64.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY fanfit ./fanfit
COPY fixtures ./fixtures
RUN useradd --uid 10001 --no-create-home app && mkdir -p /data/qloo-cache && chown app /data/qloo-cache
USER 10001
ENV PATH="/app/.venv/bin:$PATH" QLOO_CACHE_DIR=/data/qloo-cache
EXPOSE 8000
CMD ["uvicorn", "fanfit.web:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
