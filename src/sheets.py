"""
Google Sheets Integration Module.
Three sheets (not one giant sheet):
  1. EPISODES — Main episode data
  2. CATEGORIES — Controlled taxonomy
  3. PROFILE — User interest profile for relevance scoring

Transcripts are NOT stored in sheets — only a file path reference.
Google Sheets = database/index, not a transcript repository.

Authentication:
  Uses OAuth2 (browser login). On first run, opens browser for Google
  sign-in. Token is cached locally — no repeated logins needed.

  Setup: Download OAuth Client ID JSON from Google Cloud Console
  (APIs & Services > Credentials > Create OAuth Client ID > Desktop app)
  and save it as config/credentials.json
"""

import os
from pathlib import Path
from typing import Optional

import gspread
from loguru import logger

from src.models import Episode


# Project root for resolving config paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Default paths for OAuth files
DEFAULT_CREDENTIALS_FILE = PROJECT_ROOT / "config" / "credentials.json"
DEFAULT_AUTHORIZED_USER_FILE = PROJECT_ROOT / "config" / "authorized_user.json"


class SheetsManager:
    """Manages the 3-sheet Google Sheets structure."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
    ):
        self.credentials_path = Path(
            credentials_path
            or os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", str(DEFAULT_CREDENTIALS_FILE))
        )
        self.authorized_user_path = Path(
            os.getenv("GOOGLE_SHEETS_AUTHORIZED_USER_PATH", str(DEFAULT_AUTHORIZED_USER_FILE))
        )
        self.spreadsheet_id = spreadsheet_id or os.getenv(
            "GOOGLE_SHEETS_SPREADSHEET_ID", ""
        )

        if not self.spreadsheet_id:
            raise ValueError(
                "Google Sheets spreadsheet ID not found. "
                "Set GOOGLE_SHEETS_SPREADSHEET_ID in .env"
            )

        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"OAuth credentials file not found: {self.credentials_path}\n"
                "Download it from Google Cloud Console:\n"
                "  APIs & Services > Credentials > Create OAuth Client ID > Desktop app\n"
                "Save it as config/credentials.json"
            )

        self.client = self._authenticate()
        self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)

    def _authenticate(self) -> gspread.Client:
        """Authenticate via OAuth2 (browser-based login).

        First run opens browser for consent. Token is cached locally
        at config/authorized_user.json for subsequent runs.
        """
        return gspread.oauth(
            credentials_filename=str(self.credentials_path),
            authorized_user_filename=str(self.authorized_user_path),
        )

    # ─── EPISODES Sheet ───────────────────────────────────────────────

    def ensure_episodes_sheet(self) -> gspread.Worksheet:
        """Create EPISODES sheet if it doesn't exist."""
        try:
            ws = self.spreadsheet.worksheet("EPISODES")
        except gspread.exceptions.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(
                title="EPISODES", rows=1000, cols=20
            )
            headers = Episode.sheet_headers()
            ws.update("A1", [headers])
            ws.format("A1:R1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0},
            })
            logger.info("Created EPISODES sheet with headers")
        return ws

    def push_episodes(self, episodes: list[Episode]):
        """Push episodes to the EPISODES sheet (skips duplicates by FO_ID)."""
        ws = self.ensure_episodes_sheet()

        # Get existing FO_IDs to avoid duplicates
        existing_data = ws.get_all_values()
        existing_ids = set()
        if len(existing_data) > 1:
            fo_col_idx = 0  # FO_ID is first column
            existing_ids = {
                row[fo_col_idx] for row in existing_data[1:]
                if row[fo_col_idx]
            }

        # Filter new episodes
        new_episodes = [ep for ep in episodes if ep.fo_id not in existing_ids]

        if not new_episodes:
            logger.info("No new episodes to push to EPISODES sheet")
            return

        rows = [ep.to_sheet_row() for ep in new_episodes]

        # Append after last row
        next_row = len(existing_data) + 1
        ws.update(f"A{next_row}", rows)

        logger.success(
            f"Pushed {len(new_episodes)} episodes to EPISODES "
            f"(skipped {len(episodes) - len(new_episodes)} duplicates)"
        )

    def update_episode(self, episode: Episode):
        """Update a single episode row (find by FO_ID and overwrite)."""
        ws = self.ensure_episodes_sheet()
        data = ws.get_all_values()

        for i, row in enumerate(data[1:], start=2):  # skip header
            if row[0] == episode.fo_id:
                ws.update(f"A{i}", [episode.to_sheet_row()])
                logger.debug(f"Updated {episode.fo_id} in EPISODES")
                return

        # Not found — append
        next_row = len(data) + 1
        ws.update(f"A{next_row}", [episode.to_sheet_row()])

    def get_existing_fo_ids(self) -> set[str]:
        """Get all FO_IDs already in the EPISODES sheet."""
        try:
            ws = self.spreadsheet.worksheet("EPISODES")
            data = ws.get_all_values()
            if len(data) <= 1:
                return set()
            return {row[0] for row in data[1:] if row[0]}
        except gspread.exceptions.WorksheetNotFound:
            return set()

    def get_existing_urls(self) -> set[str]:
        """Get all YouTube URLs already processed."""
        try:
            ws = self.spreadsheet.worksheet("EPISODES")
            data = ws.get_all_values()
            if len(data) <= 1:
                return set()
            url_idx = Episode.sheet_headers().index("YouTube_URL")
            return {row[url_idx] for row in data[1:] if len(row) > url_idx and row[url_idx]}
        except gspread.exceptions.WorksheetNotFound:
            return set()

    # ─── CATEGORIES Sheet ─────────────────────────────────────────────

    def ensure_categories_sheet(self, categories: list[str]):
        """Create/update CATEGORIES sheet with controlled taxonomy."""
        try:
            ws = self.spreadsheet.worksheet("CATEGORIES")
        except gspread.exceptions.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(
                title="CATEGORIES", rows=50, cols=3
            )
            logger.info("Created CATEGORIES sheet")

        # Write categories
        headers = [["Category", "Description", "Episode Count"]]
        rows = [[cat, "", ""] for cat in categories]
        ws.update("A1", headers + rows)
        ws.format("A1:C1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.9, "green": 1.0, "blue": 0.9},
        })

    # ─── PROFILE Sheet ────────────────────────────────────────────────

    def ensure_profile_sheet(self, profile: dict):
        """Create/update PROFILE sheet with user interest scores."""
        try:
            ws = self.spreadsheet.worksheet("PROFILE")
        except gspread.exceptions.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(
                title="PROFILE", rows=50, cols=3
            )
            logger.info("Created PROFILE sheet")

        headers = [["Category", "Interest (1-5)", "Notes"]]
        rows = [[cat, str(score), ""] for cat, score in profile.items()]
        ws.update("A1", headers + rows)
        ws.format("A1:C1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.85},
        })

    # ─── Setup All Sheets ─────────────────────────────────────────────

    def setup_all_sheets(self, categories: list[str], profile: dict):
        """Initialize all 3 sheets."""
        self.ensure_episodes_sheet()
        self.ensure_categories_sheet(categories)
        self.ensure_profile_sheet(profile)
        logger.success("All 3 sheets ready: EPISODES, CATEGORIES, PROFILE")

    # ─── Health Check ─────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Verify Google Sheets connectivity."""
        try:
            title = self.spreadsheet.title
            logger.info(f"Connected to spreadsheet: {title}")
            return True
        except Exception as e:
            logger.error(f"Google Sheets health check failed: {e}")
            return False
