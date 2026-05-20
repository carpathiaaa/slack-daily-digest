"""Google Docs: append a day's summaries and transcripts into the master Doc.

Newest-at-top. Each channel heading in the Summaries tab links to the matching
channel heading in the Transcripts tab.
"""

from __future__ import annotations

from datetime import date, datetime

from googleapiclient.discovery import build

from src.config import (
    MASTER_DOC_ID,
    SUMMARIES_TAB_ID,
    TIMEZONE,
    TRANSCRIPTS_TAB_ID,
    load_google_credentials,
)

_SCOPES = ["https://www.googleapis.com/auth/documents"]

_SECTION_ORDER = [
    ("key_decisions", "Key Decisions"),
    ("action_items", "Action Items"),
    ("open_questions", "Open Questions"),
    ("notable_discussions", "Notable Discussions"),
    ("participants", "Participants"),
]

_INDENT_STEP_PT = 18  # one indent level, roughly 0.25 inch


def _docs_service():
    creds = load_google_credentials(_SCOPES)
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def _u16len(s: str) -> int:
    """Length in UTF-16 code units, which is how the Docs API counts indices."""
    return len(s.encode("utf-16-le")) // 2


def _format_ts(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), TIMEZONE).strftime("%H:%M")


def _summary_lines(
    date_pt: date, channel_entries: list[dict]
) -> list[tuple[str, str, int]]:
    lines: list[tuple[str, str, int]] = [(date_pt.isoformat(), "h1", 0)]
    for entry in channel_entries:
        lines.append((f"#{entry['channel_name']}", "h2", 0))
        summary = entry["summary"]
        for key, label in _SECTION_ORDER:
            lines.append((label, "bold", 0))
            value = (summary.get(key) or "None.").strip()
            body = [ln for ln in value.splitlines() if ln.strip()] or ["None."]
            for ln in body:
                lines.append((ln, "normal", 1))
    return lines


def _transcript_lines(
    date_pt: date, channel_entries: list[dict]
) -> list[tuple[str, str, int]]:
    lines: list[tuple[str, str, int]] = [(date_pt.isoformat(), "h1", 0)]
    for entry in channel_entries:
        lines.append((f"#{entry['channel_name']}", "h2", 0))
        messages = entry["messages"]
        if not messages:
            lines.append(("(no messages)", "normal", 0))
            continue
        for m in messages:
            indent = 1 if m["is_thread_reply"] else 0
            display = f"[{_format_ts(m['ts'])}] {m['user_name']}: {m['text'] or ''}"
            for part in display.split("\n"):
                lines.append((part, "normal", indent))
    return lines


def _block_text(lines: list[tuple[str, str, int]]) -> str:
    return "".join(content + "\n" for content, _, _ in lines)


def _build_requests(
    lines: list[tuple[str, str, int]],
    tab_id: str,
    heading_links: dict[str, dict] | None = None,
) -> list[dict]:
    """batchUpdate requests that prepend `lines` at the top of a tab.

    heading_links maps an h2 line's text to a HeadingLink ({id, tabId}); when
    present, that heading's text is turned into a link to the given heading.
    """
    full_text = _block_text(lines)
    if not full_text:
        return []

    block_len = _u16len(full_text)
    whole = {"startIndex": 1, "endIndex": 1 + block_len, "tabId": tab_id}

    requests: list[dict] = [
        {"insertText": {"location": {"index": 1, "tabId": tab_id}, "text": full_text}},
        {
            "updateParagraphStyle": {
                "range": whole,
                "paragraphStyle": {
                    "namedStyleType": "NORMAL_TEXT",
                    "indentStart": {"magnitude": 0, "unit": "PT"},
                    "indentFirstLine": {"magnitude": 0, "unit": "PT"},
                },
                "fields": "namedStyleType,indentStart,indentFirstLine",
            }
        },
        {
            "updateTextStyle": {
                "range": whole,
                "textStyle": {"bold": False},
                "fields": "bold,link",
            }
        },
    ]

    offset = 0
    for content, kind, indent in lines:
        line_len = _u16len(content) + 1  # trailing newline
        start = 1 + offset
        content_len = _u16len(content)
        para_range = {
            "startIndex": start,
            "endIndex": start + line_len,
            "tabId": tab_id,
        }
        text_range = {
            "startIndex": start,
            "endIndex": start + content_len,
            "tabId": tab_id,
        }
        if kind in ("h1", "h2"):
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": para_range,
                        "paragraphStyle": {
                            "namedStyleType": "HEADING_1"
                            if kind == "h1"
                            else "HEADING_2"
                        },
                        "fields": "namedStyleType",
                    }
                }
            )
        elif kind == "bold":
            if content_len > 0:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": text_range,
                            "textStyle": {"bold": True},
                            "fields": "bold",
                        }
                    }
                )
        if (
            kind == "h2"
            and content_len > 0
            and heading_links
            and content in heading_links
        ):
            requests.append(
                {
                    "updateTextStyle": {
                        "range": text_range,
                        "textStyle": {"link": {"heading": heading_links[content]}},
                        "fields": "link",
                    }
                }
            )
        if indent > 0:
            magnitude = _INDENT_STEP_PT * indent
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": para_range,
                        "paragraphStyle": {
                            "indentStart": {"magnitude": magnitude, "unit": "PT"},
                            "indentFirstLine": {"magnitude": magnitude, "unit": "PT"},
                        },
                        "fields": "indentStart,indentFirstLine",
                    }
                }
            )
        offset += line_len
    return requests


