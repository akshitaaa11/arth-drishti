# Arth Drishti: API + dashboard in one image. Build:  docker compose build api   Run:  docker compose up api
# Stage 1 builds the React dashboard; stage 2 is the Python API that also serves it at /app/.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# libgomp is needed by LightGBM; curl is only for debugging inside the container.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Editable install keeps the code at /app/src, so the project root the code computes is /app (where config/, data/ and reports/ live).
COPY pyproject.toml README.md PRD.md ./
COPY src ./src
RUN pip install -e .
COPY config ./config
COPY data/csv ./data/csv
COPY data/source_pdfs ./data/source_pdfs
COPY reports ./reports
COPY --from=web /web/dist ./web/dist
# No secrets are baked in: GROQ_API_KEY and friends arrive as environment variables at run time (see docker-compose.yml and .env).
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "bsp.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
