FROM python:3.13-slim

WORKDIR /app

# System dependencies for Pillow (libjpeg, zlib) and Postgres client
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (better cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir psycopg2-binary

# Copy application code
COPY . .

# Create runtime directories
RUN mkdir -p flask_session static/uploads migrations

# Make entrypoint executable (also strip CRLF in case of Windows checkout)
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

EXPOSE 5000

CMD ["./docker-entrypoint.sh"]
