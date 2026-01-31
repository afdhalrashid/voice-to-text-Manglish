# VoiceToText - includes ffmpeg required by Whisper
FROM python:3.11-slim

# Install ffmpeg (required for Whisper audio decoding)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Whisper model cache and uploads
ENV WHISPER_CACHE_DIR=/app/.whisper_cache
RUN mkdir -p uploads .whisper_cache

EXPOSE 5000

CMD ["python", "app.py"]
