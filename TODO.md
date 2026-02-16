# Timeout Fix TODO

## Completed Changes

- [x] Made speaker diarization opt-in in `/api/transcribe` to reduce default request latency.
- [x] Added request duration logging in transcription flow for performance visibility.
- [x] Aligned Flask default port to `5000` (matches nginx upstream example).
- [x] Made Flask debug mode configurable with `FLASK_DEBUG`.
- [x] Added nginx + gunicorn timeout troubleshooting and config examples in `README.md`.

## Deployment Follow-up

- [ ] Apply nginx location timeout settings for `/api/transcribe`.
- [ ] Reload nginx after config update.
- [ ] Run app with Gunicorn timeout set to `600` seconds.
- [ ] Verify long audio transcription no longer returns `upstream timed out (110)`.

## Validation Done

- [x] Python syntax check passed: `python -m py_compile app.py`.