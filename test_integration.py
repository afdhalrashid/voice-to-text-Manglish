#!/usr/bin/env python3
"""
Integration test script for VoiceToText async functionality
"""
import requests
import time
import json
import sys
import tempfile
import os

BASE_URL = "http://localhost:5000"

def test_health():
    """Test health endpoint"""
    print("🩺 Testing health endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        if response.status_code == 200:
            print("✅ Health check passed")
            return True
        else:
            print(f"❌ Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False

def test_async_transcription():
    """Test async transcription workflow"""
    print("\n🎤 Testing async transcription workflow...")
    
    # Create a fake audio file for testing
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
        tmp_file.write(b'fake audio content for testing' * 100)  # Make it somewhat large
        tmp_file.flush()
        
        try:
            # Step 1: Submit async transcription job
            print("📤 Submitting transcription job...")
            with open(tmp_file.name, 'rb') as f:
                files = {'audio': ('test_audio.mp3', f, 'audio/mpeg')}
                data = {
                    'language': 'en',
                    'enable_diarization': 'false'
                }
                
                response = requests.post(f"{BASE_URL}/api/transcribe-async", 
                                       files=files, data=data, timeout=30)
            
            if response.status_code != 200:
                print(f"❌ Job submission failed: {response.status_code}")
                print(f"Response: {response.text}")
                return False
            
            job_data = response.json()
            job_id = job_data.get('job_id')
            
            if not job_id:
                print("❌ No job ID received")
                return False
            
            print(f"✅ Job submitted successfully: {job_id}")
            
            # Step 2: Monitor job status
            print(f"⏳ Monitoring job status...")
            max_wait_time = 60  # 1 minute max wait
            start_time = time.time()
            
            while time.time() - start_time < max_wait_time:
                status_response = requests.get(f"{BASE_URL}/api/jobs/{job_id}", timeout=10)
                
                if status_response.status_code != 200:
                    print(f"❌ Status check failed: {status_response.status_code}")
                    return False
                
                status_data = status_response.json()
                job_status = status_data.get('status')
                progress = status_data.get('progress', 0)
                
                print(f"📊 Job status: {job_status} ({progress}%)")
                
                if job_status == 'completed':
                    print("✅ Job completed successfully!")
                    
                    # Check if result data is available
                    if 'result' in status_data or status_data.get('result_data'):
                        result = status_data.get('result') or status_data.get('result_data')
                        print(f"📝 Transcription result preview: {str(result).get('transcription_text', 'No text')[:50]}...")
                        print("✅ Async transcription test passed!")
                        return True
                    else:
                        print("⚠️ Job completed but no result data found")
                        return False
                        
                elif job_status == 'failed':
                    error_msg = status_data.get('error_message', 'Unknown error')
                    print(f"❌ Job failed: {error_msg}")
                    return False
                    
                elif job_status in ['pending', 'processing']:
                    time.sleep(2)  # Wait 2 seconds before next check
                    continue
                else:
                    print(f"❌ Unknown job status: {job_status}")
                    return False
            
            print("❌ Job did not complete within time limit")
            return False
            
        except Exception as e:
            print(f"❌ Test error: {e}")
            return False
        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_file.name)
            except:
                pass

def test_job_listing():
    """Test job listing endpoint"""
    print("\n📋 Testing job listing...")
    try:
        response = requests.get(f"{BASE_URL}/api/jobs", timeout=10)
        if response.status_code == 200:
            data = response.json()
            jobs = data.get('jobs', [])
            print(f"✅ Found {len(jobs)} jobs")
            return True
        else:
            print(f"❌ Job listing failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Job listing error: {e}")
        return False

def test_transcription_history():
    """Test transcription history endpoint"""
    print("\n📚 Testing transcription history...")
    try:
        response = requests.get(f"{BASE_URL}/api/history", timeout=10)
        if response.status_code == 200:
            data = response.json()
            history = data.get('history', [])
            print(f"✅ Found {len(history)} transcription records")
            return True
        else:
            print(f"❌ History listing failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ History listing error: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 VoiceToText Async Integration Tests")
    print("=" * 50)
    
    tests = [
        test_health,
        test_job_listing,
        test_transcription_history,
        # Note: Async transcription test disabled by default as it requires Celery worker
        # test_async_transcription,
    ]
    
    passed = 0
    total = len(tests)
    
    for test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                print(f"❌ Test failed: {test_func.__name__}")
        except Exception as e:
            print(f"❌ Test error in {test_func.__name__}: {e}")
    
    print("\n" + "=" * 50)
    print(f"📊 Tests Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed")
        sys.exit(1)

if __name__ == "__main__":
    main()