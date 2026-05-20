"""Env vars, timezone, time-bounds helpers."""

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

TIMEZONE = ZoneInfo("America/Los_Angeles")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required env var not set: {name}")
    return value


def get_pt_bounds_for_date(d: date) -> tuple[str, str]:
    """Return (oldest, latest) Slack-style unix timestamps for the given PT date."""
    start = datetime.combine(d, time.min, tzinfo=TIMEZONE)
    end = start + timedelta(days=1)
    return (f"{start.timestamp():.6f}", f"{end.timestamp():.6f}")


def get_yesterday_pt_bounds() -> tuple[str, str]:
    yesterday = (datetime.now(TIMEZONE) - timedelta(days=1)).date()
    return get_pt_bounds_for_date(yesterday)


def get_yesterday_pt_date() -> date:
    return (datetime.now(TIMEZONE) - timedelta(days=1)).date()


SLACK_BOT_TOKEN = _require("SLACK_BOT_TOKEN")
SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_KEY = _require("SUPABASE_KEY")
GROQ_API_KEY = _require("GROQ_API_KEY")
GOOGLE_SERVICE_ACCOUNT_JSON = _require("GOOGLE_SERVICE_ACCOUNT_JSON")
MASTER_DOC_ID = _require("MASTER_DOC_ID")
SUMMARIES_TAB_ID = _require("SUMMARIES_TAB_ID")
TRANSCRIPTS_TAB_ID = _require("TRANSCRIPTS_TAB_ID")


def load_google_credentials(scopes: list[str]):
    """GOOGLE_SERVICE_ACCOUNT_JSON is either a file path (local) or raw JSON (CI)."""
    from google.oauth2 import service_account

    value = GOOGLE_SERVICE_ACCOUNT_JSON
    if value.lstrip().startswith("{"):
        import json

        info = json.loads(value)
        return service_account.Credentials.from_service_account_info(
            info, scopes=scopes
        )
    return service_account.Credentials.from_service_account_file(value, scopes=scopes)
