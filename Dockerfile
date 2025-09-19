# Use a small official Python base
FROM python:3.11-slim

# Avoid Python writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps (if any). Keep minimal for slim image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY app/ /app/

# Default envs - can be overridden by docker-compose or .env
ENV MEDIA_ROOT=/media \
    LOG_ROOT=/fetch_logs \
    RD_SCRIPT=/app/rdfin_strm.py \
    FLASK_ENV=production

# Expose port for Flask
EXPOSE 3001

# Run the Flask app
CMD ["python", "app.py"]
