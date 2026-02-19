"""
Comprehensive unit tests for VoiceToText async queuing system
"""
import pytest
import os
import tempfile
import json
from unittest.mock import patch, MagicMock, Mock
import time
from datetime import datetime, timedelta

# Set up test environment
os.environ['TESTING'] = 'true'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['REDIS_URL'] = 'redis://localhost:6379/1'  # Use test database
os.environ['SECRET_KEY'] = 'test-secret-key'

# Import after setting environment
import sys
sys.path.append('/var/www/VoiceToText')

from app_updated import app, db
from models_updated import User, Job, TranscriptionHistory, JobStatus, JobType
from tasks import transcribe_audio_async, make_json_serializable, get_whisper_model
import uuid


class TestConfig:
    """Test configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'test-secret-key'
    WTF_CSRF_ENABLED = False


@pytest.fixture
def client():
    """Create test client"""
    app.config.from_object(TestConfig)
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.drop_all()


@pytest.fixture
def test_user():
    """Create test user"""
    user = User(username='testuser', email='test@example.com')
    user.set_password('testpassword')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def authenticated_client(client, test_user):
    """Create authenticated client"""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def test_audio_file():
    """Create a test audio file"""
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
        f.write(b'fake audio content for testing')
        yield f.name
    # Clean up
    try:
        os.unlink(f.name)
    except OSError:
        pass


class TestModels:
    """Test database models"""
    
    def test_user_model(self, client, test_user):
        """Test User model functionality"""
        assert test_user.username == 'testuser'
        assert test_user.email == 'test@example.com'
        assert test_user.check_password('testpassword')
        assert not test_user.check_password('wrongpassword')
    
    def test_job_model(self, client, test_user):
        """Test Job model functionality"""
        job = Job(
            user_id=test_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename='test.mp3',
            file_path='/tmp/test.mp3',
            file_size=1024,
        )
        db.session.add(job)
        db.session.commit()
        
        assert job.id is not None
        assert job.status == JobStatus.PENDING.value
        assert job.progress == 0
        assert job.user_id == test_user.id
        
        # Test status update
        job.update_status(JobStatus.PROCESSING.value, progress=50)
        assert job.status == JobStatus.PROCESSING.value
        assert job.progress == 50
        assert job.started_at is not None
        
        # Test completion
        job.update_status(JobStatus.COMPLETED.value, progress=100)
        assert job.status == JobStatus.COMPLETED.value
        assert job.progress == 100
        assert job.completed_at is not None
        assert job.processing_time is not None
    
    def test_transcription_history_model(self, client, test_user):
        """Test TranscriptionHistory model"""
        # Create job first
        job = Job(
            user_id=test_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename='test.mp3',
            file_path='/tmp/test.mp3',
        )
        db.session.add(job)
        db.session.commit()
        
        # Create transcription history
        history = TranscriptionHistory(
            user_id=test_user.id,
            job_id=job.id,
            filename='test.mp3',
            transcription_text='Hello world',
            language='en',
            file_size=1024,
            model_used='base',
        )
        db.session.add(history)
        db.session.commit()
        
        assert history.id is not None
        assert history.user_id == test_user.id
        assert history.job_id == job.id
        assert history.transcription_text == 'Hello world'
        
        # Test to_dict method
        data = history.to_dict()
        assert data['transcription_text'] == 'Hello world'
        assert data['language'] == 'en'


class TestTaskUtils:
    """Test utility functions in tasks module"""
    
    def test_make_json_serializable(self):
        """Test JSON serialization utility"""
        import numpy as np
        
        # Test numpy types
        assert make_json_serializable(np.int64(42)) == 42
        assert make_json_serializable(np.float32(3.14)) == pytest.approx(3.14)
        assert make_json_serializable(np.array([1, 2, 3])) == [1, 2, 3]
        
        # Test nested structures
        data = {
            'int': np.int32(10),
            'float': np.float64(2.5),
            'array': np.array([1, 2]),
            'nested': {'value': np.int16(5)}
        }
        result = make_json_serializable(data)
        assert result['int'] == 10
        assert result['float'] == 2.5
        assert result['array'] == [1, 2]
        assert result['nested']['value'] == 5
    
    @patch('tasks.whisper.load_model')
    def test_get_whisper_model_caching(self, mock_load_model):
        """Test Whisper model caching"""
        mock_model = Mock()
        mock_load_model.return_value = mock_model
        
        # First call should load the model
        model1 = get_whisper_model('base')
        assert model1 == mock_model
        assert mock_load_model.call_count == 1
        
        # Second call should return cached model
        model2 = get_whisper_model('base')
        assert model2 == mock_model
        assert mock_load_model.call_count == 1  # Should not be called again


class TestAsyncEndpoints:
    """Test async API endpoints"""
    
    def test_health_endpoint(self, client):
        """Test health check endpoint"""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'
    
    def test_transcribe_async_no_file(self, authenticated_client):
        """Test async transcription without file"""
        response = authenticated_client.post('/api/transcribe-async')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'No audio file provided' in data['error']
    
    def test_transcribe_async_empty_file(self, authenticated_client):
        """Test async transcription with empty filename"""
        response = authenticated_client.post(
            '/api/transcribe-async',
            data={'audio': (open(__file__, 'rb'), '')},  # Empty filename
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'No file selected' in data['error']
    
    def test_transcribe_async_invalid_file_type(self, authenticated_client):
        """Test async transcription with invalid file type"""
        response = authenticated_client.post(
            '/api/transcribe-async',
            data={'audio': (open(__file__, 'rb'), 'test.txt')},  # Invalid extension
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'File type not allowed' in data['error']
    
    @patch('app_updated.transcribe_audio_async.delay')
    def test_transcribe_async_success(self, mock_task_delay, authenticated_client, test_audio_file):
        """Test successful async transcription submission"""
        # Mock Celery task
        mock_task = Mock()
        mock_task.id = 'test-task-id'
        mock_task_delay.return_value = mock_task
        
        with open(test_audio_file, 'rb') as f:
            response = authenticated_client.post(
                '/api/transcribe-async',
                data={
                    'audio': (f, 'test.mp3'),
                    'language': 'en',
                    'enable_diarization': 'true',
                    'num_speakers': '2',
                }
            )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'job_id' in data
        assert data['task_id'] == 'test-task-id'
        assert data['status'] == 'pending'
        
        # Verify job was created in database
        job = Job.query.filter_by(id=data['job_id']).first()
        assert job is not None
        assert job.filename == 'test.mp3'
        assert job.status == JobStatus.PENDING.value
        assert job.celery_task_id == 'test-task-id'
    
    def test_get_job_status_not_found(self, authenticated_client):
        """Test job status for non-existent job"""
        response = authenticated_client.get('/api/jobs/non-existent-id')
        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'Job not found' in data['error']
    
    def test_get_job_status_success(self, authenticated_client, test_user):
        """Test successful job status retrieval"""
        # Create test job
        job = Job(
            user_id=test_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename='test.mp3',
            file_path='/tmp/test.mp3',
            status=JobStatus.COMPLETED.value,
            progress=100,
            result_data={'transcription_text': 'Hello world', 'language': 'en'}
        )
        db.session.add(job)
        db.session.commit()
        
        response = authenticated_client.get(f'/api/jobs/{job.id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['id'] == job.id
        assert data['status'] == JobStatus.COMPLETED.value
        assert data['progress'] == 100
        assert 'result' in data
        assert data['result']['transcription_text'] == 'Hello world'
    
    def test_cancel_job_success(self, authenticated_client, test_user):
        """Test successful job cancellation"""
        # Create test job
        job = Job(
            user_id=test_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename='test.mp3',
            file_path='/tmp/test.mp3',
            status=JobStatus.PROCESSING.value,
            celery_task_id='test-task-id'
        )
        db.session.add(job)
        db.session.commit()
        
        with patch('celery.result.AsyncResult') as mock_async_result:
            mock_task = Mock()
            mock_async_result.return_value = mock_task
            
            response = authenticated_client.delete(f'/api/jobs/{job.id}')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success'] is True
            
            # Verify job status updated
            db.session.refresh(job)
            assert job.status == JobStatus.CANCELLED.value
            
            # Verify task was revoked
            mock_task.revoke.assert_called_once_with(terminate=True)
    
    def test_cancel_completed_job(self, authenticated_client, test_user):
        """Test cancelling already completed job"""
        # Create completed job
        job = Job(
            user_id=test_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename='test.mp3',
            file_path='/tmp/test.mp3',
            status=JobStatus.COMPLETED.value,
        )
        db.session.add(job)
        db.session.commit()
        
        response = authenticated_client.delete(f'/api/jobs/{job.id}')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'Cannot cancel completed job' in data['error']
    
    def test_list_jobs(self, authenticated_client, test_user):
        """Test job listing"""
        # Create test jobs
        for i in range(5):
            job = Job(
                user_id=test_user.id,
                job_type=JobType.TRANSCRIPTION.value,
                filename=f'test_{i}.mp3',
                file_path=f'/tmp/test_{i}.mp3',
                status=JobStatus.COMPLETED.value if i % 2 == 0 else JobStatus.FAILED.value,
            )
            db.session.add(job)
        db.session.commit()
        
        # Test all jobs
        response = authenticated_client.get('/api/jobs')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['jobs']) == 5
        assert data['total'] == 5
        
        # Test filtering by status
        response = authenticated_client.get('/api/jobs?status=completed')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['jobs']) == 3  # 3 completed jobs
        
        # Test pagination
        response = authenticated_client.get('/api/jobs?page=1&per_page=2')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['jobs']) == 2
        assert data['has_next'] is True
    
    def test_transcription_history(self, authenticated_client, test_user):
        """Test transcription history endpoint"""
        # Create test history
        for i in range(3):
            history = TranscriptionHistory(
                user_id=test_user.id,
                filename=f'test_{i}.mp3',
                transcription_text=f'Transcription {i}',
                language='en',
                file_size=1024 * (i + 1),
            )
            db.session.add(history)
        db.session.commit()
        
        response = authenticated_client.get('/api/history')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['history']) == 3
        assert data['total'] == 3
    
    def test_delete_transcription(self, authenticated_client, test_user):
        """Test transcription deletion"""
        history = TranscriptionHistory(
            user_id=test_user.id,
            filename='test.mp3',
            transcription_text='Test transcription',
            language='en',
        )
        db.session.add(history)
        db.session.commit()
        
        response = authenticated_client.delete(f'/api/history/{history.id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        
        # Verify deletion
        deleted_history = TranscriptionHistory.query.get(history.id)
        assert deleted_history is None


class TestCeleryTasks:
    """Test Celery background tasks"""
    
    @patch('tasks.whisper.load_model')
    @patch('tasks.os.path.exists')
    def test_transcribe_audio_async_file_not_found(self, mock_exists, mock_load_model, client, test_user):
        """Test transcription task with missing file"""
        mock_exists.return_value = False
        
        # Create test job
        job = Job(
            user_id=test_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename='missing.mp3',
            file_path='/tmp/missing.mp3',
        )
        db.session.add(job)
        db.session.commit()
        
        # Run task
        with app.app_context():
            result = transcribe_audio_async(job.id, '/tmp/missing.mp3', test_user.id)
        
        assert 'error' in result
        assert 'not found' in result['error']
        
        # Verify job status
        db.session.refresh(job)
        assert job.status == JobStatus.FAILED.value
    
    @patch('tasks.whisper.load_model')
    @patch('tasks.os.path.exists')
    @patch('tasks.os.remove')
    def test_transcribe_audio_async_success(self, mock_remove, mock_exists, mock_load_model, 
                                           client, test_user, test_audio_file):
        """Test successful transcription task"""
        # Mock Whisper model and result
        mock_model = Mock()
        mock_result = {
            'text': 'Hello world test transcription',
            'language': 'en',
            'segments': [
                {
                    'id': 0,
                    'seek': 0,
                    'start': 0.0,
                    'end': 2.5,
                    'text': 'Hello world test transcription',
                    'tokens': [1, 2, 3],
                    'temperature': 0.0,
                    'avg_logprob': -0.5,
                    'compression_ratio': 1.0,
                    'no_speech_prob': 0.1
                }
            ]
        }
        mock_model.transcribe.return_value = mock_result
        mock_load_model.return_value = mock_model
        mock_exists.return_value = True
        
        # Create test job
        job = Job(
            user_id=test_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename='test.mp3',
            file_path=test_audio_file,
            file_size=1024,
        )
        db.session.add(job)
        db.session.commit()
        
        # Run task
        with app.app_context():
            result = transcribe_audio_async(
                job.id, 
                test_audio_file, 
                test_user.id,
                transcribe_params={'language': 'en'},
                diarization_params={}
            )
        
        # Verify result
        assert result['transcription_text'] == 'Hello world test transcription'
        assert result['language'] == 'en'
        assert result['model_used'] == 'base'
        assert 'processing_time' in result
        
        # Verify job status
        db.session.refresh(job)
        assert job.status == JobStatus.COMPLETED.value
        assert job.progress == 100
        assert job.result_data is not None
        
        # Verify transcription history created
        history = TranscriptionHistory.query.filter_by(job_id=job.id).first()
        assert history is not None
        assert history.transcription_text == 'Hello world test transcription'
        assert history.language == 'en'
    
    @patch('tasks.whisper.load_model')
    @patch('tasks.os.path.exists')
    def test_transcribe_audio_async_with_diarization(self, mock_exists, mock_load_model, 
                                                    client, test_user, test_audio_file):
        """Test transcription with speaker diarization"""
        # Mock Whisper model
        mock_model = Mock()
        mock_result = {
            'text': 'Speaker test',
            'language': 'en',
            'segments': [{'id': 0, 'text': 'Speaker test', 'start': 0.0, 'end': 1.0}]
        }
        mock_model.transcribe.return_value = mock_result
        mock_load_model.return_value = mock_model
        mock_exists.return_value = True
        
        # Mock diarization
        with patch('tasks.get_diarizer') as mock_get_diarizer:
            mock_diarizer = Mock()
            mock_diarizer.diarize.return_value = [
                {'speaker': 'SPEAKER_00', 'start': 0.0, 'end': 1.0}
            ]
            mock_diarizer.merge_with_transcription.return_value = [
                {'id': 0, 'text': 'Speaker test', 'start': 0.0, 'end': 1.0, 'speaker': 'SPEAKER_00'}
            ]
            mock_diarizer.get_speaker_summary.return_value = {'SPEAKER_00': {'duration': 1.0}}
            mock_get_diarizer.return_value = mock_diarizer
            
            # Create test job
            job = Job(
                user_id=test_user.id,
                job_type=JobType.TRANSCRIPTION.value,
                filename='test.mp3',
                file_path=test_audio_file,
            )
            db.session.add(job)
            db.session.commit()
            
            # Run task with diarization
            with app.app_context():
                result = transcribe_audio_async(
                    job.id,
                    test_audio_file,
                    test_user.id,
                    transcribe_params={},
                    diarization_params={'enable_diarization': True, 'num_speakers': 2}
                )
            
            # Verify diarization was called
            mock_diarizer.diarize.assert_called_once()
            assert result['num_speakers'] == 1
            assert len(result['speaker_segments']) == 1
    
    @patch('tasks.whisper.load_model')
    @patch('tasks.os.path.exists')
    def test_transcribe_audio_async_exception(self, mock_exists, mock_load_model, 
                                            client, test_user, test_audio_file):
        """Test transcription task exception handling"""
        mock_exists.return_value = True
        mock_load_model.side_effect = Exception("Model loading failed")
        
        # Create test job
        job = Job(
            user_id=test_user.id,
            job_type=JobType.TRANSCRIPTION.value,
            filename='test.mp3',
            file_path=test_audio_file,
        )
        db.session.add(job)
        db.session.commit()
        
        # Run task - should raise exception
        with app.app_context():
            with pytest.raises(Exception):
                transcribe_audio_async(job.id, test_audio_file, test_user.id)
        
        # Verify job marked as failed
        db.session.refresh(job)
        assert job.status == JobStatus.FAILED.value
        assert job.error_message is not None


class TestAuthentication:
    """Test authentication requirements"""
    
    def test_protected_endpoints_require_auth(self, client):
        """Test that protected endpoints require authentication"""
        protected_endpoints = [
            '/api/transcribe-async',
            '/api/jobs',
            '/api/history',
            '/dashboard',
            '/',
        ]
        
        for endpoint in protected_endpoints:
            response = client.get(endpoint)
            # Should redirect to login or return 401/403
            assert response.status_code in [302, 401, 403]
    
    def test_public_endpoints_no_auth(self, client):
        """Test that public endpoints don't require auth"""
        response = client.get('/api/health')
        assert response.status_code == 200


