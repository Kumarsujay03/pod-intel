"""
Google Gemini Client Module — Fast Cloud Classification.

Uses the new google-genai SDK for fast bulk classification:
- Primary category
- Subcategory
- Topics
- Tags
- Guest type
- Relevance score
- Short summary

Much faster than local Ollama (~2-5 sec vs ~40 sec per episode).
"""

import json
import os
import time
from typing import Optional

from google import genai
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models import VideoMetadata, TranscriptData, OllamaClassification


class GeminiClassifier:
    """Uses Google Gemini API for fast bulk classification of ALL episodes."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash",
        temperature: float = 0.3,
        categories: list = None,
        profile: dict = None,
        rpm_limit: int = 15,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Gemini API key not found. Set GEMINI_API_KEY in .env")

        self.client = genai.Client(api_key=self.api_key)
        self.model_name = model
        self.temperature = temperature
        self.categories = categories or []
        self.profile = profile or {}
        self.rpm_limit = rpm_limit

        # Rate limiting
        self._min_interval = 60.0 / rpm_limit
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce rate limiting to stay within RPM quota."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _build_prompt(
        self,
        video: VideoMetadata,
        transcript: Optional[TranscriptData],
    ) -> str:
        """Build classification prompt."""
        categories_str = "\n".join(f"  - {c}" for c in self.categories)

        content = ""
        if transcript and transcript.full_text:
            content = transcript.full_text[:4000]
        else:
            content = video.description[:1000]

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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def classify(
        self,
        video: VideoMetadata,
        transcript: Optional[TranscriptData] = None,
    ) -> Optional[OllamaClassification]:
        """
        Classify a single episode using Gemini.
        Fast cloud processing (~2-5 sec per episode).
        """
        try:
            self._rate_limit()
            prompt = self._build_prompt(video, transcript)

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={
                    "temperature": self.temperature,
                    "response_mime_type": "application/json",
                    "system_instruction": (
                        "You are a precise content classifier. "
                        "Always respond in valid JSON only. No explanation, no markdown."
                    ),
                },
            )

            result_text = response.text.strip()
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
                f"[Gemini] {video.title[:40]}... -> "
                f"{classification.primary_category} | "
                f"Relevance: {classification.relevance_score}"
            )
            return classification

        except json.JSONDecodeError as e:
            logger.warning(f"[Gemini] JSON parse failed for '{video.title}': {e}")
            return None
        except Exception as e:
            logger.error(f"[Gemini] Error for '{video.title}': {e}")
            raise

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response."""
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]

        import re
        text = re.sub(r',\s*([}\]])', r'\1', text)
        return text.strip()

    def health_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents="Say hello",
                config={"max_output_tokens": 10},
            )
            # Check if we got any response
            if response and response.candidates:
                return True
            if response and response.text:
                return True
            return False
        except Exception as e:
            logger.error(f"Gemini health check failed: {e}")
            return False
