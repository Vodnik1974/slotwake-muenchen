#!/usr/bin/env python3
"""Manually add / update a waitlist row (when IMAP is not set up yet)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# reuse tracker helpers by importing concierge module pieces
import concierge as c  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    p.add_argument("--service", default="wohnsitzanmeldung")
    p.add_argument("--offices", default="any")
    p.add_argument("--from", dest="date_from", default="")
    p.add_argument("--to", dest="date_to", default="")
    p.add_argument("--time", dest="time_of_day", default="either")
    p.add_argument("--urgency", default="14d")
    p.add_argument("--lang", dest="alert_lang", default="en")
    p.add_argument("--wtp", default="")
    p.add_argument("--notes", default="")
    args = p.parse_args()

    rows = c.load_rows()
    em = args.email.strip().lower()
    for r in rows:
        if (r.get("email") or "").lower() == em:
            r.update(
                {
                    "service": args.service,
                    "offices": args.offices,
                    "date_from": args.date_from,
                    "date_to": args.date_to,
                    "time_of_day": args.time_of_day,
                    "urgency": args.urgency,
                    "alert_lang": args.alert_lang,
                    "wtp": args.wtp,
                    "notes": args.notes,
                    "status": "watching",
                }
            )
            c.save_rows(rows)
            print(f"updated {em}")
            return 0

    row = {k: "" for k in c.TRACKER_FIELDS}
    row.update(
        {
            "email": em,
            "service": args.service,
            "offices": args.offices,
            "date_from": args.date_from,
            "date_to": args.date_to,
            "time_of_day": args.time_of_day,
            "urgency": args.urgency,
            "alert_lang": args.alert_lang,
            "wtp": args.wtp,
            "notes": args.notes,
            "status": "watching",
            "created_at": c.now_iso(),
            "alerts_sent": "0",
        }
    )
    rows.append(row)
    c.save_rows(rows)
    print(f"added {em}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
