"""One-time backfill: run the digest for the last N days.

Usage:
    python -m scripts.backfill --days 7

Processes oldest day first so newer days insert above older ones in the Doc
(newest-at-top). Already-written days are skipped by run_digest's guard, so
re-running after a failure resumes safely.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from src.config import TIMEZONE, get_pt_bounds_for_date
from src.main import run_digest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill the digest for the last N days (ending yesterday)."
    )
    parser.add_argument(
        "--days", type=int, required=True, help="Number of days back to process."
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")

    today = datetime.now(TIMEZONE).date()
    dates = [today - timedelta(days=n) for n in range(args.days, 0, -1)]

    failures: list = []
    for d in dates:
        print(f"--- Backfilling {d} ---")
        oldest, latest = get_pt_bounds_for_date(d)
        try:
            run_digest(d, oldest, latest)
        except Exception as err:
            print(f"{d}: FAILED - {type(err).__name__}: {err}")
            failures.append(d)

    if failures:
        print(f"\nBackfill finished with {len(failures)} failure(s): {failures}")
        raise SystemExit(1)
    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
