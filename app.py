from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    render_template,
    redirect,
    url_for,
)
from flask_cors import CORS
from flask_login import LoginManager, login_required, current_user
from flask_mail import Mail
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import tempfile
import logging
from logging.handlers import RotatingFileHandler
import numpy as np
from datetime import datetime

# Load environment variables
load_dotenv()

# Set Whisper cache directory to project folder (to avoid permission issues)
# This must be set before importing whisper
WHISPER_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".whisper_cache")
os.makedirs(WHISPER_CACHE_DIR, exist_ok=True)

# Log file for voice-to-text processing and errors
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "voice2text.log")

from werkzeug.middleware.proxy_fix import ProxyFix
import whisper

# Import models and auth
from models import db, User, TranscriptionHistory
from auth import auth_bp

# Import speaker diarization
try:
    from diarization import SpeakerDiarizer, get_diarizer

    DIARIZATION_AVAILABLE = (
        os.environ.get("ENABLE_DIARIZATION", "true").lower() == "true"
    )
    if not DIARIZATION_AVAILABLE:
        logger = logging.getLogger(__name__)
        logger.info("Speaker diarization disabled via ENABLE_DIARIZATION setting")
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.warning(f"Speaker diarization not available: {e}")
    DIARIZATION_AVAILABLE = False

app = Flask(__name__, static_folder="frontend", template_folder="frontend")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configuration
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "dev-secret-key-change-in-production"
)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///voice2text.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Upload configuration - Get max file size from environment variable (default: 500MB)
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "500"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

# Email configuration
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "false").lower() == "true"
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")

# Initialize extensions
CORS(app)
db.init_app(app)
mail = Mail(app)

# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Register blueprints
app.register_blueprint(auth_bp, url_prefix="/auth")

# Configure logging: console + rotating log file
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5,
    encoding="utf-8",
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Configure upload settings
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"wav", "mp3", "m4a", "ogg", "flac", "webm", "mp4", "wma", "aac"}
# MAX_FILE_SIZE is already set above in Flask config section

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load Whisper model (base model supports Malay well)
model = None


def load_model():
    global model
    if model is None:
        logger.info("Loading Whisper model...")
        model = whisper.load_model("base", download_root=WHISPER_CACHE_DIR)
        logger.info("Model loaded successfully")
    return model


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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


# Create database tables
with app.app_context():
    db.create_all()
    logger.info("Database tables created/verified")


