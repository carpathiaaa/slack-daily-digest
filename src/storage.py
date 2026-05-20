"""Supabase: persist raw Slack messages and track digest run status."""

from __future__ import annotations

from datetime import date, datetime, timezone

from supabase import Client, create_client

from src.config import SUPABASE_KEY, SUPABASE_URL

_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_messages(records: list[dict], digest_date: date) -> int:
    """Insert normalized Slack records, skipping any already stored. Returns count submitted."""
    if not records:
        return 0
    rows = [
        {
            "channel_id": r["channel_id"],
            "channel_name": r["channel_name"],
            "message_ts": r["ts"],
            "thread_ts": r["thread_ts"],
            "user_id": r["user_id"],
            "user_name": r["user_name"],
            "text": r["text"],
            "raw_json": r["raw_json"],
            "digest_date": digest_date.isoformat(),
        }
        for r in records
    ]
    _client.table("slack_raw_messages").upsert(
        rows, on_conflict="channel_id,message_ts", ignore_duplicates=True
    ).execute()
    return len(rows)


def _row_to_record(row: dict) -> dict:
    """DB row back into the normalized shape slack_fetcher produces."""
    message_ts = row["message_ts"]
    thread_ts = row.get("thread_ts")
    return {
        "channel_id": row["channel_id"],
        "channel_name": row["channel_name"],
        "user_id": row.get("user_id") or "",
        "user_name": row.get("user_name") or "",
        "ts": message_ts,
        "text": row.get("text") or "",
        "thread_ts": thread_ts,
        "is_thread_reply": bool(thread_ts and thread_ts != message_ts),
        "raw_json": row.get("raw_json") or {},
    }


def get_messages_for_date(digest_date: date) -> list[dict]:
    resp = (
        _client.table("slack_raw_messages")
        .select("*")
        .eq("digest_date", digest_date.isoformat())
        .order("message_ts")
        .execute()
    )
    return [_row_to_record(row) for row in resp.data]


def start_run(digest_date: date) -> str:
    """Create or reset the digest_runs row for this date. Returns run id."""
    resp = (
        _client.table("digest_runs")
        .upsert(
            {
                "digest_date": digest_date.isoformat(),
                "status": "pending",
                "channels_processed": 0,
                "messages_fetched": 0,
                "error_message": None,
                "started_at": _utc_now_iso(),
                "completed_at": None,
            },
            on_conflict="digest_date",
        )
        .execute()
    )
    return resp.data[0]["id"]


def get_run_status(digest_date: date) -> str | None:
    """Status of the digest_runs row for this date, or None if there is none."""
    resp = (
        _client.table("digest_runs")
        .select("status")
        .eq("digest_date", digest_date.isoformat())
        .limit(1)
        .execute()
    )
    return resp.data[0]["status"] if resp.data else None


def mark_fetched(run_id: str, channels_processed: int, messages_fetched: int) -> None:
    _client.table("digest_runs").update(
        {
            "status": "fetched",
            "channels_processed": channels_processed,
            "messages_fetched": messages_fetched,
        }
    ).eq("id", run_id).execute()


def mark_summarized(run_id: str) -> None:
    _client.table("digest_runs").update({"status": "summarized"}).eq(
        "id", run_id
    ).execute()


def mark_written(run_id: str) -> None:
    _client.table("digest_runs").update(
        {"status": "written", "completed_at": _utc_now_iso()}
    ).eq("id", run_id).execute()


def mark_failed(run_id: str, error_message: str) -> None:
    _client.table("digest_runs").update(
        {
            "status": "failed",
            "error_message": error_message,
            "completed_at": _utc_now_iso(),
        }
    ).eq("id", run_id).execute()


def main() -> None:
    from src.config import get_yesterday_pt_bounds, get_yesterday_pt_date
    from src.slack_fetcher import fetch_channel_day, list_public_channels

    digest_date = get_yesterday_pt_date()
    oldest, latest = get_yesterday_pt_bounds()

    run_id = start_run(digest_date)
    print(f"Started run {run_id} for {digest_date}")

    channels = list_public_channels()
    all_records: list[dict] = []
    for ch in channels:
        all_records.extend(fetch_channel_day(ch, oldest, latest))

    submitted = upsert_messages(all_records, digest_date)
    mark_fetched(run_id, len(channels), submitted)
    print(f"Upserted {submitted} record(s) from {len(channels)} channel(s)")

    readback = get_messages_for_date(digest_date)
    print(f"Read back {len(readback)} record(s) for {digest_date}")
    if readback:
        sample = readback[0]
        print(f"  sample: [{sample['ts']}] {sample['user_name']}: {sample['text'][:60]}")


if __name__ == "__main__":
    main()
