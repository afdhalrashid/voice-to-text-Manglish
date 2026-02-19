# VoiceToText - includes ffmpeg required by Whisper
FROM python:3.11-slim

# Install ffmpeg (required for Whisper audio decoding)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy remaining files first
COPY auth.py diarization.py ./
COPY frontend/ frontend/

# Then override with async versions
COPY frontend/index_async.html frontend/index.html
COPY frontend/dashboard_async.html frontend/dashboard.html

# Copy updated async files
COPY app_updated.py app.py
COPY models_updated.py models.py
COPY tasks.py worker.py ./

# Whisper model cache and uploads
ENV WHISPER_CACHE_DIR=/app/.whisper_cache
RUN mkdir -p uploads .whisper_cache

EXPOSE 5000

CMD ["python", "app.py"]
