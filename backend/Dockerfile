FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-postgres.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt

COPY . .

EXPOSE 8000

# Default command runs the API. The worker and scheduler override this in
# docker-compose with their own commands.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
