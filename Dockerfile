# Root-level Dockerfile for deploying the FastAPI backend on platforms like Railway.
# Uses repo root as build context so we can copy both backend app and shared `sotd` package.

FROM python:3.11-slim

WORKDIR /app

# Install backend dependencies
COPY app/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend app and shared recommender code
COPY app/backend/app ./app
COPY sotd ./sotd

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Bind to platform-provided PORT env var, default to 8000 locally
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
