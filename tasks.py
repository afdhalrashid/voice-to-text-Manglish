"""
Celery tasks for background processing
"""
import os
import time
import tempfile
import logging
from datetime import datetime, timedelta
from celery import Celery
import whisper
import numpy as np

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import models
from models import db, Job, TranscriptionHistory, JobStatus, User

# Initialize Celery
celery = Celery('voicetotext')

# Configure Celery from environment variables
celery.conf.update(
    broker_url=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    result_backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=int(os.environ.get('CELERY_TASK_TIMEOUT', 7200)),  # 2 hours
    task_soft_time_limit=int(os.environ.get('CELERY_TASK_TIMEOUT', 7200)) - 60,  # 2 hours - 1 minute
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1,  # Restart worker after each task to free memory
)

# Global model cache to avoid reloading
_whisper_model = None


def get_whisper_model(model_name="base"):
    """Get or load Whisper model with caching"""
    global _whisper_model
    if _whisper_model is None:
        logger.info(f"Loading Whisper model: {model_name}")
        start_time = time.time()
        _whisper_model = whisper.load_model(model_name)
        load_time = time.time() - start_time
        logger.info(f"Whisper model loaded in {load_time:.2f} seconds")
    return _whisper_model


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


@celery.task(bind=True, name='transcribe_audio_async')
def transcribe_audio_async(self, job_id, file_path, user_id, transcribe_params=None, diarization_params=None):
    """
    Async transcription task using Celery
    
    Args:
        job_id (str): Job ID for tracking
        file_path (str): Path to audio file
        user_id (int): User ID who submitted the job
        transcribe_params (dict): Whisper transcription parameters
        diarization_params (dict): Speaker diarization parameters
    """
    # Import app context within the task
    from app import app
    
    transcribe_params = transcribe_params or {}
    diarization_params = diarization_params or {}
    
    with app.app_context():
        job = Job.query.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return {"error": "Job not found"}
        
        try:
            # Update job status to processing
            job.update_status(JobStatus.PROCESSING.value, progress=10)
            job.celery_task_id = self.request.id
            db.session.commit()
            logger.info(f"Starting transcription for job {job_id}, file: {job.filename}")
            
            # Check if file exists
            if not os.path.exists(file_path):
                error_msg = f"Audio file not found: {file_path}"
                logger.error(error_msg)
                job.update_status(JobStatus.FAILED.value, progress=0, error_message=error_msg)
                db.session.commit()
                return {"error": error_msg}
            
            # Update progress
            job.update_status(JobStatus.PROCESSING.value, progress=20)
            db.session.commit()
            
            # Load Whisper model
            model_name = os.environ.get('WHISPER_MODEL', 'base')
            model = get_whisper_model(model_name)
            
            # Update progress
            job.update_status(JobStatus.PROCESSING.value, progress=30)
            db.session.commit()
            
            # Prepare transcription parameters
            default_params = {
                "fp16": False,
                "verbose": False,
                "task": "transcribe"
            }
            default_params.update(transcribe_params)
            
            # Perform transcription
            logger.info(f"Starting Whisper transcription with params: {default_params}")
            transcription_start = time.time()
            
            result = model.transcribe(file_path, **default_params)
            
            transcription_time = time.time() - transcription_start
            logger.info(f"Transcription completed in {transcription_time:.2f} seconds")
            
            # Update progress
            job.update_status(JobStatus.PROCESSING.value, progress=70)
            db.session.commit()
            
            # Convert numpy types to JSON serializable
            segments = make_json_serializable(result.get("segments", []))
            language = result.get("language", "unknown")
            if hasattr(language, "item"):
                language = str(language)
            
            # Extract transcription text
            text = result.get("text", "").strip()
            
            # Update progress
            job.update_status(JobStatus.PROCESSING.value, progress=80)
            db.session.commit()
            
            # Handle speaker diarization if requested
            speaker_segments = []
            speaker_summary = {}
            num_speakers = 0
            
            should_run_diarization = diarization_params.get('enable_diarization', False)
            
            if should_run_diarization:
                try:
                    logger.info("Starting speaker diarization...")
                    # Import diarization module
                    from diarization import get_diarizer
                    
                    diarizer = get_diarizer()
                    
                    # Run diarization
                    diarization_result = diarizer.diarize(
                        file_path,
                        num_speakers=diarization_params.get('num_speakers'),
                        min_speakers=diarization_params.get('min_speakers'),
                        max_speakers=diarization_params.get('max_speakers'),
                    )
                    
                    if diarization_result:
                        # Merge with transcription segments
                        segments = diarizer.merge_with_transcription(segments, diarization_result)
                        speaker_summary = diarizer.get_speaker_summary(segments)
                        num_speakers = len(set(s["speaker"] for s in diarization_result))
                        speaker_segments = diarization_result
                        
                        logger.info(f"Speaker diarization complete: {num_speakers} speakers identified")
                        
                except Exception as e:
                    logger.warning(f"Speaker diarization failed: {str(e)}")
                    # Continue without speaker identification
            
            # Update progress
            job.update_status(JobStatus.PROCESSING.value, progress=90)
            db.session.commit()
            
            # Prepare result data
            result_data = {
                "transcription_text": text,
                "language": language,
                "segments": segments,
                "speaker_segments": speaker_segments,
                "speaker_summary": speaker_summary,
                "num_speakers": num_speakers,
                "model_used": model_name,
                "processing_time": transcription_time,
                "file_size": job.file_size,
            }
            
            # Save to transcription history
            transcription_record = TranscriptionHistory(
                user_id=user_id,
                job_id=job_id,
                filename=job.filename,
                transcription_text=text,
                language=language,
                file_size=job.file_size or 0,
                processing_time=transcription_time,
                model_used=model_name,
                speaker_segments=speaker_segments,
                speaker_summary=speaker_summary,
                num_speakers=num_speakers,
            )
            
            db.session.add(transcription_record)
            
            # Update job with results
            job.result_data = result_data
            job.update_status(JobStatus.COMPLETED.value, progress=100)
            
            db.session.commit()
            
            # Clean up temporary file if it's in temp directory
            if file_path.startswith(tempfile.gettempdir()) or '/tmp/' in file_path:
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up temporary file: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not clean up temporary file {file_path}: {e}")
            
            logger.info(f"Job {job_id} completed successfully")
            return result_data
            
        except Exception as e:
            error_msg = f"Transcription failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            job.update_status(JobStatus.FAILED.value, progress=0, error_message=error_msg)
            db.session.commit()
            
            # Clean up file on error
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
                
            raise


