"""Groq: summarize one channel-day into the five structured sections."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from groq import Groq

from src.config import GROQ_API_KEY, TIMEZONE

_MODEL = "llama-3.3-70b-versatile"
_PROMPT_PATH = Path(__file__).parent / "templates" / "summary_prompt.txt"

_client = Groq(api_key=GROQ_API_KEY)

_SECTION_KEYS = {
    "key decisions": "key_decisions",
    "action items": "action_items",
    "open questions": "open_questions",
    "notable discussions": "notable_discussions",
    "participants": "participants",
}

_EMPTY_SUMMARY = {key: "None." for key in _SECTION_KEYS.values()}


def _format_ts(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), TIMEZONE).strftime("%H:%M")


def build_transcript_block(messages: list[dict]) -> str:
    lines: list[str] = []
    for m in messages:
        indent = "    " if m["is_thread_reply"] else ""
        text = m["text"].strip()
        lines.append(f"{indent}[{_format_ts(m['ts'])}] {m['user_name']}: {text}")
    return "\n".join(lines)


def _render_prompt(channel_name: str, date_pt: date, transcript_block: str) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{channel_name}", channel_name)
        .replace("{date_pt}", date_pt.isoformat())
        .replace("{transcript_block}", transcript_block)
    )


def parse_summary(text: str) -> dict[str, str]:
    sections = dict(_EMPTY_SUMMARY)
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None:
            sections[current] = "\n".join(buffer).strip() or "None."

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            header = stripped.lstrip("#").strip().lower()
            if header in _SECTION_KEYS:
                flush()
                current = _SECTION_KEYS[header]
                buffer = []
                continue
        if current is not None:
            buffer.append(line)
    flush()
    return sections


def summarize_channel_day(
    channel_name: str, messages: list[dict], date_pt: date
) -> dict[str, str]:
    if not messages:
        return dict(_EMPTY_SUMMARY)
    prompt = _render_prompt(channel_name, date_pt, build_transcript_block(messages))
    resp = _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return parse_summary(resp.choices[0].message.content)


def main() -> None:
    from src.config import get_yesterday_pt_bounds, get_yesterday_pt_date
    from src.slack_fetcher import fetch_channel_day, list_public_channels

    date_pt = get_yesterday_pt_date()
    oldest, latest = get_yesterday_pt_bounds()

    for ch in list_public_channels():
        records = fetch_channel_day(ch, oldest, latest)
        if not records:
            continue
        print(f"Summarizing #{ch['name']} for {date_pt} ({len(records)} messages)\n")
        summary = summarize_channel_day(ch["name"], records, date_pt)
        for key, value in summary.items():
            print(f"## {key}")
            print(value)
            print()
        return

    print("No channels had messages yesterday. Try a known-busy date.")


if __name__ == "__main__":
    main()
