from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import secrets

db = SQLAlchemy()


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


class TranscriptionHistory(db.Model):
    __tablename__ = "transcription_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    transcription_text = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(10), default="unknown")
    file_size = db.Column(db.Integer, default=0)  # Size in bytes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Speaker diarization data (JSON format)
    speaker_segments = db.Column(
        db.JSON, nullable=True
    )  # Store speaker segments with timestamps
    speaker_summary = db.Column(db.JSON, nullable=True)  # Speaker statistics summary
    num_speakers = db.Column(db.Integer, nullable=True)  # Number of speakers detected

    def to_dict(self):
        """Convert transcription record to dictionary"""
        return {
            "id": self.id,
            "filename": self.filename,
            "transcription_text": self.transcription_text,
            "language": self.language,
            "file_size": self.file_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "speaker_segments": self.speaker_segments,
            "speaker_summary": self.speaker_summary,
            "num_speakers": self.num_speakers,
        }

    def __repr__(self):
        return f"<TranscriptionHistory {self.id} - User {self.user_id}>"
