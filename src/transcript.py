"""
Transcript Extraction Module.

Saves transcripts to local files (not Google Sheets).
Google Sheets only gets the file path reference.

Storage: data/transcripts/{channel_name}/{video_id}.txt
"""

import json
from pathlib import Path
from typing import Optional

from loguru import logger
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from src.models import VideoMetadata, TranscriptData, TranscriptResult


class TranscriptExtractor:
    """Extracts YouTube transcripts and saves them to local files."""

    def __init__(
        self,
        preferred_languages: list[str] = None,
        fallback_to_auto: bool = True,
        chunk_size: int = 5000,
        transcripts_dir: str = "data/transcripts",
    ):
        self.preferred_languages = preferred_languages or ["en", "hi"]
        self.fallback_to_auto = fallback_to_auto
        self.chunk_size = chunk_size
        self.transcripts_dir = Path(transcripts_dir)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.api = YouTubeTranscriptApi()

    def get_transcript(self, video: VideoMetadata) -> Optional[TranscriptData]:
        """
        Fetch transcript for a video.
        Returns full TranscriptData for in-memory processing.
        """
        try:
            transcript_list = self.api.list(video.video_id)

            transcript = None
            is_auto = False

            # Try manual transcript first
            try:
                transcript = transcript_list.find_manually_created_transcript(
                    self.preferred_languages
                )
            except NoTranscriptFound:
                if self.fallback_to_auto:
                    try:
                        transcript = transcript_list.find_generated_transcript(
                            self.preferred_languages
                        )
                        is_auto = True
                    except NoTranscriptFound:
                        # Try any available
                        try:
                            available = list(transcript_list)
                            if available:
                                transcript = available[0]
                                is_auto = transcript.is_generated
                        except Exception:
                            pass

            if transcript is None:
                logger.warning(f"No transcript: {video.title} ({video.video_id})")
                return None

            # Fetch transcript segments (v1.x API returns FetchedTranscript)
            fetched = transcript.fetch()
            full_text = " ".join(snippet.text for snippet in fetched.snippets)
            full_text = self._clean_text(full_text)
            chunks = self._chunk_text(full_text)

            result = TranscriptData(
                video_id=video.video_id,
                language=transcript.language_code,
                is_auto_generated=is_auto,
                full_text=full_text,
                chunks=chunks,
            )

            logger.info(
                f"Transcript: {video.title[:40]}... "
                f"({result.word_count} words, {'auto' if is_auto else 'manual'})"
            )
            return result

        except TranscriptsDisabled:
            logger.warning(f"Transcripts disabled: {video.title}")
            return None
        except VideoUnavailable:
            logger.warning(f"Video unavailable: {video.title}")
            return None
        except Exception as e:
            logger.error(f"Transcript error for {video.video_id}: {e}")
            return None

    def save_transcript(self, video: VideoMetadata, transcript: TranscriptData) -> str:
        """
        Save transcript to a local file.
        Returns the file path (this goes into Google Sheets, not the text).
        """
        channel_dir = self.transcripts_dir / video.channel_name.lower().replace(" ", "_")
        channel_dir.mkdir(exist_ok=True)

        # Save as plain text (for reading) + JSON metadata
        txt_path = channel_dir / f"{video.video_id}.txt"
        meta_path = channel_dir / f"{video.video_id}.json"

        # Plain text transcript
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"Title: {video.title}\n")
            f.write(f"Channel: {video.channel_name}\n")
            f.write(f"URL: {video.url}\n")
            f.write(f"Date: {video.published_at}\n")
            f.write(f"Language: {transcript.language}\n")
            f.write(f"Words: {transcript.word_count}\n")
            f.write(f"{'='*60}\n\n")
            f.write(transcript.full_text)

        # JSON metadata
        meta = {
            "video_id": video.video_id,
            "title": video.title,
            "channel": video.channel_name,
            "language": transcript.language,
            "is_auto_generated": transcript.is_auto_generated,
            "word_count": transcript.word_count,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # Return relative path for Google Sheets reference
        rel_path = str(txt_path).replace("\\", "/")
        return rel_path

    def load_transcript(self, video_id: str, channel_name: str) -> Optional[TranscriptData]:
        """Load a previously saved transcript from file."""
        channel_dir = self.transcripts_dir / channel_name.lower().replace(" ", "_")
        txt_path = channel_dir / f"{video_id}.txt"

        if not txt_path.exists():
            return None

        with open(txt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Skip header lines (first 7 lines are metadata)
        text_start = 0
        for i, line in enumerate(lines):
            if line.startswith("=" * 10):
                text_start = i + 2  # skip separator + blank line
                break

        full_text = "".join(lines[text_start:]).strip()

        # Read metadata
        meta_path = channel_dir / f"{video_id}.json"
        language = "en"
        is_auto = False
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                language = meta.get("language", "en")
                is_auto = meta.get("is_auto_generated", False)

        return TranscriptData(
            video_id=video_id,
            language=language,
            is_auto_generated=is_auto,
            full_text=full_text,
            chunks=self._chunk_text(full_text),
        )

    def has_transcript(self, video_id: str, channel_name: str) -> bool:
        """Check if transcript already exists locally."""
        channel_dir = self.transcripts_dir / channel_name.lower().replace(" ", "_")
        return (channel_dir / f"{video_id}.txt").exists()

    def _clean_text(self, text: str) -> str:
        """Clean transcript artifacts."""
        text = " ".join(text.split())
        text = text.replace("[Music]", "").replace("[Applause]", "")
        text = text.replace("[Laughter]", "").replace("&amp;", "&")
        return text.strip()

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks for AI processing."""
        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        words = text.split()
        current_chunk = []
        current_length = 0

        for word in words:
            word_len = len(word) + 1
            if current_length + word_len > self.chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = [word]
                current_length = word_len
            else:
                current_chunk.append(word)
                current_length += word_len

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks
