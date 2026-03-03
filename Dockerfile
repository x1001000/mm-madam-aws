# Base image
FROM public.ecr.aws/docker/library/python:3.13-slim

# Lambda Web Adapter: translates Lambda invoke events into HTTP requests,
# enabling SSE streaming via a standard web server (uvicorn) on Lambda
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
ENV PORT=8000

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies (git needed for packages from git repos)
COPY pyproject.toml uv.lock ./
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --no-dev --no-install-project

# Application code and static assets
COPY main.py .
COPY test-frontend/ ./test-frontend/

# Help center knowledge base: HTML articles and CSV indexes (sets the `cutoff` global in main.py)
COPY knowledge/ ./knowledge/

# Start uvicorn; Lambda Web Adapter forwards Lambda events to this server
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
