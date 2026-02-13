#!/bin/bash

# Voice-to-Text Authentication Setup Script

echo "🎤 Voice-to-Text Authentication Setup"
echo "======================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "✅ Python version: $(python3 --version)"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo ""
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo ""
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install requirements
echo ""
echo "📥 Installing requirements..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo ""
    echo "📝 Creating .env file from .env.example..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your configuration!"
fi

# Create required directories
echo ""
echo "📁 Creating required directories..."
mkdir -p uploads logs

# Initialize database
echo ""
echo "🗄️  Initializing database..."
python3 -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('✅ Database tables created successfully!')
"

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 To start the application:"
echo "   1. Edit .env file with your configuration"
echo "   2. Run: python app.py"
echo ""
echo "📖 Default URLs:"
echo "   - Application: http://localhost:5001"
echo "   - Login:       http://localhost:5001/auth/login"
echo "   - Register:    http://localhost:5001/auth/register"
echo ""
