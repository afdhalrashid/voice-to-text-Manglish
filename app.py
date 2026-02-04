from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import tempfile
from werkzeug.utils import secure_filename
import logging
from logging.handlers import RotatingFileHandler
import numpy as np

# Set Whisper cache directory to project folder (to avoid permission issues)
# This must be set before importing whisper
WHISPER_CACHE_DIR = os.path.join(os.path.dirname(__file__), '.whisper_cache')
os.makedirs(WHISPER_CACHE_DIR, exist_ok=True)

# Log file for voice-to-text processing and errors
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'voice2text.log')

from werkzeug.middleware.proxy_fix import ProxyFix
import whisper

app = Flask(__name__, static_folder='frontend')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
CORS(app)

# Configure logging: console + rotating log file
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Configure upload settings
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'ogg', 'flac', 'webm', 'mp4', 'wma', 'aac'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load Whisper model (base model supports Malay well)
# You can change to 'small', 'medium', or 'large' for better accuracy but slower processing
model = None

def load_model():
    global model
    if model is None:
        logger.info("Loading Whisper model...")
        # Use custom cache directory to avoid permission issues
        model = whisper.load_model("base", download_root=WHISPER_CACHE_DIR)
        logger.info("Model loaded successfully")
    return model

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def make_json_serializable(obj):
    """Convert numpy/types to native Python so jsonify() works."""
    if isinstance(obj, (np.integer, np.floating)):
        return float(obj) if isinstance(obj, np.floating) else int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_json_serializable(v) for v in obj]
    return obj

@app.route('/')
def index():
    return send_from_directory('frontend', 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "Voice to Text API is running"})

@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    try:
        # Check if file is present
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        
        file = request.files['audio']
        
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if not allowed_file(file.filename):
            return jsonify({"error": f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
        
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        temp_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(temp_path)
        
        # Check file size
        file_size = os.path.getsize(temp_path)
        if file_size > MAX_FILE_SIZE:
            os.remove(temp_path)
            return jsonify({"error": f"File too large. Maximum size: {MAX_FILE_SIZE / (1024*1024):.0f}MB"}), 400
        
        logger.info(f"Processing file: {filename} ({file_size / (1024*1024):.2f}MB)")
        
        # Load model if not already loaded
        model = load_model()
        
        # Transcribe audio
        # Using language='ms' for Malay, but Whisper auto-detects well for mixed languages
        # task='transcribe' ensures it transcribes (not translates)
        result = model.transcribe(
            temp_path,
            language='ms',  # Malay language code
            task='transcribe',  # Transcribe (not translate)
            fp16=False,  # Use fp32 for better compatibility
            verbose=False
        )
        
        # Clean up temporary file
        os.remove(temp_path)
        
        # Extract transcription text
        text = result.get('text', '').strip()
        
        logger.info(f"Transcription completed. Length: {len(text)} characters")
        
        # Whisper segments contain numpy types; convert so jsonify() can serialize
        segments = make_json_serializable(result.get('segments', []))
        language = result.get('language', 'unknown')
        if hasattr(language, 'item'):  # numpy scalar
            language = str(language)
        
        return jsonify({
            "success": True,
            "text": text,
            "language": language,
            "segments": segments
        })
        
    except Exception as e:
        filename_ctx = f" (file: {filename})" if 'filename' in locals() else ""
        logger.error(f"Error during transcription{filename_ctx}: {str(e)}", exc_info=True)
        # Clean up file if it exists
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                logger.warning(f"Could not remove temp file: {temp_path}")
        return jsonify({"error": f"Transcription failed: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
