"""Slack API: list channels, fetch messages + thread replies, resolve user names."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.config import SLACK_BOT_TOKEN, TIMEZONE, get_yesterday_pt_bounds, get_yesterday_pt_date

_client = WebClient(token=SLACK_BOT_TOKEN)
_user_name_cache: dict[str, str] = {}


def list_public_channels() -> list[dict]:
    """All public channels the bot is a member of."""
    out: list[dict] = []
    cursor = None
    while True:
        resp = _client.conversations_list(
            types="public_channel",
            exclude_archived=True,
            limit=200,
            cursor=cursor,
        )
        for ch in resp["channels"]:
            if ch.get("is_member"):
                out.append({"id": ch["id"], "name": ch["name"]})
        cursor = resp.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    return out


def fetch_channel_messages(channel_id: str, oldest: str, latest: str) -> list[dict]:
    """Top-level messages in [oldest, latest). Does not include thread replies."""
    out: list[dict] = []
    cursor = None
    while True:
        resp = _client.conversations_history(
            channel=channel_id,
            oldest=oldest,
            latest=latest,
            inclusive=True,
            limit=200,
            cursor=cursor,
        )
        out.extend(resp["messages"])
        cursor = resp.get("response_metadata", {}).get("next_cursor") or None
        if not cursor or not resp.get("has_more"):
            break
    return out


def fetch_thread_replies(channel_id: str, thread_ts: str) -> list[dict]:
    """All replies in a thread, excluding the parent message itself."""
    out: list[dict] = []
    cursor = None
    while True:
        resp = _client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=200,
            cursor=cursor,
        )
        for m in resp["messages"]:
            if m.get("ts") != thread_ts:
                out.append(m)
        cursor = resp.get("response_metadata", {}).get("next_cursor") or None
        if not cursor or not resp.get("has_more"):
            break
    return out


def resolve_user_names(user_ids: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for uid in set(uid for uid in user_ids if uid):
        if uid in _user_name_cache:
            out[uid] = _user_name_cache[uid]
            continue
        try:
            resp = _client.users_info(user=uid)
            u = resp["user"]
            name = u.get("real_name") or u.get("name") or uid
        except SlackApiError:
            name = uid
        _user_name_cache[uid] = name
        out[uid] = name
    return out


def _normalize(msg: dict, channel_id: str, channel_name: str, user_names: dict[str, str]) -> dict:
    uid = msg.get("user") or msg.get("bot_id") or ""
    thread_ts = msg.get("thread_ts")
    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "user_id": uid,
        "user_name": user_names.get(uid, uid),
        "ts": msg["ts"],
        "text": msg.get("text", ""),
        "thread_ts": thread_ts,
        "is_thread_reply": bool(thread_ts and thread_ts != msg["ts"]),
        "raw_json": msg,
    }


def fetch_channel_day(channel: dict, oldest: str, latest: str) -> list[dict]:
    """Normalized records for one channel: top-level messages + thread replies, in order."""
    parents = fetch_channel_messages(channel["id"], oldest, latest)
    parents.sort(key=lambda m: float(m["ts"]))

    all_messages: list[tuple[dict, list[dict]]] = []
    user_ids: set[str] = set()
    for p in parents:
        replies: list[dict] = []
        if p.get("reply_count", 0) > 0 and p.get("thread_ts"):
            replies = fetch_thread_replies(channel["id"], p["thread_ts"])
        all_messages.append((p, replies))
        if p.get("user"):
            user_ids.add(p["user"])
        for r in replies:
            if r.get("user"):
                user_ids.add(r["user"])

    user_names = resolve_user_names(user_ids)

    out: list[dict] = []
    for parent, replies in all_messages:
        out.append(_normalize(parent, channel["id"], channel["name"], user_names))
        for r in sorted(replies, key=lambda m: float(m["ts"])):
            out.append(_normalize(r, channel["id"], channel["name"], user_names))
    return out


def _format_ts(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), TIMEZONE).strftime("%H:%M")


def _print_channel(channel: dict, records: list[dict]) -> None:
    print(f"\n=== #{channel['name']} ({len(records)} messages) ===")
    if not records:
        print("  (no messages)")
        return
    for r in records:
        prefix = "    " if r["is_thread_reply"] else "  "
        text = r["text"].replace("\n", " ")
        print(f"{prefix}[{_format_ts(r['ts'])}] {r['user_name']}: {text}")


def main() -> None:
    oldest, latest = get_yesterday_pt_bounds()
    target_date = get_yesterday_pt_date()
    print(f"Fetching messages for {target_date} (PT) [oldest={oldest}, latest={latest}]")

    channels = list_public_channels()
    print(f"Bot is in {len(channels)} public channel(s): {[c['name'] for c in channels]}")

    for ch in channels:
        records = fetch_channel_day(ch, oldest, latest)
        _print_channel(ch, records)


if __name__ == "__main__":
    main()
