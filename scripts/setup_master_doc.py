"""One-time setup helper: prints the IDs of the tabs in the master Doc.

Run once after manually creating the "Summaries" and "Transcripts" tabs.
Save the printed IDs to .env as SUMMARIES_TAB_ID and TRANSCRIPTS_TAB_ID.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
]


def load_credentials():
    """GOOGLE_SERVICE_ACCOUNT_JSON is either a file path (local) or raw JSON (CI)."""
    value = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not value:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")

    stripped = value.lstrip()
    if stripped.startswith("{"):
        info = json.loads(value)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    path = Path(value)
    if not path.is_file():
        raise RuntimeError(f"service account file not found: {value}")
    return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)


def main() -> int:
    load_dotenv()

    doc_id = os.environ.get("MASTER_DOC_ID")
    if not doc_id:
        print("ERROR: MASTER_DOC_ID is not set in .env", file=sys.stderr)
        return 1

    try:
        creds = load_credentials()
    except RuntimeError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    docs = build("docs", "v1", credentials=creds, cache_discovery=False)

    doc = docs.documents().get(documentId=doc_id, includeTabsContent=True).execute()

    tabs = doc.get("tabs", [])
    if not tabs:
        print(
            "No tabs returned."
            ,
            file=sys.stderr,
        )
        return 1

    print(f"Document: {doc.get('title', '(no title)')}")
    print(f"Tabs found: {len(tabs)}\n")
    for tab in tabs:
        props = tab.get("tabProperties", {})
        tab_id = props.get("tabId", "(no id)")
        title = props.get("title", "(no title)")
        print(f"  title: {title!r}")
        print(f"  tabId: {tab_id}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
