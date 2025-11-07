# Use the official AWS Lambda Python runtime as a parent image
FROM public.ecr.aws/lambda/python:3.13

# Install Node.js 20 and npm for MCP server
RUN microdnf update -y && microdnf install -y \
    tar \
    xz \
    git \
    && microdnf clean all

# Install Node.js 20 from NodeSource
RUN curl -fsSL https://rpm.nodesource.com/setup_20.x | bash - && \
    microdnf install -y nodejs && \
    microdnf clean all

# Install mcp-remote locally in Lambda task root
WORKDIR ${LAMBDA_TASK_ROOT}
RUN npm init -y && npm install mcp-remote

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy function code
COPY main.py ${LAMBDA_TASK_ROOT}

# Copy static files and knowledge data
COPY index.html ${LAMBDA_TASK_ROOT}
COPY chat-widget.js ${LAMBDA_TASK_ROOT}
COPY *.png ${LAMBDA_TASK_ROOT}
COPY knowledge/ ${LAMBDA_TASK_ROOT}/knowledge/

# Set the CMD to your handler
CMD ["main.handler"]