def _find_tab(doc: dict, tab_id: str) -> dict | None:
    for tab in doc.get("tabs", []):
        if tab.get("tabProperties", {}).get("tabId") == tab_id:
            return tab
    return None


def _collect_heading_links(
    doc: dict, tab_id: str, block_len: int
) -> dict[str, dict]:
    """Map each H2 heading text in the freshly inserted top block to a
    HeadingLink ({id, tabId}) pointing at it."""
    tab = _find_tab(doc, tab_id)
    if tab is None:
        return {}
    links: dict[str, dict] = {}
    content = tab.get("documentTab", {}).get("body", {}).get("content", [])
    for element in content:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        style = paragraph.get("paragraphStyle", {})
        if style.get("namedStyleType") != "HEADING_2":
            continue
        start = element.get("startIndex", 0)
        if not 1 <= start < 1 + block_len:
            continue
        text = "".join(
            e.get("textRun", {}).get("content", "")
            for e in paragraph.get("elements", [])
        ).rstrip("\n")
        heading_id = style.get("headingId")
        if text and heading_id:
            links[text] = {"id": heading_id, "tabId": tab_id}
    return links


def append_daily_entry(date_pt: date, channel_entries: list[dict]) -> None:
    """Prepend one day to both tabs. channel_entries: list of
    {channel_name, summary: dict, messages: list}."""
    service = _docs_service()
    doc = (
        service.documents()
        .get(documentId=MASTER_DOC_ID, includeTabsContent=True)
        .execute()
    )
    tab_ids = {
        t.get("tabProperties", {}).get("tabId") for t in doc.get("tabs", [])
    }
    for needed in (SUMMARIES_TAB_ID, TRANSCRIPTS_TAB_ID):
        if needed not in tab_ids:
            raise RuntimeError(f"Tab id not found in document: {needed}")

    transcript_lines = _transcript_lines(date_pt, channel_entries)
    transcript_requests = _build_requests(transcript_lines, TRANSCRIPTS_TAB_ID)

    heading_links: dict[str, dict] = {}
    if transcript_requests:
        service.documents().batchUpdate(
            documentId=MASTER_DOC_ID, body={"requests": transcript_requests}
        ).execute()
        refreshed = (
            service.documents()
            .get(documentId=MASTER_DOC_ID, includeTabsContent=True)
            .execute()
        )
        heading_links = _collect_heading_links(
            refreshed, TRANSCRIPTS_TAB_ID, _u16len(_block_text(transcript_lines))
        )

    summary_requests = _build_requests(
        _summary_lines(date_pt, channel_entries), SUMMARIES_TAB_ID, heading_links
    )
    if summary_requests:
        service.documents().batchUpdate(
            documentId=MASTER_DOC_ID, body={"requests": summary_requests}
        ).execute()


def main() -> None:
    from src.config import get_yesterday_pt_bounds, get_yesterday_pt_date
    from src.slack_fetcher import fetch_channel_day, list_public_channels
    from src.summarizer import summarize_channel_day

    date_pt = get_yesterday_pt_date()
    oldest, latest = get_yesterday_pt_bounds()

    channel_entries: list[dict] = []
    for ch in list_public_channels():
        messages = fetch_channel_day(ch, oldest, latest)
        summary = summarize_channel_day(ch["name"], messages, date_pt)
        channel_entries.append(
            {"channel_name": ch["name"], "summary": summary, "messages": messages}
        )

    append_daily_entry(date_pt, channel_entries)
    print(f"Appended {date_pt} to both tabs ({len(channel_entries)} channel(s)).")


if __name__ == "__main__":
    main()
