FROM python:3.11-slim

WORKDIR /app

COPY app/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend app and the shared recommender code
COPY app/backend/app ./app
COPY sotd ./sotd

ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
