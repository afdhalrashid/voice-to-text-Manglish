# Voice to Text Converter

A web application that converts uploaded voice recordings to text, with excellent support for Malay language, English, and mixed language speech (including slang).

## Features

- 🎤 Upload audio files in various formats (MP3, WAV, M4A, OGG, FLAC, WEBM, MP4, WMA, AAC)
- 🌏 Optimized for Malay language with support for English and mixed speech
- 🎯 Handles slang and casual speech patterns
- 📋 Copy transcription results to clipboard
- 🎨 Modern, responsive UI with drag-and-drop support
- ⚡ Fast and accurate transcription using OpenAI Whisper

## Requirements

- Python 3.8 or higher
- pip (Python package manager)
- **ffmpeg** (required by Whisper for audio decoding)

## Installation

1. **Install ffmpeg** (required for transcription):
   - **macOS (Homebrew):** `brew install ffmpeg`
   - **Ubuntu/Debian:** `sudo apt install ffmpeg`
   - **Windows:** Download from [ffmpeg.org](https://ffmpeg.org/download.html) or use `winget install ffmpeg`

2. **Clone or navigate to the project directory:**
   ```bash
   cd VoiceToText
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

   Note: The first time you run the app, Whisper will download the model (~150MB for base model). This happens automatically.

## Usage

1. **Start the Flask server:**
   ```bash
   python app.py
   ```

2. **Open your browser and navigate to:**
   ```
   http://localhost:5000
   ```

3. **Upload an audio file:**
   - Click the upload area or drag and drop an audio file
   - Click "Transcribe Audio" button
   - Wait for processing (may take a few seconds to minutes depending on file size)
   - View the transcription result
   - Copy the text to clipboard if needed

## API Endpoints

### Health Check
```
GET /api/health
```
Returns API status.

### Transcribe Audio
```
POST /api/transcribe
Content-Type: multipart/form-data

Form data:
- audio: (file) Audio file to transcribe
```

**Response:**
```json
{
  "success": true,
  "text": "Transcribed text here...",
  "language": "ms",
  "segments": [...]
}
```

## Model Options

The app uses Whisper's `base` model by default. You can change this in `app.py`:

- `tiny` - Fastest, least accurate (~39M parameters)
- `base` - Good balance (default, ~74M parameters)
- `small` - Better accuracy (~244M parameters)
- `medium` - High accuracy (~769M parameters)
- `large` - Best accuracy (~1550M parameters)

To change the model, edit line 25 in `app.py`:
```python
model = whisper.load_model("base")  # Change "base" to your preferred model
```

## Supported Audio Formats

- MP3
- WAV
- M4A
- OGG
- FLAC
- WEBM
- MP4
- WMA
- AAC

Maximum file size: 100MB

## Deployment (server)

When you deploy to a server, **ffmpeg must be installed on that server** or transcription will fail with `No such file or directory: 'ffmpeg'`.

**On the server**, run one of the following (depending on OS):

- **Ubuntu / Debian:**
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```
- **CentOS / RHEL / Fedora:**
  ```bash
  sudo yum install -y ffmpeg
  ```
  or (Fedora/newer RHEL): `sudo dnf install -y ffmpeg`
- **Alpine (e.g. minimal Docker):**
  ```bash
  apk add --no-cache ffmpeg
  ```

Then install Python dependencies and run the app as usual. Restart the app after installing ffmpeg.

**Alternatively**, use the included Docker setup so ffmpeg is installed in the image:
```bash
docker build -t voicetotext .
docker run -p 5000:5000 voicetotext
```

## Troubleshooting

### Transcription failed: No such file or directory: 'ffmpeg'
The server (or container) where the app runs does not have ffmpeg installed. Install ffmpeg on the server — see [Deployment (server)](#deployment-server) above.

### Model download issues
If the model fails to download automatically, you can manually download it:
```bash
python -c "import whisper; whisper.load_model('base')"
```

### Port already in use
Change the port in `app.py`:
```python
port = int(os.environ.get('PORT', 5000))  # Change 5000 to another port
```

### Memory issues
If you encounter memory errors with large files:
1. Use a smaller Whisper model (e.g., `tiny` or `base`)
2. Split large audio files into smaller chunks
3. Increase system RAM

## Performance Tips

- **Faster processing:** Use `tiny` or `base` models
- **Better accuracy:** Use `small`, `medium`, or `large` models
- **Large files:** Consider splitting into smaller chunks for faster processing

## License

This project is open source and available for personal and commercial use.

## Acknowledgments

- Built with [OpenAI Whisper](https://github.com/openai/whisper)
- Flask web framework
- Modern web technologies