@celery.task(name='cleanup_old_files')
def cleanup_old_files():
    """
    Periodic task to clean up old files and failed jobs
    """
    from app import app
    
    with app.app_context():
        logger.info("Starting cleanup of old files and jobs")
        
        # Clean up files older than FILE_CLEANUP_HOURS
        cleanup_hours = int(os.environ.get('FILE_CLEANUP_HOURS', 24))
        cutoff_time = datetime.utcnow() - timedelta(hours=cleanup_hours)
        
        # Find old completed/failed jobs
        old_jobs = Job.query.filter(
            Job.completed_at < cutoff_time,
            Job.status.in_([JobStatus.COMPLETED.value, JobStatus.FAILED.value])
        ).all()
        
        for job in old_jobs:
            try:
                # Remove file if it exists
                if job.file_path and os.path.exists(job.file_path):
                    os.remove(job.file_path)
                    logger.info(f"Cleaned up file: {job.file_path}")
            except Exception as e:
                logger.warning(f"Could not clean up file {job.file_path}: {e}")
        
        logger.info(f"Cleanup completed. Processed {len(old_jobs)} old jobs")
        return {"cleaned_jobs": len(old_jobs)}


# Configure periodic tasks
celery.conf.beat_schedule = {
    'cleanup-old-files': {
        'task': 'cleanup_old_files',
        'schedule': 3600.0,  # Run every hour
    },
}