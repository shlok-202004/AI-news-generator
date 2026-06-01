# syntax=docker/dockerfile:1
FROM python:3.12-slim

# trafilatura depends on lxml which needs gcc + libxml2/libxslt to compile on slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libxml2-dev \
        libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so this layer caches unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure logs dir exists at image build time
RUN mkdir -p /app/logs

# discord_bot.py is the single entry point: runs the bot + daily APScheduler
CMD ["python", "delivery/discord_bot.py"]
