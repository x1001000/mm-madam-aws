# Use the official AWS Lambda Python runtime as a parent image
FROM public.ecr.aws/lambda/python:3.13

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install git for git-based pip dependencies
RUN microdnf install -y git && microdnf clean all

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