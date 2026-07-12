# Purpose: RestoreProof API / worker container image
# Author: Doug Hesseltine
# Created: 2026-07-12
# Version: 1.0.0

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /data/evidence /data/keys \
    && chmod 700 /data/keys

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
