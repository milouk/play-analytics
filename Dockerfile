FROM python:3.12-slim AS base

ARG VERSION=dev
ARG TARGETARCH
ENV PLAY_ANALYTICS_VERSION=$VERSION \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    OUTPUT_DIR=/app/output

WORKDIR /app

# System deps + supercronic (small static binary, cron designed for
# containers — logs to stdout, runs as PID 1, no privilege escalation).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/v0.2.30/supercronic-linux-${TARGETARCH:-amd64}" \
 && chmod +x /usr/local/bin/supercronic \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py fetch.py parse.py dashboard.py report_md.py main.py pricing.py apply_pricing.py ./
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN useradd --create-home --uid 10001 app \
 && mkdir -p $DATA_DIR $OUTPUT_DIR \
 && chown -R app:app /app
USER app

VOLUME ["/app/data", "/app/output"]
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
