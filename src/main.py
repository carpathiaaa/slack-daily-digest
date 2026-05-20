"""Orchestrator: fetch -> store -> summarize -> write, with run status tracking."""

from __future__ import annotations

from datetime import date

from src.config import get_yesterday_pt_bounds, get_yesterday_pt_date
from src.docs_writer import append_daily_entry
from src.slack_fetcher import fetch_channel_day, list_public_channels
from src.storage import (
    get_run_status,
    mark_failed,
    mark_fetched,
    mark_summarized,
    mark_written,
    start_run,
    upsert_messages,
)
from src.summarizer import summarize_channel_day


def run_digest(date_pt: date, oldest: str, latest: str) -> None:
    if get_run_status(date_pt) == "written":
        print(f"{date_pt}: already written, skipping.")
        return

    run_id = start_run(date_pt)
    try:
        channels = list_public_channels()
        channel_entries: list[dict] = []
        all_records: list[dict] = []
        for ch in channels:
            messages = fetch_channel_day(ch, oldest, latest)
            all_records.extend(messages)
            channel_entries.append(
                {"channel_name": ch["name"], "messages": messages}
            )

        upsert_messages(all_records, date_pt)
        mark_fetched(run_id, len(channels), len(all_records))

        for entry in channel_entries:
            entry["summary"] = summarize_channel_day(
                entry["channel_name"], entry["messages"], date_pt
            )
        mark_summarized(run_id)

        append_daily_entry(date_pt, channel_entries)
        mark_written(run_id)
        print(
            f"{date_pt}: done "
            f"({len(channels)} channels, {len(all_records)} messages)."
        )
    except Exception as err:
        mark_failed(run_id, f"{type(err).__name__}: {err}")
        raise


def main() -> None:
    date_pt = get_yesterday_pt_date()
    oldest, latest = get_yesterday_pt_bounds()
    print(f"Running digest for {date_pt} (PT)")
    run_digest(date_pt, oldest, latest)


if __name__ == "__main__":
    main()
