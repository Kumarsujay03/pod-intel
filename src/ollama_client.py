"""
Ollama Client Module — Bulk/Local Processing.

Uses a small local instruct model for:
- Primary category
- Subcategory
- Topics
- Tags
- Guest type
- Relevance score
- Short summary
- Duplicate detection

This runs on ALL episodes cheaply and fast.
"""

import json
from typing import Optional

import ollama
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed

from src.models import VideoMetadata, TranscriptData, OllamaClassification


class OllamaClassifier:
    """Uses Ollama (local LLM) for bulk classification of ALL episodes."""

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.3,
        categories: list = None,
        profile: dict = None,
    ):
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.categories = categories or []
        self.profile = profile or {}
        self.client = ollama.Client(host=base_url)

    def _build_prompt(
        self,
        video: VideoMetadata,
        transcript: Optional[TranscriptData],
    ) -> str:
        """Build classification prompt."""
        categories_str = "\n".join(f"  - {c}" for c in self.categories)

        # Use transcript if available, otherwise description
        content = ""
        if transcript and transcript.full_text:
            content = transcript.full_text[:3000]
        else:
            content = video.description[:1000]

        # Include user profile for relevance calculation
        profile_str = "\n".join(
            f"  {k}: {v}/5" for k, v in self.profile.items()
        )

        prompt = f"""Classify this YouTube episode. Be precise and factual.

EPISODE:
- Title: {video.title}
- Channel: {video.channel_name}
- Duration: {video.duration}
- Views: {video.view_count:,}

CONTENT:
{content}

ALLOWED CATEGORIES (pick ONE primary, ONE subcategory):
{categories_str}

USER INTEREST PROFILE (use to calculate relevance):
{profile_str}

INSTRUCTIONS:
1. Pick ONE primary_category from the allowed list above
2. Pick a subcategory (can be more specific, e.g., "AI Agents", "Mutual Funds")
3. List 3-6 topics discussed
4. Assign 3-5 tags
5. Identify guest type (e.g., "Entrepreneur", "Investor", "Author", "Solo Episode")
6. Write a 1-2 sentence summary
7. Calculate relevance_score (1-5) based on how well episode topics match user interests

Respond ONLY in this JSON format:
{{
  "primary_category": "AI & Technology",
  "subcategory": "AI Agents",
  "topics": ["AI", "automation", "future of work"],
  "tags": ["AI", "Agents", "Automation"],
  "guest_type": "Tech Entrepreneur",
  "summary": "Discussion about how AI agents will transform business operations",
  "relevance_score": 4.5
}}"""
        return prompt

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def classify(
        self,
        video: VideoMetadata,
        transcript: Optional[TranscriptData] = None,
    ) -> Optional[OllamaClassification]:
        """
        Classify a single episode using Ollama.
        Cheap, fast, runs on ALL episodes.
        """
        try:
            prompt = self._build_prompt(video, transcript)

            response = self.client.chat(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise content classifier. "
                            "Always respond in valid JSON only. No explanation."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": self.temperature},
            )

            result_text = response["message"]["content"].strip()
            result_text = self._extract_json(result_text)
            data = json.loads(result_text)

            classification = OllamaClassification(
                primary_category=data.get("primary_category", "Uncategorized"),
                subcategory=data.get("subcategory", ""),
                topics=data.get("topics", []),
                tags=data.get("tags", []),
                guest_type=data.get("guest_type", ""),
                summary=data.get("summary", ""),
                relevance_score=float(data.get("relevance_score", 0)),
            )

            logger.info(
                f"[Ollama] {video.title[:40]}... → "
                f"{classification.primary_category} | "
                f"Relevance: {classification.relevance_score}"
            )
            return classification

        except json.JSONDecodeError as e:
            logger.warning(f"[Ollama] JSON parse failed for '{video.title}': {e}")
            return None
        except Exception as e:
            logger.error(f"[Ollama] Error for '{video.title}': {e}")
            raise

    def is_duplicate(self, title: str, existing_titles: list[str]) -> bool:
        """
        Use Ollama to check if an episode title is a duplicate/reupload.
        Useful for detecting re-uploads with slightly different titles.
        """
        if not existing_titles:
            return False

        try:
            sample = existing_titles[:20]  # Check against recent episodes
            titles_str = "\n".join(f"  - {t}" for t in sample)

            prompt = f"""Is this a duplicate or re-upload of an existing episode?

NEW EPISODE: "{title}"

EXISTING EPISODES:
{titles_str}

Respond with ONLY: {{"is_duplicate": true/false, "similar_to": "title or null"}}"""

            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1},
            )

            result = json.loads(self._extract_json(response["message"]["content"]))
            return result.get("is_duplicate", False)

        except Exception:
            return False

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response that might include markdown."""
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]

        return text.strip()

    def health_check(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            models = self.client.list()
            available = [m["name"] for m in models.get("models", [])]

            if not any(self.model in m for m in available):
                logger.warning(
                    f"Model '{self.model}' not found. Available: {available}"
                )
                logger.info(f"Pull it with: ollama pull {self.model}")
                return False

            return True
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False
