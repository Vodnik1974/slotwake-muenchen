#!/usr/bin/env python3
"""One-shot München Bürgerbüro slot check + waitlist match (NOTIFY ONLY).

Uses sibling starnberg-termin ZMS adapter. Never books.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

STARNBERG = Path(
    os.getenv("STARNBERG_TERMIN_ROOT", str(ROOT.parent / "starnberg-termin"))
).resolve()
if not (STARNBERG / "regions" / "zms.py").exists():
    sys.exit(f"starnberg-termin not found at {STARNBERG} — set STARNBERG_TERMIN_ROOT")

sys.path.insert(0, str(STARNBERG))

from regions import get_region  # noqa: E402
from regions.zms import _headers, fetch_appointments  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")
BOOK_BASE = (
    "https://stadt.muenchen.de/buergerservice/terminvereinbarung.html"
    "#/services/{service}/locations/{office}"
)
SERVICE_MAP = {
    "wohnsitzanmeldung": 1063475,
    "wohnsitzanmeldung-familie": 10224132,
    "personalausweis": 1063441,
    "reisepass": 1063453,
}
OFFICE_NAME = {
    102522: "Orleansplatz",
    102523: "Leonrodstraße",
    102524: "Scheidplatz",
    102526: "Forstenrieder Allee",
    10489: "Ruppertstraße",
    54261: "Pasing",
}


def load_waitlist(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        print(f"no waitlist at {path} — copy data/waitlist.example.csv → data/waitlist.csv")
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def in_window(slot_dt: datetime, row: dict[str, str]) -> bool:
    d = slot_dt.date().isoformat()
    a = (row.get("date_from") or "").strip()
    b = (row.get("date_to") or "").strip()
    if a and d < a:
        return False
    if b and d > b:
        return False
    tod = (row.get("time_of_day") or "either").strip().lower()
    if tod == "morning" and slot_dt.hour >= 12:
        return False
    if tod == "afternoon" and slot_dt.hour < 12:
        return False
    return True


def wants_office(row: dict[str, str], office_id: int) -> bool:
    raw = (row.get("offices") or "any").lower()
    if "any" in raw or raw.strip() == "":
        return True
    aliases = {
        "orleans": 102522,
        "leonrod": 102523,
        "scheid": 102524,
        "forstenried": 102526,
        "ruppert": 10489,
        "pasing": 54261,
    }
    for key, oid in aliases.items():
        if key in raw and oid == office_id:
            return True
    return False


def ping(text: str) -> None:
    url = (os.getenv("SEND_WEBHOOK_URL") or "").strip()
    if not url:
        print("--- alert ---\n" + text + "\n")
        return
    # Slack incoming webhook OR generic JSON {text}
    r = requests.post(url, json={"text": text}, timeout=20)
    r.raise_for_status()
    print(f"webhook ok {r.status_code}")


def main() -> int:
    region = get_region("muenchen-anmeldung")
    if region is None:
        sys.exit("muenchen-anmeldung missing — pull latest starnberg-termin")

    session = requests.Session()
    _headers(session, region)
    slots = fetch_appointments(session, region)
    print(f"{len(slots)} open Wohnsitzanmeldung-related slots (region default service)")

    # Also pull other hot services if env set
    waitlist = load_waitlist(ROOT / "data" / "waitlist.csv")
    if not waitlist:
        for s in slots[:5]:
            oid = s["_zms"]["office_id"]
            print(
                f"  {s['date_time']} · {OFFICE_NAME.get(oid, oid)} · "
                + BOOK_BASE.format(service=s["_zms"]["service_id"], office=oid)
            )
        return 0

    matches = 0
    for row in waitlist:
        email = (row.get("email") or "").strip()
        if not email:
            continue
        want = SERVICE_MAP.get((row.get("service") or "").strip().lower(), 1063475)
        for s in slots:
            meta = s.get("_zms") or {}
            if int(meta.get("service_id") or 0) not in (want, 1063475) and want != 1063475:
                # default region fetch is Wohnsitz only; skip mismatch quietly
                if int(meta.get("service_id") or 0) != want:
                    continue
            oid = int(meta["office_id"])
            when = datetime.fromisoformat(s["datetime_iso8601"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=TZ)
            if not in_window(when, row):
                continue
            if not wants_office(row, oid):
                continue
            link = BOOK_BASE.format(service=meta["service_id"], office=oid)
            msg = (
                f"SlotWake match for {email}\n"
                f"{s['date_time']} · {OFFICE_NAME.get(oid, oid)}\n"
                f"Book yourself: {link}\n"
                f"(notify only — we do not book)"
            )
            ping(msg)
            matches += 1
            break  # one ping per subscriber per run
    print(f"matches notified: {matches}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