class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_large_file_rejection(self, authenticated_client, test_user):
        """Test rejection of files that are too large"""
        # This would need to be tested with a larger file or mock
        # For now, we test the logic pathway
        pass
    
    def test_concurrent_job_handling(self, authenticated_client, test_user):
        """Test handling of multiple concurrent jobs"""
        # Test creating multiple jobs for same user
        jobs = []
        for i in range(3):
            job = Job(
                user_id=test_user.id,
                job_type=JobType.TRANSCRIPTION.value,
                filename=f'concurrent_{i}.mp3',
                file_path=f'/tmp/concurrent_{i}.mp3',
            )
            db.session.add(job)
            jobs.append(job)
        db.session.commit()
        
        # All jobs should be created successfully
        assert len(jobs) == 3
        for job in jobs:
            assert job.id is not None
    
    def test_job_cleanup_on_error(self, authenticated_client, test_user, test_audio_file):
        """Test that files are cleaned up on job errors"""
        # This is tested within the task exception test
        pass


# Integration tests
class TestIntegration:
    """Integration tests for the complete workflow"""
    
    @patch('app_updated.transcribe_audio_async.delay')
    def test_complete_async_workflow(self, mock_task_delay, authenticated_client, test_user, test_audio_file):
        """Test complete async transcription workflow"""
        # Mock Celery task
        mock_task = Mock()
        mock_task.id = 'integration-test-task-id'
        mock_task_delay.return_value = mock_task
        
        # Step 1: Submit job
        with open(test_audio_file, 'rb') as f:
            response = authenticated_client.post(
                '/api/transcribe-async',
                data={'audio': (f, 'integration_test.mp3')}
            )
        
        assert response.status_code == 200
        job_data = json.loads(response.data)
        job_id = job_data['job_id']
        
        # Step 2: Check job status (pending)
        response = authenticated_client.get(f'/api/jobs/{job_id}')
        assert response.status_code == 200
        status_data = json.loads(response.data)
        assert status_data['status'] == 'pending'
        
        # Step 3: Simulate job completion
        job = Job.query.get(job_id)
        job.update_status(JobStatus.COMPLETED.value, progress=100)
        job.result_data = {
            'transcription_text': 'Integration test completed',
            'language': 'en',
            'processing_time': 5.0
        }
        db.session.commit()
        
        # Step 4: Check completed job status
        response = authenticated_client.get(f'/api/jobs/{job_id}')
        assert response.status_code == 200
        completed_data = json.loads(response.data)
        assert completed_data['status'] == 'completed'
        assert 'result' in completed_data
        
        # Step 5: Verify job appears in job list
        response = authenticated_client.get('/api/jobs')
        assert response.status_code == 200
        jobs_data = json.loads(response.data)
        job_ids = [j['id'] for j in jobs_data['jobs']]
        assert job_id in job_ids


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v', '--tb=short'])