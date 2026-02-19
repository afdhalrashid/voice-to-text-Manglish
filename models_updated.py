from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import secrets
import uuid
from enum import Enum

db = SQLAlchemy()


class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(Enum):
    TRANSCRIPTION = "transcription"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reset_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)

    # Relationship to transcription history
    transcriptions = db.relationship(
        "TranscriptionHistory", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    
    # Relationship to jobs
    jobs = db.relationship(
        "Job", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        """Hash and set user password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if provided password matches hash"""
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self):
        """Generate a password reset token"""
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)
        return self.reset_token

    def verify_reset_token(self, token):
        """Verify if reset token is valid and not expired"""
        if self.reset_token != token:
            return False
        if not self.reset_token_expiry or datetime.utcnow() > self.reset_token_expiry:
            return False
        return True

    def clear_reset_token(self):
        """Clear the reset token after use"""
        self.reset_token = None
        self.reset_token_expiry = None

    def __repr__(self):
        return f"<User {self.username}>"


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    celery_task_id = db.Column(db.String(100), unique=True, nullable=True)
    
    # Job details
    job_type = db.Column(db.String(50), default=JobType.TRANSCRIPTION.value)
    status = db.Column(db.String(20), default=JobStatus.PENDING.value)
    progress = db.Column(db.Integer, default=0)  # 0-100
    
    # File information
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Results and metadata
    result_data = db.Column(db.JSON, nullable=True)  # Store transcription result
    job_metadata = db.Column(db.JSON, nullable=True)  # Job-specific parameters
    error_message = db.Column(db.Text, nullable=True)
    processing_time = db.Column(db.Float, nullable=True)  # Seconds
    
    def to_dict(self):
        """Convert job record to dictionary"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "celery_task_id": self.celery_task_id,
            "job_type": self.job_type,
            "status": self.status,
            "progress": self.progress,
            "filename": self.filename,
            "file_size": self.file_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_data": self.result_data,
            "metadata": self.job_metadata,
            "error_message": self.error_message,
            "processing_time": self.processing_time,
        }

    def update_status(self, status, progress=None, error_message=None):
        """Update job status with optional progress and error message"""
        self.status = status
        if progress is not None:
            self.progress = progress
        if error_message:
            self.error_message = error_message
        
        if status == JobStatus.PROCESSING.value and not self.started_at:
            self.started_at = datetime.utcnow()
        elif status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value]:
            if not self.completed_at:
                self.completed_at = datetime.utcnow()
            if self.started_at and not self.processing_time:
                self.processing_time = (self.completed_at - self.started_at).total_seconds()

    def __repr__(self):
        return f"<Job {self.id} - {self.job_type} - {self.status}>"


class TranscriptionHistory(db.Model):
    __tablename__ = "transcription_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    job_id = db.Column(db.String(36), db.ForeignKey("jobs.id"), nullable=True)  # Link to job
    filename = db.Column(db.String(255), nullable=False)
    transcription_text = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(10), default="unknown")
    file_size = db.Column(db.Integer, default=0)  # Size in bytes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processing_time = db.Column(db.Float, nullable=True)  # Seconds
    model_used = db.Column(db.String(50), default='base')

    # Speaker diarization data (JSON format)
    speaker_segments = db.Column(
        db.JSON, nullable=True
    )  # Store speaker segments with timestamps
    speaker_summary = db.Column(db.JSON, nullable=True)  # Speaker statistics summary
    num_speakers = db.Column(db.Integer, nullable=True)  # Number of speakers detected

    # Relationship to job
    job = db.relationship("Job", backref="transcription_history", uselist=False)

    def to_dict(self):
        """Convert transcription record to dictionary"""
        return {
            "id": self.id,
            "job_id": self.job_id,
            "filename": self.filename,
            "transcription_text": self.transcription_text,
            "language": self.language,
            "file_size": self.file_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "processing_time": self.processing_time,
            "model_used": self.model_used,
            "speaker_segments": self.speaker_segments,
            "speaker_summary": self.speaker_summary,
            "num_speakers": self.num_speakers,
        }

    def __repr__(self):
        return f"<TranscriptionHistory {self.id} - User {self.user_id}>"