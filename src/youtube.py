"""
YouTube Data Collection Module.
Fetches video metadata from multiple YouTube channels using YouTube Data API v3.

Supports:
- Multi-channel collection
- Shorts filtering (skip shorts, only long-form)
- Duration filtering (min_duration_minutes)
- Date filtering (since_date per channel)
- Fetching ALL videos (no arbitrary 50 limit)
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models import ChannelConfig, VideoMetadata


class YouTubeCollector:
    """Collects video metadata from YouTube channels."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        if not self.api_key:
            raise ValueError("YouTube API key not found. Set YOUTUBE_API_KEY in .env")

        self.youtube = build("youtube", "v3", developerKey=self.api_key)
        self.data_dir = Path("data/raw")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_channel_videos(
        self,
        channel: ChannelConfig,
        since_date: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> list[VideoMetadata]:
        """
        Fetch ALL videos from a channel (respecting filters).
        
        Args:
            channel: Channel configuration (includes filter settings)
            since_date: Override since_date from config (ISO: "2024-01-01T00:00:00Z")
            max_results: Override max videos (0 = no limit)
        """
        logger.info(f"Fetching videos for: {channel.name} ({channel.channel_handle})")

        # Determine limits
        max_vids = max_results if max_results is not None else channel.max_videos
        if max_vids == 0:
            max_vids = 10000  # Effectively unlimited

        # Determine date filter
        published_after = since_date
        if not published_after and hasattr(channel, 'since_date') and channel.since_date:
            published_after = f"{channel.since_date}T00:00:00Z"

        videos = []
        next_page_token = None

        while True:
            try:
                # Search for videos on this channel
                search_params = {
                    "part": "id,snippet",
                    "channelId": channel.channel_id,
                    "maxResults": 50,  # API max per page
                    "order": "date",
                    "type": "video",
                }
                if next_page_token:
                    search_params["pageToken"] = next_page_token
                if published_after:
                    search_params["publishedAfter"] = published_after

                request = self.youtube.search().list(**search_params)
                response = request.execute()

                video_ids = [
                    item["id"]["videoId"]
                    for item in response.get("items", [])
                    if item["id"].get("videoId")
                ]

                if video_ids:
                    # Get detailed video info (duration, stats)
                    details = self._get_video_details(video_ids)

                    for item in response["items"]:
                        vid_id = item["id"].get("videoId")
                        if not vid_id or vid_id not in details:
                            continue

                        detail = details[vid_id]
                        snippet = item["snippet"]

                        # Parse duration
                        iso_duration = detail.get("contentDetails", {}).get("duration", "")
                        duration_str = self._parse_duration(iso_duration)
                        duration_minutes = self._duration_to_minutes(iso_duration)

                        # Filter: Skip Shorts (under 60 seconds typically)
                        if hasattr(channel, 'filter_shorts') and channel.filter_shorts:
                            if duration_minutes < 1.5:  # Under 90 sec = likely a Short
                                continue

                        # Filter: Minimum duration
                        min_dur = getattr(channel, 'min_duration_minutes', 0)
                        if min_dur and duration_minutes < min_dur:
                            continue

                        video = VideoMetadata(
                            video_id=vid_id,
                            channel_id=channel.channel_id,
                            channel_name=channel.name,
                            title=snippet["title"],
                            url=f"https://www.youtube.com/watch?v={vid_id}",
                            published_at=snippet["publishedAt"],
                            duration=duration_str,
                            description=snippet.get("description", ""),
                            view_count=int(
                                detail.get("statistics", {}).get("viewCount", 0)
                            ),
                            like_count=int(
                                detail.get("statistics", {}).get("likeCount", 0)
                            ),
                            comment_count=int(
                                detail.get("statistics", {}).get("commentCount", 0)
                            ),
                            thumbnail_url=snippet.get("thumbnails", {})
                            .get("high", {})
                            .get("url", ""),
                        )
                        videos.append(video)

                next_page_token = response.get("nextPageToken")

                # Stop conditions
                if not next_page_token:
                    break
                if len(videos) >= max_vids:
                    break

                logger.debug(f"  Fetched {len(videos)} so far... (next page)")

            except HttpError as e:
                if e.resp.status == 403:
                    logger.error(f"YouTube API quota exceeded for {channel.name}")
                    break
                logger.error(f"YouTube API error for {channel.name}: {e}")
                raise

        # Trim to max
        videos = videos[:max_vids] if max_vids < 10000 else videos

        logger.success(f"Fetched {len(videos)} videos from {channel.name}")
        return videos

    def _get_video_details(self, video_ids: list[str]) -> dict:
        """Get detailed info for a batch of video IDs."""
        request = self.youtube.videos().list(
            part="contentDetails,statistics",
            id=",".join(video_ids),
        )
        response = request.execute()

        return {
            item["id"]: item
            for item in response.get("items", [])
        }

    @staticmethod
    def _parse_duration(iso_duration: str) -> str:
        """Convert ISO 8601 duration (PT1H2M3S) to readable format."""
        if not iso_duration:
            return "Unknown"

        match = re.match(
            r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration
        )
        if not match:
            return iso_duration

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _duration_to_minutes(iso_duration: str) -> float:
        """Convert ISO 8601 duration to total minutes."""
        if not iso_duration:
            return 0

        match = re.match(
            r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration
        )
        if not match:
            return 0

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)

        return hours * 60 + minutes + seconds / 60

    def save_raw_data(self, channel_name: str, videos: list[VideoMetadata]):
        """Save raw video metadata to JSON for backup."""
        safe_name = channel_name.lower().replace(" ", "_").replace("/", "_")
        filename = self.data_dir / f"{safe_name}_videos.json"

        data = {
            "channel": channel_name,
            "fetched_at": datetime.now().isoformat(),
            "count": len(videos),
            "videos": [
                {
                    "video_id": v.video_id,
                    "title": v.title,
                    "url": v.url,
                    "published_at": v.published_at,
                    "duration": v.duration,
                    "description": v.description[:500],
                    "view_count": v.view_count,
                    "like_count": v.like_count,
                    "comment_count": v.comment_count,
                }
                for v in videos
            ],
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved raw data: {filename} ({len(videos)} videos)")
