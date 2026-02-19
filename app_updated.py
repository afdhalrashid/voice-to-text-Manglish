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
import time

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
from models import db, User, TranscriptionHistory, Job, JobStatus, JobType
from auth import auth_bp

# Import tasks for Celery
from tasks import transcribe_audio_async, celery

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

# Celery configuration
app.config["CELERY_BROKER_URL"] = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
app.config["CELERY_RESULT_BACKEND"] = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

# Initialize extensions
CORS(app)
db.init_app(app)
mail = Mail(app)

# Configure Celery
celery.conf.update(app.config)

class ContextTask(celery.Task):
    """Make celery tasks work with Flask app context."""
    def __call__(self, *args, **kwargs):
        with app.app_context():
            return self.run(*args, **kwargs)

celery.Task = ContextTask

# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Register authentication blueprint
app.register_blueprint(auth_bp)

# Configure logging
if not app.debug:
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10240000, backupCount=10)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]"
        )
    )
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info("Voice to Text startup")

# Create logger for this module
logger = logging.getLogger(__name__)

# File upload settings
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "mp3",
    "wav",
    "m4a",
    "ogg",
    "flac",
    "webm",
    "mp4",
    "wma",
    "aac",
}

# Global Whisper model (loaded on first use)
model = None


def load_model():
    global model
    if model is None:
        model_name = os.environ.get("WHISPER_MODEL", "base")
        logger.info(f"Loading Whisper model: {model_name}")
        start_time = time.time()
        model = whisper.load_model(model_name)
        load_time = time.time() - start_time
        logger.info(f"Whisper model loaded in {load_time:.2f} seconds")
    return model


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def make_json_serializable(obj):
    """Convert numpy types to JSON serializable types"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_serializable(item) for item in obj]
    return obj


# Routes
@app.route("/")
@login_required
def index():
    """Main transcription interface"""
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    """User dashboard showing transcription history"""
    # Get user's recent transcriptions (limit to last 50)
    transcriptions = TranscriptionHistory.query.filter_by(user_id=current_user.id).order_by(
        TranscriptionHistory.created_at.desc()
    ).limit(50).all()

    # Get user's active jobs
    active_jobs = Job.query.filter_by(
        user_id=current_user.id
    ).filter(
        Job.status.in_([JobStatus.PENDING.value, JobStatus.PROCESSING.value])
    ).order_by(Job.created_at.desc()).all()

    return render_template("dashboard.html", transcriptions=transcriptions, active_jobs=active_jobs)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Voice to Text API is running"})


# Legacy synchronous transcription endpoint (kept for backward compatibility)
@app.route("/api/transcribe", methods=["POST"])
@login_required
def transcribe():
    """Legacy synchronous transcription endpoint (deprecated - use /api/transcribe-async)"""
    logger.warning("Legacy synchronous transcription endpoint used - consider using /api/transcribe-async")
    
    # For now, redirect to async endpoint
    return jsonify({
        "error": "Synchronous transcription is deprecated. Please use /api/transcribe-async for better performance.",
        "redirect": "/api/transcribe-async"
    }), 400


@app.route("/api/transcribe-async", methods=["POST"])
@login_required
def transcribe_async():
    """Submit transcription job for async processing"""
    filename = None
    temp_path = None
    request_start = time.perf_counter()

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
        temp_path = os.path.join(UPLOAD_FOLDER, f"{current_user.id}_{int(time.time())}_{filename}")
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

        # Create job record
        job = Job(
            user_id=current_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename=filename,
            file_path=temp_path,
            file_size=file_size,
        )
        
        db.session.add(job)
        db.session.commit()

        # Prepare task parameters
        transcribe_params = {}
        
        # Get language preference from request (optional)
        language_pref = request.form.get("language", "auto")
        if language_pref and language_pref != "auto":
            transcribe_params["language"] = language_pref

        # Speaker diarization parameters
        diarization_params = {}
        diarization_enabled = request.form.get("enable_diarization", "").lower() in {
            "1", "true", "yes", "on"
        }
        
        if diarization_enabled:
            diarization_params["enable_diarization"] = True
            if request.form.get("num_speakers"):
                diarization_params["num_speakers"] = int(request.form.get("num_speakers"))
            if request.form.get("min_speakers"):
                diarization_params["min_speakers"] = int(request.form.get("min_speakers"))
            if request.form.get("max_speakers"):
                diarization_params["max_speakers"] = int(request.form.get("max_speakers"))

        # Submit async task
        task = transcribe_audio_async.delay(
            job_id=job.id,
            file_path=temp_path,
            user_id=current_user.id,
            transcribe_params=transcribe_params,
            diarization_params=diarization_params
        )

        # Update job with task ID
        job.celery_task_id = task.id
        db.session.commit()

        logger.info(f"Job {job.id} submitted successfully (task: {task.id})")
        logger.info("Request completed in %.2fs", time.perf_counter() - request_start)

        return jsonify({
            "success": True,
            "job_id": job.id,
            "task_id": task.id,
            "status": "pending",
            "message": "Transcription job submitted successfully. Use /api/jobs/{job_id} to check status."
        })

    except Exception as e:
        filename_ctx = f" (file: {filename})" if filename else ""
        logger.error(f"Error submitting job{filename_ctx}: {str(e)}", exc_info=True)
        logger.info("Request failed in %.2fs", time.perf_counter() - request_start)
        
        # Clean up file if it exists
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

        return jsonify({"error": f"Failed to submit transcription job: {str(e)}"}), 500


@app.route("/api/jobs/<job_id>", methods=["GET"])
@login_required
def get_job_status(job_id):
    """Get job status and results"""
    try:
        job = Job.query.filter_by(id=job_id, user_id=current_user.id).first()
        
        if not job:
            return jsonify({"error": "Job not found"}), 404

        # Get Celery task status if available
        if job.celery_task_id:
            from celery.result import AsyncResult
            task = AsyncResult(job.celery_task_id, app=celery)
            
            # Update job status based on Celery task state
            if task.state == "PENDING" and job.status != JobStatus.PENDING.value:
                job.update_status(JobStatus.PENDING.value, progress=0)
                db.session.commit()
            elif task.state == "PROGRESS" and job.status != JobStatus.PROCESSING.value:
                job.update_status(JobStatus.PROCESSING.value, progress=50)
                db.session.commit()
            elif task.state == "SUCCESS" and job.status != JobStatus.COMPLETED.value:
                job.update_status(JobStatus.COMPLETED.value, progress=100)
                db.session.commit()
            elif task.state == "FAILURE" and job.status != JobStatus.FAILED.value:
                error_msg = str(task.info) if task.info else "Task failed"
                job.update_status(JobStatus.FAILED.value, progress=0, error_message=error_msg)
                db.session.commit()

        response_data = job.to_dict()
        
        # Include transcription result if job is completed
        if job.status == JobStatus.COMPLETED.value and job.result_data:
            response_data["result"] = job.result_data

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error getting job status for {job_id}: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to get job status"}), 500


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
@login_required
def cancel_job(job_id):
    """Cancel a job"""
    try:
        job = Job.query.filter_by(id=job_id, user_id=current_user.id).first()
        
        if not job:
            return jsonify({"error": "Job not found"}), 404

        if job.status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value]:
            return jsonify({"error": "Cannot cancel completed job"}), 400

        # Cancel Celery task if it exists
        if job.celery_task_id:
            from celery.result import AsyncResult
            task = AsyncResult(job.celery_task_id, app=celery)
            task.revoke(terminate=True)

        # Update job status
        job.update_status(JobStatus.CANCELLED.value, progress=0)
        db.session.commit()

        # Clean up file
        if job.file_path and os.path.exists(job.file_path):
            try:
                os.remove(job.file_path)
            except Exception:
                pass

        logger.info(f"Job {job_id} cancelled by user {current_user.username}")

        return jsonify({
            "success": True,
            "message": "Job cancelled successfully"
        })

    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to cancel job"}), 500


@app.route("/api/jobs", methods=["GET"])
@login_required
def list_jobs():
    """List user's jobs"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_filter = request.args.get('status')

        query = Job.query.filter_by(user_id=current_user.id)
        
        if status_filter:
            query = query.filter_by(status=status_filter)

        jobs = query.order_by(Job.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return jsonify({
            "jobs": [job.to_dict() for job in jobs.items],
            "total": jobs.total,
            "page": jobs.page,
            "per_page": jobs.per_page,
            "pages": jobs.pages,
            "has_next": jobs.has_next,
            "has_prev": jobs.has_prev,
        })

    except Exception as e:
        logger.error(f"Error listing jobs: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to list jobs"}), 500


