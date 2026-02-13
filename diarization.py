"""
Speaker Diarization Module using PyAnnote.audio
Identifies 'who spoke when' in audio files
"""

import os
import torch
import logging
from typing import List, Dict, Tuple, Optional
import numpy as np

logger = logging.getLogger(__name__)


class SpeakerDiarizer:
    """
    Speaker diarization using PyAnnote models.
    Identifies different speakers and their time segments in audio.
    """

    def __init__(
        self, huggingface_token: Optional[str] = None, device: Optional[str] = None
    ):
        """
        Initialize the speaker diarizer.

        Args:
            huggingface_token: Hugging Face authentication token for model download
            device: Device to run on ('cuda', 'cpu', or None for auto)
        """
        self.pipeline = None
        self.huggingface_token = huggingface_token or os.environ.get("HF_TOKEN")
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    def load_model(self):
        """Load the PyAnnote speaker diarization pipeline"""
        if self.pipeline is not None:
            return self.pipeline

        try:
            from pyannote.audio import Pipeline

            logger.info("Loading PyAnnote speaker diarization pipeline...")

            # Use the pre-trained speaker diarization model
            # This requires Hugging Face authentication
            try:
                if self.huggingface_token:
                    # Try new API first (token parameter)
                    try:
                        self.pipeline = Pipeline.from_pretrained(
                            "pyannote/speaker-diarization-3.1",
                            token=self.huggingface_token,
                        )
                    except TypeError:
                        # Fall back to old API (use_auth_token parameter)
                        self.pipeline = Pipeline.from_pretrained(
                            "pyannote/speaker-diarization-3.1",
                            use_auth_token=self.huggingface_token,
                        )
                else:
                    # Try without token (might fail for some models)
                    self.pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1"
                    )
            except Exception as e:
                logger.error(f"Failed to load PyAnnote pipeline: {e}")
                logger.error("Please ensure you have:")
                logger.error(
                    "1. A valid Hugging Face token in HF_TOKEN environment variable"
                )
                logger.error(
                    "2. Accepted the user agreement at: https://huggingface.co/pyannote/speaker-diarization-3.1"
                )
                return None

            # Move to appropriate device
            self.pipeline.to(torch.device(self.device))

            logger.info(f"Speaker diarization pipeline loaded on {self.device}")
            return self.pipeline

        except Exception as e:
            logger.error(f"Failed to load PyAnnote pipeline: {str(e)}")
            logger.warning("Speaker diarization will be disabled")
            return None

    def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> List[Dict]:
        """
        Perform speaker diarization on audio file.

        Args:
            audio_path: Path to audio file
            num_speakers: Exact number of speakers (optional)
            min_speakers: Minimum number of speakers (optional)
            max_speakers: Maximum number of speakers (optional)

        Returns:
            List of segments with speaker labels and timestamps
        """
        pipeline = self.load_model()
        if pipeline is None:
            logger.warning(
                "Diarization pipeline not available, returning empty segments"
            )
            return []

        try:
            logger.info(f"Running speaker diarization on: {audio_path}")

            # Run diarization with optional parameters
            params = {}
            if num_speakers is not None:
                params["num_speakers"] = num_speakers
            if min_speakers is not None:
                params["min_speakers"] = min_speakers
            if max_speakers is not None:
                params["max_speakers"] = max_speakers

            diarization = pipeline(audio_path, **params)

            # Convert to list of segments
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(
                    {
                        "speaker": speaker,
                        "start": float(turn.start),
                        "end": float(turn.end),
                        "duration": float(turn.end - turn.start),
                    }
                )

            # Sort by start time
            segments.sort(key=lambda x: x["start"])

            logger.info(
                f"Diarization complete: {len(segments)} segments, "
                f"{len(set(s['speaker'] for s in segments))} speakers identified"
            )

            return segments

        except Exception as e:
            logger.error(f"Speaker diarization failed: {str(e)}")
            return []

    def merge_with_transcription(
        self, whisper_segments: List[Dict], diarization_segments: List[Dict]
    ) -> List[Dict]:
        """
        Merge Whisper transcription segments with speaker diarization.

        Args:
            whisper_segments: Transcription segments from Whisper
            diarization_segments: Speaker segments from diarization

        Returns:
            Combined segments with text and speaker labels
        """
        if not diarization_segments:
            # No diarization data, return original segments
            return whisper_segments

        merged_segments = []

        for whisper_seg in whisper_segments:
            # Get the middle timestamp of the whisper segment
            whisper_start = whisper_seg.get("start", 0)
            whisper_end = whisper_seg.get("end", whisper_start)
            whisper_mid = (whisper_start + whisper_end) / 2

            # Find the speaker for this time segment
            speaker = self._get_speaker_at_time(whisper_mid, diarization_segments)

            # Create merged segment
            merged_seg = whisper_seg.copy()
            merged_seg["speaker"] = speaker
            merged_segments.append(merged_seg)

        return merged_segments

    def _get_speaker_at_time(
        self, timestamp: float, diarization_segments: List[Dict]
    ) -> str:
        """
        Get the speaker label for a specific timestamp.

        Args:
            timestamp: Time in seconds
            diarization_segments: List of diarization segments

        Returns:
            Speaker label (e.g., 'SPEAKER_00', 'SPEAKER_01')
        """
        for seg in diarization_segments:
            if seg["start"] <= timestamp <= seg["end"]:
                return seg["speaker"]

        # If no match found, find closest speaker
        closest_speaker = "UNKNOWN"
        min_distance = float("inf")

        for seg in diarization_segments:
            # Distance to start or end of segment
            dist_to_start = abs(timestamp - seg["start"])
            dist_to_end = abs(timestamp - seg["end"])
            min_seg_distance = min(dist_to_start, dist_to_end)

            if min_seg_distance < min_distance:
                min_distance = min_seg_distance
                closest_speaker = seg["speaker"]

        return closest_speaker

    def get_speaker_summary(self, segments: List[Dict]) -> Dict:
        """
        Get summary statistics for each speaker.

        Args:
            segments: List of segments with speaker labels

        Returns:
            Dictionary with speaker statistics
        """
        speaker_stats = {}

        for seg in segments:
            speaker = seg.get("speaker", "UNKNOWN")

            if speaker not in speaker_stats:
                speaker_stats[speaker] = {
                    "total_time": 0,
                    "segment_count": 0,
                    "word_count": 0,
                }

            speaker_stats[speaker]["total_time"] += seg.get(
                "duration", seg.get("end", 0) - seg.get("start", 0)
            )
            speaker_stats[speaker]["segment_count"] += 1

            # Count words in text if available
            text = seg.get("text", "")
            if text:
                speaker_stats[speaker]["word_count"] += len(text.split())

        return speaker_stats


# Global diarizer instance (lazy loaded)
_diarizer = None


def get_diarizer():
    """Get or create global diarizer instance"""
    global _diarizer
    if _diarizer is None:
        _diarizer = SpeakerDiarizer()
    return _diarizer


def diarize_audio(audio_path: str, **kwargs) -> List[Dict]:
    """
    Convenience function to diarize audio.

    Args:
        audio_path: Path to audio file
        **kwargs: Additional arguments for diarization

    Returns:
        List of speaker segments
    """
    diarizer = get_diarizer()
    return diarizer.diarize(audio_path, **kwargs)
