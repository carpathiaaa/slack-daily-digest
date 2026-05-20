# Slack Daily Digest

A daily automation that archives public Slack channel messages from the Pareto
Labs workspace into a Google Doc. It generates LLM summaries for fast scanning
and keeps full transcripts for fidelity. Built to retain Slack history without
paying for Slack Premium, which hides messages older than 90 days.

## How it works

A GitHub Actions cron job runs once a day around 7am PT:

1. Fetches the previous PT day's messages and thread replies from every public
   channel the bot is a member of (Slack API).
2. Stores raw messages in Supabase as a safety net for re-summarizing later.
3. Summarizes each channel's day with Groq (Llama 3.3 70B).
4. Appends the result to a master Google Doc with two tabs, `Summaries` and
   `Transcripts`, newest day on top.

## Prerequisites

One-time manual setup, done outside this repo:

- **Slack app** with bot scopes `channels:read`, `channels:history`,
  `users:read`, installed to the workspace and invited to each public channel.
- **Google Cloud project** with the Docs API and Drive API enabled, plus a
  service account and its JSON key.
- **Master Google Doc** with two manually created tabs named exactly
  `Summaries` and `Transcripts`, shared with the service account as Editor.
  Google Docs API cannot create tabs, so they must be made by hand once.
- **Supabase project** with the schema below applied.
- **Groq API key** from console.groq.com.

## Configuration

Copy `.env.example` to `.env` and fill in the values. `.env` is gitignored.

| Variable | What it is |
|---|---|
| `SLACK_BOT_TOKEN` | Slack bot token, `xoxb-...` |
| `GROQ_API_KEY` | Groq API key, `gsk_...` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Local: path to the JSON key file. CI: the JSON content itself. |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase `service_role` key |
| `MASTER_DOC_ID` | ID of the master Google Doc |
| `SUMMARIES_TAB_ID` | Tab ID of the Summaries tab |
| `TRANSCRIPTS_TAB_ID` | Tab ID of the Transcripts tab |

The same eight values must also be set as repository secrets in GitHub for the
scheduled run to work.

## Supabase schema

Run once in the Supabase SQL editor:

```sql
create table slack_raw_messages (
  id uuid primary key default gen_random_uuid(),
  channel_id text not null,
  channel_name text not null,
  message_ts text not null,
  thread_ts text,
  user_id text,
  user_name text,
  text text,
  raw_json jsonb not null,
  digest_date date not null,
  inserted_at timestamptz default now(),
  unique(channel_id, message_ts)
);

create index on slack_raw_messages(digest_date, channel_id);

create table digest_runs (
  id uuid primary key default gen_random_uuid(),
  digest_date date not null unique,
  status text not null,
  channels_processed int default 0,
  messages_fetched int default 0,
  error_message text,
  started_at timestamptz default now(),
  completed_at timestamptz
);
```

## Local development

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Print the tab IDs after creating the Doc tabs:

```powershell
python scripts/setup_master_doc.py
```

Run the digest for yesterday:

```powershell
python -m src.main
```

Backfill the last N days (oldest first, so the Doc stays newest-on-top):

```powershell
python -m scripts.backfill --days 7
```

## Scheduling

`.github/workflows/daily-digest.yml` runs the digest daily at 14:00 UTC, which
is about 7am PT during DST and 6am PST otherwise. It can also be triggered
manually from the GitHub Actions tab via `workflow_dispatch`. The job runs on
GitHub's runners, so no local machine needs to be on.

## Re-running

Each run is tracked in the `digest_runs` table. A date already marked `written`
is skipped on later runs to avoid duplicate entries in the Doc. To force a
re-write of a date, delete its row from `digest_runs` first, then run again.

## Project layout

```
src/
  main.py            orchestrator: fetch -> store -> summarize -> write
  slack_fetcher.py   Slack API
  storage.py         Supabase
  summarizer.py      Groq
  docs_writer.py     Google Docs
  config.py          env vars, timezone, time bounds
  templates/
    summary_prompt.txt
scripts/
  setup_master_doc.py  one-time, prints tab IDs
  backfill.py          one-time, --days N
```

See `CLAUDE.md` for the full list of locked-in design decisions and the
constraints behind them.
