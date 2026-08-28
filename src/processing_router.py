"""
Processing Router — Smart routing between Ollama and NVIDIA.

Architecture (from scale.md):
  600 episodes
     │
     ▼
  Ollama (classify ALL 600, tag ALL 600, basic summaries)
     │
     ▼
  Identify important episodes (relevance >= threshold)
     │
     ▼
  NVIDIA (deep analysis ONLY for important ones)

Don't make NVIDIA and Ollama do the same thing.
Ollama = "Process everything cheaply."
NVIDIA = "Think harder when necessary."
"""

import time
from typing import Optional

from loguru import logger
from rich.console import Console

from src.models import (
    VideoMetadata,
    TranscriptData,
    OllamaClassification,
    NvidiaAnalysis,
    Episode,
)
from src.nvidia_client import NvidiaAnalyzer

console = Console()


class ProcessingRouter:
    """Routes episodes through Classifier (all) → NVIDIA (important only)."""

    def __init__(
        self,
        classifier,
        nvidia: Optional[NvidiaAnalyzer] = None,
        nvidia_threshold: float = 4.0,
        delay_between_requests: float = 2.0,
    ):
        self.classifier = classifier
        self.nvidia = nvidia
        self.nvidia_threshold = nvidia_threshold
        self.delay = delay_between_requests

    def process_all_ollama(
        self,
        episodes: list[Episode],
        videos: dict[str, VideoMetadata],
        transcripts: dict[str, TranscriptData],
    ) -> list[Episode]:
        """
        Step 1: Run Ollama on ALL episodes.
        Cheap, fast, local. Classifies everything.
        """
        logger.info(f"[Router] Classifying {len(episodes)} episodes...")

        for i, episode in enumerate(episodes):
            if episode.ollama_status == "Done":
                continue

            video = videos.get(episode.video_id)
            if not video:
                continue

            transcript = transcripts.get(episode.video_id)

            try:
                classification = self.classifier.classify(video, transcript)

                if classification:
                    episode.apply_ollama(classification)
                else:
                    episode.ollama_status = "Failed"

            except Exception as e:
                episode.ollama_status = "Failed"
                logger.error(f"[Router] Classification failed for {episode.title[:40]}: {e}")

            # Rate limiting
            if i < len(episodes) - 1:
                time.sleep(self.delay)

        done = sum(1 for ep in episodes if ep.ollama_status == "Done")
        failed = sum(1 for ep in episodes if ep.ollama_status == "Failed")
        logger.info(f"[Router] Classification complete: {done} done, {failed} failed")

        return episodes

    def identify_important_episodes(self, episodes: list[Episode]) -> list[Episode]:
        """
        Step 2: Identify episodes that deserve NVIDIA deep analysis.
        Based on relevance_score from Ollama >= nvidia_threshold.
        """
        important = [
            ep for ep in episodes
            if ep.ollama_status == "Done"
            and ep.relevance >= self.nvidia_threshold
            and ep.nvidia_status != "Done"
        ]

        logger.info(
            f"[Router] {len(important)}/{len(episodes)} episodes meet "
            f"NVIDIA threshold (relevance >= {self.nvidia_threshold})"
        )

        # Sort by relevance (highest first)
        important.sort(key=lambda ep: ep.relevance, reverse=True)
        return important

    def process_nvidia(
        self,
        episodes: list[Episode],
        videos: dict[str, VideoMetadata],
        transcripts: dict[str, TranscriptData],
    ) -> list[Episode]:
        """
        Step 3: Run NVIDIA deep analysis on important episodes only.
        Expensive, powerful — only for high-relevance content.
        """
        if not self.nvidia:
            logger.info("[Router] NVIDIA not configured, marking as Skipped")
            for ep in episodes:
                ep.nvidia_status = "Skipped"
            return episodes

        logger.info(f"[Router] NVIDIA deep-analyzing {len(episodes)} important episodes...")

        for i, episode in enumerate(episodes):
            video = videos.get(episode.video_id)
            transcript = transcripts.get(episode.video_id)

            if not video or not transcript:
                episode.nvidia_status = "Skipped"
                continue

            try:
                analysis = self.nvidia.analyze(
                    video, transcript, ollama_category=episode.primary_category
                )

                if analysis:
                    episode.apply_nvidia(analysis)
                else:
                    episode.nvidia_status = "Failed"

            except Exception as e:
                episode.nvidia_status = "Failed"
                logger.error(f"[Router] NVIDIA failed for {episode.title[:40]}: {e}")

            # Longer delay for NVIDIA (rate limits)
            if i < len(episodes) - 1:
                time.sleep(self.delay * 2)

        done = sum(1 for ep in episodes if ep.nvidia_status == "Done")
        logger.info(f"[Router] NVIDIA complete: {done}/{len(episodes)} analyzed")

        return episodes

    def mark_skipped(self, episodes: list[Episode]) -> list[Episode]:
        """Mark non-important episodes as NVIDIA Skipped."""
        for ep in episodes:
            if ep.nvidia_status == "Pending" and ep.ollama_status == "Done":
                if ep.relevance < self.nvidia_threshold:
                    ep.nvidia_status = "Skipped"
        return episodes

    def full_process(
        self,
        episodes: list[Episode],
        videos: dict[str, VideoMetadata],
        transcripts: dict[str, TranscriptData],
    ) -> list[Episode]:
        """
        Full smart routing pipeline:
        1. Ollama classifies ALL episodes
        2. Identify important ones (relevance >= threshold)
        3. NVIDIA deep-analyzes only the important ones
        4. Mark the rest as Skipped
        """
        # Step 1: Ollama on all
        episodes = self.process_all_ollama(episodes, videos, transcripts)

        # Step 2: Identify important
        important = self.identify_important_episodes(episodes)

        # Step 3: NVIDIA on important only
        if important:
            self.process_nvidia(important, videos, transcripts)

        # Step 4: Mark the rest
        episodes = self.mark_skipped(episodes)

        # Summary
        total = len(episodes)
        ollama_done = sum(1 for ep in episodes if ep.ollama_status == "Done")
        nvidia_done = sum(1 for ep in episodes if ep.nvidia_status == "Done")
        nvidia_skipped = sum(1 for ep in episodes if ep.nvidia_status == "Skipped")

        console.print(
            f"\n  [bold]Processing Summary:[/bold]\n"
            f"  Total: {total} | "
            f"Ollama: {ollama_done} done | "
            f"NVIDIA: {nvidia_done} deep-analyzed, {nvidia_skipped} skipped"
        )

        return episodes
