"""
NVIDIA API Client Module — Deep Analysis.

Uses NVIDIA API ONLY for important/high-relevance episodes.
Don't send every 2-hour transcript to the expensive API.

Handles:
- Full transcript analysis
- Detailed episode summary
- Key insights
- Important arguments
- Contradictory viewpoints
- Business lessons
- Technical explanations
- Claims that need verification
- Major themes
"""

import json
import os
from typing import Optional

from loguru import logger
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models import VideoMetadata, TranscriptData, NvidiaAnalysis


class NvidiaAnalyzer:
    """Uses NVIDIA API for deep analysis of important episodes only."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        model: str = "meta/llama-3.1-70b-instruct",
        temperature: float = 0.4,
        max_tokens: int = 4096,
    ):
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        if not self.api_key:
            raise ValueError("NVIDIA API key not found. Set NVIDIA_API_KEY in .env")

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # NVIDIA uses OpenAI-compatible endpoint
        self.client = OpenAI(
            base_url=base_url,
            api_key=self.api_key,
        )

    def _build_prompt(
        self,
        video: VideoMetadata,
        transcript: TranscriptData,
        ollama_category: str = "",
    ) -> str:
        """Build deep analysis prompt - uses full transcript."""
        # Send more content to NVIDIA (it handles long context)
        content = transcript.full_text[:12000]

        prompt = f"""Perform a deep analysis of this podcast/YouTube episode.

EPISODE:
- Title: {video.title}
- Channel: {video.channel_name}
- Duration: {video.duration}
- Category: {ollama_category}
- Published: {video.published_at}

FULL TRANSCRIPT:
{content}

Provide comprehensive analysis in this JSON format:
{{
  "detailed_summary": "3-5 sentence thorough summary of the episode content and value",
  "key_insights": [
    "Specific insight 1 with context",
    "Specific insight 2 with context",
    "Specific insight 3 with context"
  ],
  "important_arguments": [
    "Core argument or claim made in the episode",
    "Another significant argument"
  ],
  "contradictory_viewpoints": [
    "Any contrarian or opposing views discussed"
  ],
  "business_lessons": [
    "Actionable business/career lesson from this episode"
  ],
  "technical_explanations": [
    "Any technical concept explained (if applicable)"
  ],
  "claims_to_verify": [
    "Any bold claim that should be fact-checked"
  ],
  "major_themes": [
    "Theme 1",
    "Theme 2",
    "Theme 3"
  ]
}}

RULES:
- Be specific and factual based on the transcript
- Key insights should be actionable, not generic platitudes
- Include 5-7 key insights
- Include 2-5 important arguments
- Include business lessons only if relevant
- Mark claims that seem unverified or exaggerated
- Major themes should be broad topic labels"""

        return prompt

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def analyze(
        self,
        video: VideoMetadata,
        transcript: TranscriptData,
        ollama_category: str = "",
    ) -> Optional[NvidiaAnalysis]:
        """
        Deep-analyze an episode using NVIDIA API.
        Only called for high-relevance episodes (relevance >= threshold).
        """
        if not transcript or not transcript.full_text:
            logger.warning(f"[NVIDIA] No transcript for: {video.title}")
            return None

        try:
            prompt = self._build_prompt(video, transcript, ollama_category)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert analyst specializing in podcasts and "
                            "long-form content. Provide deep, structured analysis. "
                            "Always respond in valid JSON only. No markdown, no explanation."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            result_text = response.choices[0].message.content.strip()
            result_text = self._extract_json(result_text)

            # Try parsing, with fallback repair
            try:
                data = json.loads(result_text)
            except json.JSONDecodeError:
                # Aggressive repair: fix broken strings by removing internal newlines
                import re
                repaired = re.sub(r'"\s*\n\s*', '" ', result_text)
                repaired = re.sub(r'\n\s*"', ' "', repaired)
                repaired = re.sub(r',\s*,', ',', repaired)
                data = json.loads(repaired)

            analysis = NvidiaAnalysis(
                detailed_summary=data.get("detailed_summary", ""),
                key_insights=data.get("key_insights", []),
                important_arguments=data.get("important_arguments", []),
                contradictory_viewpoints=data.get("contradictory_viewpoints", []),
                business_lessons=data.get("business_lessons", []),
                technical_explanations=data.get("technical_explanations", []),
                claims_to_verify=data.get("claims_to_verify", []),
                major_themes=data.get("major_themes", []),
            )

            logger.info(
                f"[NVIDIA] Deep analysis done: {video.title[:40]}... "
                f"({len(analysis.key_insights)} insights, "
                f"{len(analysis.major_themes)} themes)"
            )
            return analysis

        except json.JSONDecodeError as e:
            logger.warning(f"[NVIDIA] JSON parse failed for '{video.title}': {e}")
            return None
        except Exception as e:
            logger.error(f"[NVIDIA] Error for '{video.title}': {e}")
            raise

    def _extract_json(self, text: str) -> str:
        """Extract and fix JSON from response."""
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]

        text = text.strip()

        # Fix common LLM JSON issues
        import re
        # Remove trailing commas before } or ]
        text = re.sub(r',\s*([}\]])', r'\1', text)
        # Fix unescaped newlines inside string values
        text = re.sub(r'(?<=": ")(.*?)(?=")', lambda m: m.group(0).replace('\n', ' '), text)

        return text

    def health_check(self) -> bool:
        """Verify NVIDIA API connectivity (quick test with short timeout)."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Reply with: OK"}],
                max_tokens=10,
                timeout=15,  # Short timeout for health check only
            )
            return bool(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"NVIDIA API health check failed: {e}")
            return False
