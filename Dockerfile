FROM python:3.12-slim AS base

ARG VERSION=dev
ENV PLAY_ANALYTICS_VERSION=$VERSION \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    OUTPUT_DIR=/app/output

WORKDIR /app

# System deps: only what's needed by httplib2/grpc wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY config.py fetch.py parse.py dashboard.py report_md.py main.py ./

# Non-root user for safety. Owns the data/output dirs (mountable).
RUN useradd --create-home --uid 10001 app \
 && mkdir -p $DATA_DIR $OUTPUT_DIR \
 && chown -R app:app /app
USER app

VOLUME ["/app/data", "/app/output"]
EXPOSE 8080

ENTRYPOINT ["python", "main.py"]