@app.route("/")
def index():
    """Main page - requires authentication"""
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    return send_from_directory("frontend", "index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    """User dashboard with transcription history"""
    transcriptions = (
        TranscriptionHistory.query.filter_by(user_id=current_user.id)
        .order_by(TranscriptionHistory.created_at.desc())
        .all()
    )

    # Calculate stats
    total_transcriptions = len(transcriptions)
    total_files = len(set([t.filename for t in transcriptions]))
    member_since = (
        current_user.created_at.strftime("%B %Y")
        if current_user.created_at
        else "Unknown"
    )

    return render_template(
        "dashboard.html",
        transcriptions=transcriptions,
        total_transcriptions=total_transcriptions,
        total_files=total_files,
        member_since=member_since,
    )


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Voice to Text API is running"})


@app.route("/api/transcribe", methods=["POST"])
@login_required
def transcribe():
    """Transcribe audio file and save to user history"""
    filename = None
    temp_path = None

    try:
        # Check if file is present
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400

        file = request.files["audio"]

        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        if not allowed_file(file.filename):
            return jsonify(
                {
                    "error": f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
                }
            ), 400

        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        temp_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(temp_path)

        # Check file size
        file_size = os.path.getsize(temp_path)
        if file_size > MAX_FILE_SIZE:
            os.remove(temp_path)
            return jsonify(
                {
                    "error": f"File too large. Maximum size: {MAX_FILE_SIZE / (1024 * 1024):.0f}MB"
                }
            ), 400

        logger.info(
            f"Processing file: {filename} ({file_size / (1024 * 1024):.2f}MB) - User: {current_user.username}"
        )

        # Load model if not already loaded
        model = load_model()

        # Get language preference from request (optional)
        # If not specified, Whisper will auto-detect (best for mixed languages)
        language_pref = request.form.get("language", "auto")

        # Prepare transcription parameters
        transcribe_params = {"fp16": False, "verbose": False, "task": "transcribe"}

        # Only specify language if user explicitly chooses one
        # "auto" or not specified = let Whisper detect automatically (best for mixed language)
        if language_pref and language_pref != "auto":
            transcribe_params["language"] = language_pref
            logger.info(f"Using specified language: {language_pref}")
        else:
            logger.info("Using auto language detection for mixed-language support")

        # Transcribe audio
        result = model.transcribe(temp_path, **transcribe_params)

        logger.info(
            f"Transcription completed. Length: {len(result.get('text', ''))} characters"
        )

        # Convert numpy types to JSON serializable
        segments = make_json_serializable(result.get("segments", []))
        language = result.get("language", "unknown")
        if hasattr(language, "item"):
            language = str(language)

        # Perform speaker diarization (optional)
        speaker_segments = []
        speaker_summary = {}
        num_speakers = 0

        if DIARIZATION_AVAILABLE:
            try:
                logger.info("Starting speaker diarization...")
                diarizer = get_diarizer()

                # Get optional parameters from request
                expected_speakers = request.form.get("num_speakers", type=int)
                min_speakers = request.form.get("min_speakers", type=int)
                max_speakers = request.form.get("max_speakers", type=int)

                # Run diarization
                diarization_result = diarizer.diarize(
                    temp_path,
                    num_speakers=expected_speakers,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )

                if diarization_result:
                    # Merge with transcription segments
                    segments = diarizer.merge_with_transcription(
                        segments, diarization_result
                    )
                    speaker_summary = diarizer.get_speaker_summary(segments)
                    num_speakers = len(set(s["speaker"] for s in diarization_result))
                    speaker_segments = diarization_result

                    logger.info(
                        f"Speaker diarization complete: {num_speakers} speakers identified"
                    )
            except Exception as e:
                logger.warning(f"Speaker diarization failed: {str(e)}")
                # Continue without speaker identification

        # Extract transcription text
        text = result.get("text", "").strip()

        # Clean up temporary file
        os.remove(temp_path)

        # Save to user's transcription history
        transcription_record = TranscriptionHistory(
            user_id=current_user.id,
            filename=filename,
            transcription_text=text,
            language=language,
            file_size=file_size,
            speaker_segments=speaker_segments if speaker_segments else None,
            speaker_summary=speaker_summary if speaker_summary else None,
            num_speakers=num_speakers if num_speakers > 0 else None,
        )
        db.session.add(transcription_record)
        db.session.commit()

        logger.info(
            f"Transcription saved to user {current_user.username}'s history (ID: {transcription_record.id})"
        )

        return jsonify(
            {
                "success": True,
                "text": text,
                "language": language,
                "segments": segments,
                "history_id": transcription_record.id,
                "speakers": {
                    "count": num_speakers,
                    "segments": speaker_segments,
                    "summary": speaker_summary,
                }
                if speaker_segments
                else None,
            }
        )

    except Exception as e:
        filename_ctx = f" (file: {filename})" if filename else ""
        logger.error(
            f"Error during transcription{filename_ctx}: {str(e)}", exc_info=True
        )
        # Clean up file if it exists
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                logger.warning(f"Could not remove temp file: {temp_path}")
        return jsonify({"error": f"Transcription failed: {str(e)}"}), 500


@app.route("/api/history", methods=["GET"])
@login_required
def get_history():
    """Get user's transcription history (API endpoint)"""
    try:
        transcriptions = (
            TranscriptionHistory.query.filter_by(user_id=current_user.id)
            .order_by(TranscriptionHistory.created_at.desc())
            .all()
        )
        return jsonify(
            {
                "success": True,
                "transcriptions": [t.to_dict() for t in transcriptions],
                "total": len(transcriptions),
            }
        )
    except Exception as e:
        logger.error(
            f"Error fetching history for user {current_user.username}: {str(e)}",
            exc_info=True,
        )
        return jsonify({"error": f"Failed to fetch history: {str(e)}"}), 500


@app.route("/api/history/<int:transcription_id>", methods=["DELETE"])
@login_required
def delete_transcription(transcription_id):
    """Delete a specific transcription from user's history"""
    try:
        transcription = TranscriptionHistory.query.filter_by(
            id=transcription_id, user_id=current_user.id
        ).first()

        if not transcription:
            return jsonify({"error": "Transcription not found"}), 404

        db.session.delete(transcription)
        db.session.commit()

        logger.info(
            f"Transcription {transcription_id} deleted by user {current_user.username}"
        )
        return jsonify(
            {"success": True, "message": "Transcription deleted successfully"}
        )
    except Exception as e:
        logger.error(
            f"Error deleting transcription {transcription_id}: {str(e)}", exc_info=True
        )
        return jsonify({"error": f"Failed to delete transcription: {str(e)}"}), 500


# Serve static files
@app.route("/frontend/<path:filename>")
def serve_static(filename):
    return send_from_directory("frontend", filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
