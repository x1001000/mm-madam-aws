# Base image
FROM public.ecr.aws/docker/library/python:3.13-slim

# Lambda Web Adapter: translates Lambda invoke events into HTTP requests,
# enabling SSE streaming via a standard web server (uvicorn) on Lambda
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
ENV PORT=8000

WORKDIR /app

# Install dependencies (git needed for pip packages from git repos)
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Application code and static assets
COPY main.py .
COPY index.html .
COPY chat-widget.js .
COPY *.png .

# Help center knowledge base: HTML articles and CSV indexes (sets the `cutoff` global in main.py)
COPY knowledge/ ./knowledge/

# Start uvicorn; Lambda Web Adapter forwards Lambda events to this server
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