@app.route("/api/history", methods=["GET"])
@login_required
def get_history():
    """Get user's transcription history"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        history = TranscriptionHistory.query.filter_by(user_id=current_user.id).order_by(
            TranscriptionHistory.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            "history": [record.to_dict() for record in history.items],
            "total": history.total,
            "page": history.page,
            "per_page": history.per_page,
            "pages": history.pages,
            "has_next": history.has_next,
            "has_prev": history.has_prev,
        })

    except Exception as e:
        logger.error(f"Error getting transcription history: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to get transcription history"}), 500


@app.route("/api/history/<int:history_id>", methods=["DELETE"])
@login_required
def delete_transcription(history_id):
    """Delete a transcription record"""
    transcription = TranscriptionHistory.query.filter_by(
        id=history_id, user_id=current_user.id
    ).first()

    if not transcription:
        return jsonify({"error": "Transcription not found"}), 404

    try:
        db.session.delete(transcription)
        db.session.commit()
        logger.info(
            f"Transcription {history_id} deleted by user {current_user.username}"
        )
        return jsonify({"success": True, "message": "Transcription deleted"})
    except Exception as e:
        logger.error(f"Error deleting transcription {history_id}: {str(e)}")
        return jsonify({"error": "Failed to delete transcription"}), 500


# Serve static files
@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory("frontend", filename)


# Database initialization
def create_tables():
    """Create database tables"""
    with app.app_context():
        db.create_all()
        logger.info("Database tables created")


if __name__ == "__main__":
    # Create database tables
    create_tables()
    
    # Run the Flask app
    debug_mode = os.environ.get("FLASK_DEBUG", "True").lower() == "true"
    port = int(os.environ.get("PORT", 5000))
    
    logger.info(f"Starting VoiceToText server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)