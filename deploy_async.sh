#!/bin/bash

# VoiceToText Async Deployment Script
echo "🚀 Starting VoiceToText Async Deployment..."

# Check if Docker and Docker Compose are installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Stop any existing containers
echo "🛑 Stopping existing containers..."
docker-compose down

# Backup current models and environment
echo "💾 Backing up current configuration..."
if [ -f "models.py" ]; then
    cp models.py models.py.backup
fi

if [ -f "app.py" ]; then
    cp app.py app.py.backup
fi

if [ -f ".env" ]; then
    cp .env .env.backup
fi

# Replace with new async versions
echo "🔄 Updating application files..."
cp models_updated.py models.py
cp app_updated.py app.py
cp frontend/index_async.html frontend/index.html
cp frontend/dashboard_async.html frontend/dashboard.html

# Update environment file
if [ -f ".env.updated" ]; then
    cp .env.updated .env
else
    echo "⚠️ Warning: .env.updated not found. Please update your .env file manually."
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p uploads
mkdir -p logs
mkdir -p .whisper_cache

# Set permissions
chmod 755 uploads
chmod 755 logs
chmod 755 .whisper_cache

# Build and start containers
echo "🏗️ Building Docker containers..."
docker-compose build

echo "⚡ Starting services..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check service status
echo "🩺 Checking service health..."

# Check Redis
if docker-compose exec redis redis-cli ping | grep -q "PONG"; then
    echo "✅ Redis is running"
else
    echo "❌ Redis is not responding"
fi

# Check if Flask app is running
if curl -f http://localhost:5000/api/health &> /dev/null; then
    echo "✅ Flask app is running"
else
    echo "❌ Flask app is not responding"
fi

# Check Celery worker
if docker-compose logs worker | grep -q "ready"; then
    echo "✅ Celery worker is running"
else
    echo "⚠️ Celery worker may not be ready yet"
fi

echo ""
echo "🎉 Deployment completed!"
echo ""
echo "📋 Service URLs:"
echo "   🌐 Main App: http://localhost:5000"
echo "   🌸 Flower (Celery Monitor): http://localhost:5555"
echo "   🔧 Redis: localhost:6379"
echo ""
echo "📊 Check logs with:"
echo "   docker-compose logs -f app"
echo "   docker-compose logs -f worker"
echo "   docker-compose logs -f redis"
echo ""
echo "🛑 Stop services with:"
echo "   docker-compose down"
echo ""

# Run a quick test
echo "🧪 Running quick test..."
if [ -f "test_async_queuing.py" ]; then
    echo "📝 Unit tests available. Run with:"
    echo "   docker-compose exec app python -m pytest test_async_queuing.py -v"
fi

echo "✨ Ready to process audio files with queuing!"