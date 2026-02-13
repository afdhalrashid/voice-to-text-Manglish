# Voice-to-Text Web Application Project Documentation

## Project Context

A Flask-based voice-to-text transcription service with authentication and speaker diarization capabilities.

---

## What We've Built So Far

### 1. Core Application (Flask-based Voice-to-Text)
- Base functionality using OpenAI Whisper for transcription
- Supports Malay, English, and mixed-language audio
- File upload with drag-and-drop interface
- Max file size: 500MB (configurable via MAX_FILE_SIZE_MB environment variable)
- Supported formats: MP3, WAV, M4A, OGG, FLAC, WEBM, MP4, WMA, AAC

### 2. Authentication System (Complete)
- User registration with email validation
- Login/logout with session management
- Password reset via email (configured with Mailtrap)
- Protected routes requiring authentication
- User dashboard showing transcription history

### 3. Speaker Diarization (PyAnnote Integration)
- Identifies "who spoke when" in audio
- Color-coded speaker labels in results
- Configurable min/max/expected speaker count
- Requires HuggingFace token (configured but needs user agreement acceptance)

### 4. Database (SQLite with SQLAlchemy)

**User Model:**
- `id` - Primary key
- `username` - User's display name
- `email` - User's email address
- `password_hash` - Encrypted password
- `created_at` - Account creation timestamp
- `reset_token` - Password reset token

**TranscriptionHistory Model:**
- `id` - Primary key
- `user_id` - Foreign key to User
- `filename` - Original uploaded filename
- `transcription_text` - The transcribed content
- `language` - Detected/selected language
- `file_size` - Size of uploaded file
- `created_at` - Transcription timestamp
- `speaker_segments` - JSON array of speaker timing data
- `speaker_summary` - Summary of speaker participation
- `num_speakers` - Number of speakers detected

### 5. Frontend Pages
- `index.html` - Main transcription interface with language selector & speaker options
- `login.html` - User login
- `register.html` - User registration
- `forgot_password.html` / `reset_password.html` - Password reset flow
- `dashboard.html` - User history & statistics

---

## Project Structure

```
/Users/muhammadafdhaluddin/WORK/Codeflare Solution Sdn Bhd/VoiceToText/
├── app.py                 # Main Flask app with auth & transcription
├── models.py              # Database models
├── auth.py                # Authentication routes
├── diarization.py         # Speaker identification module
├── requirements.txt       # Dependencies
├── .env                   # Configuration (SECRET_KEY, Mailtrap, HF_TOKEN)
├── .env.example          # Template file
├── setup.sh              # Installation script
├── voice2text.db         # SQLite database
└── frontend/
    ├── index.html        # Main interface with language selector
    ├── login.html
    ├── register.html
    ├── forgot_password.html
    ├── reset_password.html
    └── dashboard.html
```

---

## Configuration

| Setting | Value |
|---------|-------|
| Port | 5001 |
| Database | SQLite (voice2text.db) |
| Email | Mailtrap (sandbox.smtp.mailtrap.io) |
| HF_TOKEN | Set but requires user agreement at huggingface.co/pyannote/speaker-diarization-3.1 |
| SECRET_KEY | Auto-generated and configured |

---

## Feature Status

### ✅ Working
- User registration/login/logout
- Audio transcription with Whisper
- Language auto-detection (handles mixed English-Malay)
- Manual language selection (dropdown with 12 languages)
- File upload & history tracking
- Password reset via email
- User dashboard with stats

### ⚠️ Partially Working
- Speaker diarization - Code ready but needs HuggingFace user agreement to download models

### ❌ Known Issues
1. **Port conflicts** - May need to kill existing processes: `pkill -9 python`
2. **Database migrations** - If schema changes, need to delete `.db` file and recreate
3. **PyAnnote API** - Fixed token parameter compatibility issue

---

## Quick Start

```bash
cd "/Users/muhammadafdhaluddin/WORK/Codeflare Solution Sdn Bhd/VoiceToText"
source venv/bin/activate
pkill -9 python  # Clean up any hanging processes
python app.py    # Starts on http://127.0.0.1:5001
```

---

## Next Steps / Roadmap

### Immediate (Current Session)
1. Test speaker diarization after accepting HuggingFace agreement
2. Add database migrations (Flask-Migrate) instead of deleting DB
3. Fix "language detected as Malay only" issue for better mixed-language support

### Short-term
1. Switch from SQLite to PostgreSQL for production
2. Add background job queue (Celery) for async transcription
3. Implement file storage (S3) instead of local uploads
4. Add progress bar for long transcriptions
5. Export transcriptions (PDF, Word, TXT)

### Long-term (Scale)
1. Production WSGI server (Gunicorn)
2. Load balancing & auto-scaling
3. GPU instances for faster transcription
4. Redis caching
5. Microservices architecture

---

## Technical Stack

- **Web Framework:** Flask
- **Database:** SQLite (Flask-SQLAlchemy)
- **Authentication:** Flask-Login, Flask-Mail
- **Transcription:** OpenAI Whisper (base model)
- **Speaker Diarization:** PyAnnote speaker-diarization-3.1
- **Frontend:** HTML/CSS/JavaScript

---

## Scalability Considerations

**Current Architecture Limitations:**
- SQLite cannot handle concurrent writes
- No async processing - long transcriptions block the server
- File uploads stored locally
- Single-threaded development server

**Production Requirements for Scale:**
- PostgreSQL for concurrent database access
- Redis for caching and job queues
- Celery workers for async transcription processing
- Gunicorn with multiple workers
- Load balancer (nginx)
- Cloud storage (AWS S3 or equivalent)
- GPU instances for Whisper processing
- Container orchestration (Docker/Kubernetes)

---

## Dependencies

Key packages from `requirements.txt`:
- Flask 2.3.x
- Flask-SQLAlchemy 3.0.x
- Flask-Login 0.6.x
- Flask-Mail 0.9.x
- openai-whisper
- pyannote.audio 3.x
- torch / torchaudio
- python-dotenv

---

## API Endpoints

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/` | GET | Main transcription page | Yes |
| `/login` | GET/POST | User login | No |
| `/register` | GET/POST | User registration | No |
| `/logout` | GET | Logout user | Yes |
| `/forgot-password` | GET/POST | Request password reset | No |
| `/reset-password/<token>` | GET/POST | Reset password | No |
| `/dashboard` | GET | User dashboard | Yes |
| `/api/transcribe` | POST | Upload and transcribe audio | Yes |
| `/api/history` | GET | Get user's transcription history | Yes |
| `/api/history/<id>` | DELETE | Delete a transcription | Yes |

---

## Environment Variables

```bash
# Database
DATABASE_URL=sqlite:///voice2text.db

# Security
SECRET_KEY=your-generated-secret-key

# Email (Mailtrap)
MAIL_SERVER=sandbox.smtp.mailtrap.io
MAIL_PORT=2525
MAIL_USERNAME=your-mailtrap-username
MAIL_PASSWORD=your-mailtrap-password
MAIL_USE_TLS=True

# HuggingFace
HF_TOKEN=your-huggingface-token
```

---

## Notes

- Whisper base model can be upgraded to small/medium/large for better accuracy
- Database auto-creates tables on startup
- PyAnnote requires accepting user agreement at HuggingFace before first use
- Speaker diarization adds ~30-60 seconds processing time
