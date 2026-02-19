"""
Celery worker configuration for VoiceToText application
"""
import os
from celery import Celery
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def make_celery(app_name=__name__):
    """Create and configure Celery instance"""
    celery = Celery(app_name)
    
    # Configure Celery
    celery.conf.update(
        broker_url=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        result_backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_track_started=True,
        task_time_limit=int(os.environ.get('CELERY_TASK_TIMEOUT', 1800)),  # 30 minutes
        task_soft_time_limit=int(os.environ.get('CELERY_TASK_TIMEOUT', 1800)) - 60,  # 29 minutes
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=1,  # Restart worker after each task to free memory
        worker_concurrency=int(os.environ.get('CELERY_WORKER_CONCURRENCY', 2)),
        task_routes={
            'transcribe_audio_async': 'transcription',
            'cleanup_old_files': 'maintenance',
        },
    )
    
    # Import tasks to register them
    from tasks import transcribe_audio_async, cleanup_old_files
    
    return celery

if __name__ == '__main__':
    celery = make_celery()
    celery.start()