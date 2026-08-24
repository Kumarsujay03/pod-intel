"""
Data models for the YouTube Knowledge Pipeline.
Matches the EPISODES sheet structure from scale.md architecture.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ChannelConfig:
    """Configuration for a YouTube channel."""
    name: str
    channel_handle: str
    channel_id: str
    enabled: bool = True
    fo_prefix: str = "EP"
    max_videos: int = 0  # 0 = ALL (no limit)
    since_date: str = ""  # YYYY-MM-DD or empty for all time
    filter_shorts: bool = True  # Skip shorts by default
    min_duration_minutes: int = 0  # Minimum video length in minutes


@dataclass
class VideoMetadata:
    """Raw metadata collected from YouTube."""
    video_id: str
    channel_id: str
    channel_name: str
    title: str
    url: str
    published_at: str
    duration: str
    description: str
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    thumbnail_url: str = ""

    @property
    def short_url(self) -> str:
        return f"https://youtu.be/{self.video_id}"


@dataclass
class TranscriptResult:
    """Result of transcript extraction - stores path reference, not full text."""
    video_id: str
    language: str
    is_auto_generated: bool
    transcript_path: str  # Path to saved transcript file
    word_count: int = 0


@dataclass
class TranscriptData:
    """Full transcript data (used in-memory during processing, NOT stored in sheets)."""
    video_id: str
    language: str
    is_auto_generated: bool
    full_text: str
    chunks: list = field(default_factory=list)
    word_count: int = 0

    def __post_init__(self):
        if self.full_text and not self.word_count:
            self.word_count = len(self.full_text.split())


@dataclass
class OllamaClassification:
    """
    Ollama output — bulk/local processing.
    Handles: category, subcategory, topics, tags, relevance, summary, guest type.
    """
    primary_category: str = ""
    subcategory: str = ""
    topics: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    relevance_score: float = 0.0
    summary: str = ""
    guest_type: str = ""  # e.g., "Entrepreneur", "Investor", "Solo Episode"


@dataclass
class NvidiaAnalysis:
    """
    NVIDIA output — deep analysis for important episodes only.
    Full transcript analysis, key insights, arguments, business lessons.
    """
    detailed_summary: str = ""
    key_insights: list = field(default_factory=list)
    important_arguments: list = field(default_factory=list)
    contradictory_viewpoints: list = field(default_factory=list)
    business_lessons: list = field(default_factory=list)
    technical_explanations: list = field(default_factory=list)
    claims_to_verify: list = field(default_factory=list)
    major_themes: list = field(default_factory=list)


@dataclass
class Episode:
    """
    Fully processed episode matching the EPISODES sheet structure.
    
    Columns in Google Sheets:
    FO_ID | Guest | Title | YouTube_URL | Date | Duration | Description |
    Transcript | Primary_Category | Subcategory | Topics | Summary |
    Key_Insights | Relevance | Tags | Ollama_Status | NVIDIA_Status | Last_Updated
    """
    # Core metadata
    fo_id: str = ""
    guest: str = ""
    title: str = ""
    youtube_url: str = ""
    date: str = ""
    duration: str = ""
    description: str = ""

    # Transcript reference (path, not content)
    transcript_path: str = ""

    # Ollama classification
    primary_category: str = ""
    subcategory: str = ""
    topics: str = ""  # Comma-separated in sheet
    summary: str = ""
    key_insights: str = ""  # From NVIDIA, pipe-separated
    relevance: float = 0.0
    tags: str = ""  # Comma-separated in sheet

    # Processing status
    ollama_status: str = "Pending"  # Pending | Done | Failed
    nvidia_status: str = "Pending"  # Pending | Done | Skipped | Failed
    last_updated: str = ""

    # Internal (not in sheet)
    video_id: str = ""
    channel_name: str = ""

    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    @classmethod
    def from_video(cls, video: VideoMetadata, fo_id: str) -> "Episode":
        """Create an Episode from raw video metadata."""
        return cls(
            fo_id=fo_id,
            title=video.title,
            youtube_url=video.url,
            date=video.published_at[:10] if video.published_at else "",
            duration=video.duration,
            description=video.description[:300],
            video_id=video.video_id,
            channel_name=video.channel_name,
        )

    def apply_ollama(self, classification: OllamaClassification):
        """Apply Ollama classification results."""
        self.primary_category = classification.primary_category
        self.subcategory = classification.subcategory
        self.topics = ", ".join(classification.topics)
        self.tags = ", ".join(classification.tags)
        self.relevance = classification.relevance_score
        self.summary = classification.summary
        self.guest = classification.guest_type
        self.ollama_status = "Done"
        self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    def apply_nvidia(self, analysis: NvidiaAnalysis):
        """Apply NVIDIA deep analysis results."""
        self.key_insights = " | ".join(analysis.key_insights[:7])
        self.nvidia_status = "Done"
        self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    def to_sheet_row(self) -> list:
        """Convert to a flat row for the EPISODES Google Sheet."""
        return [
            self.fo_id,
            self.guest,
            self.title,
            self.youtube_url,
            self.date,
            self.duration,
            self.description,
            self.transcript_path,
            self.primary_category,
            self.subcategory,
            self.topics,
            self.summary,
            self.key_insights,
            str(self.relevance),
            self.tags,
            self.ollama_status,
            self.nvidia_status,
            self.last_updated,
        ]

    @staticmethod
    def sheet_headers() -> list:
        """EPISODES sheet column headers."""
        return [
            "FO_ID",
            "Guest",
            "Title",
            "YouTube_URL",
            "Date",
            "Duration",
            "Description",
            "Transcript",
            "Primary_Category",
            "Subcategory",
            "Topics",
            "Summary",
            "Key_Insights",
            "Relevance",
            "Tags",
            "Ollama_Status",
            "NVIDIA_Status",
            "Last_Updated",
        ]
