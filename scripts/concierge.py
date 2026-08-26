#!/usr/bin/env python3
"""SlotWake München concierge — notify-only automation.

Flow each run:
  1) Optional IMAP ingest of FormSubmit signup emails → waitlist.csv
  2) Fetch ZMS slots (services needed by waitlist)
  3) Match subscribers (default: urgency=14d)
  4) Email them the official booking link (SMTP)
  5) Ping you on Telegram / macOS notification
  6) Update tracker status — never books

Usage:
  .venv/bin/python scripts/concierge.py
  .venv/bin/python scripts/concierge.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import email as email_lib
import imaplib
import json
import logging
import os
import re
import smtplib
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from email.header import decode_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
# reuse operator telegram target from sniper .env if present
load_dotenv(
    Path(os.getenv("STARNBERG_TERMIN_ROOT", str(ROOT.parent / "starnberg-termin")))
    / ".env",
    override=False,
)

STARNBERG = Path(
    os.getenv("STARNBERG_TERMIN_ROOT", str(ROOT.parent / "starnberg-termin"))
).resolve()
if not (STARNBERG / "regions" / "zms.py").exists():
    sys.exit(f"starnberg-termin not found at {STARNBERG}")

sys.path.insert(0, str(STARNBERG))

from regions import get_region  # noqa: E402
from regions.zms import _headers, fetch_appointments  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")
LOG = logging.getLogger("slotwake")
WAITLIST = ROOT / "data" / "waitlist.csv"
STATE = ROOT / "data" / "alert_state.json"
TRACKER_FIELDS = [
    "email",
    "service",
    "offices",
    "date_from",
    "date_to",
    "time_of_day",
    "urgency",
    "alert_lang",
    "wtp",
    "notes",
    "status",
    "created_at",
    "last_alert_at",
    "last_slot",
    "alerts_sent",
]
BOOK_BASE = (
    "https://stadt.muenchen.de/buergerservice/terminvereinbarung.html"
    "#/services/{service}/locations/{office}"
)
SERVICE_MAP = {
    "wohnsitzanmeldung": 1063475,
    "wohnsitzanmeldung-familie": 10224132,
    "personalausweis": 1063441,
    "reisepass": 1063453,
    "meldebescheinigung": 1063576,
}
SERVICE_LABEL = {v: k for k, v in SERVICE_MAP.items()}
OFFICE_NAME = {
    102522: "Orleansplatz",
    102523: "Leonrodstraße",
    102524: "Scheidplatz",
    102526: "Forstenrieder Allee",
    10489: "Ruppertstraße",
    54261: "Pasing",
}
OFFICES_DEFAULT = "102522,102523,102524,102526,10489,54261"


def setup_log() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def load_rows() -> list[dict[str, str]]:
    if not WAITLIST.exists():
        WAITLIST.parent.mkdir(parents=True, exist_ok=True)
        with WAITLIST.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=TRACKER_FIELDS).writeheader()
        return []
    with WAITLIST.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # migrate old header
    out = []
    for r in rows:
        row = {k: (r.get(k) or "").strip() for k in TRACKER_FIELDS}
        if not row["status"]:
            row["status"] = "watching"
        if not row["created_at"]:
            row["created_at"] = now_iso()
        if not row["alerts_sent"]:
            row["alerts_sent"] = "0"
        out.append(row)
    return out


def save_rows(rows: list[dict[str, str]]) -> None:
    WAITLIST.parent.mkdir(parents=True, exist_ok=True)
    with WAITLIST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRACKER_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in TRACKER_FIELDS})


def load_state() -> dict[str, Any]:
    if not STATE.exists():
        return {"sent": {}}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"sent": {}}


def save_state(data: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def in_business_hours() -> bool:
    if os.getenv("CONCIERGE_FORCE", "").strip() in {"1", "true", "yes"}:
        return True
    h = datetime.now(TZ).hour
    start = int(os.getenv("CONCIERGE_HOUR_START", "6"))
    end = int(os.getenv("CONCIERGE_HOUR_END", "19"))
    return start <= h < end


def in_window(slot_dt: datetime, row: dict[str, str]) -> bool:
    d = slot_dt.date().isoformat()
    a = row.get("date_from") or ""
    b = row.get("date_to") or ""
    if a and d < a:
        return False
    if b and d > b:
        return False
    tod = (row.get("time_of_day") or "either").lower()
    if tod == "morning" and slot_dt.hour >= 12:
        return False
    if tod == "afternoon" and slot_dt.hour < 12:
        return False
    return True


def wants_office(row: dict[str, str], office_id: int) -> bool:
    raw = (row.get("offices") or "any").lower()
    if "any" in raw or not raw.strip():
        return True
    aliases = {
        "orleans": 102522,
        "leonrod": 102523,
        "scheid": 102524,
        "forstenried": 102526,
        "ruppert": 10489,
        "pasing": 54261,
    }
    return any(k in raw and oid == office_id for k, oid in aliases.items())


def urgency_ok(row: dict[str, str]) -> bool:
    mode = (os.getenv("CONCIERGE_URGENCY", "14d") or "14d").strip().lower()
    if mode in {"all", "*"}:
        return True
    u = (row.get("urgency") or "").strip().lower()
    return u == mode or u == ""


def decode_mime(val: str | None) -> str:
    if not val:
        return ""
    parts = decode_header(val)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def parse_formsubmit_body(body: str) -> dict[str, str]:
    """Extract Name/Value pairs from FormSubmit plain/html mail."""
    data: dict[str, str] = {}
    # plain table-ish: "email\tfoo" or "email  foo"
    for m in re.finditer(
        r"(?im)^(product|email|service|offices|date_from|date_to|time_of_day|"
        r"urgency|alert_lang|wtp|notes|consent)\s*[:=\t]+\s*(.+?)\s*$",
        body,
    ):
        data[m.group(1).lower()] = m.group(2).strip()
    # HTML <td>Name</td><td>Value</td>
    for m in re.finditer(
        r"(?is)<t[dh][^>]*>\s*(product|email|service|offices|date_from|date_to|"
        r"time_of_day|urgency|alert_lang|wtp|notes|consent)\s*</t[dh]>\s*"
        r"<t[dh][^>]*>\s*(.*?)\s*</t[dh]>",
        body,
    ):
        val = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        data[m.group(1).lower()] = val
    return data


def ingest_imap(rows: list[dict[str, str]]) -> int:
    """Pull FormSubmit mails and upsert into waitlist. Returns new count."""
    user = (
        os.getenv("IMAP_USER")
        or os.getenv("SMTP_USER")
        or os.getenv("EMAIL")
        or ""
    ).strip()
    password = (
        os.getenv("IMAP_PASS")
        or os.getenv("SMTP_PASS")
        or os.getenv("GMAIL_APP_PASSWORD")
        or ""
    ).strip()
    host = (os.getenv("IMAP_HOST") or "imap.gmail.com").strip()
    if not user or not password:
        LOG.info("IMAP not configured — skip signup ingest")
        return 0

    by_email = {(r.get("email") or "").lower(): r for r in rows if r.get("email")}
    added = 0
    try:
        M = imaplib.IMAP4_SSL(host)
        M.login(user, password)
        M.select("INBOX")
        typ, data = M.search(None, '(UNSEEN FROM "formsubmit.co")')
        if typ != "OK":
            typ, data = M.search(None, '(UNSEEN SUBJECT "SlotWake")')
        ids = data[0].split() if data and data[0] else []
        LOG.info("IMAP unseen FormSubmit/SlotWake: %s", len(ids))
        for num in ids:
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email_lib.message_from_bytes(msg_data[0][1])
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype in {"text/plain", "text/html"}:
                        try:
                            body += part.get_payload(decode=True).decode(
                                part.get_content_charset() or "utf-8",
                                errors="replace",
                            )
                        except Exception:
                            continue
            else:
                try:
                    body = msg.get_payload(decode=True).decode(
                        msg.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    body = str(msg.get_payload())
            fields = parse_formsubmit_body(body)
            em = (fields.get("email") or "").strip().lower()
            if not em or "@" not in em:
                continue
            if em in by_email:
                LOG.info("signup already tracked: %s", em)
                continue
            row = {k: "" for k in TRACKER_FIELDS}
            row.update(
                {
                    "email": em,
                    "service": fields.get("service") or "wohnsitzanmeldung",
                    "offices": fields.get("offices") or "any",
                    "date_from": fields.get("date_from") or "",
                    "date_to": fields.get("date_to") or "",
                    "time_of_day": fields.get("time_of_day") or "either",
                    "urgency": fields.get("urgency") or "14d",
                    "alert_lang": fields.get("alert_lang") or "en",
                    "wtp": fields.get("wtp") or "",
                    "notes": fields.get("notes") or "",
                    "status": "watching",
                    "created_at": now_iso(),
                    "alerts_sent": "0",
                }
            )
            rows.append(row)
            by_email[em] = row
            added += 1
            LOG.info("ingested signup %s (%s)", em, row["service"])
        M.logout()
    except Exception as exc:
        LOG.warning("IMAP ingest failed: %s", exc)
    return added


def fetch_all_slots(
    session: requests.Session, rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    base = get_region("muenchen-anmeldung")
    if base is None:
        raise RuntimeError("muenchen-anmeldung missing")
    _headers(session, base)
    wanted = {
        int(SERVICE_MAP.get((r.get("service") or "").lower(), 1063475))
        for r in rows
        if (r.get("status") or "") not in {"booked", "unsubscribed", "expired"}
    } or {1063475}
    out: list[dict[str, Any]] = []
    for sid in sorted(wanted):
        region = replace(
            base,
            service_uid=str(sid),
            calendar_uid=OFFICES_DEFAULT if sid != 1063576 else "10489",
            service_label=SERVICE_LABEL.get(sid, str(sid)),
        )
        try:
            slots = fetch_appointments(session, region)
        except Exception as exc:
            LOG.warning("fetch service %s failed: %s", sid, exc)
            continue
        LOG.info("service %s (%s): %s slots", sid, region.service_label, len(slots))
        out.extend(slots)
    return out


def send_smtp(to: str, subject: str, body: str, *, dry_run: bool) -> bool:
    user = (os.getenv("SMTP_USER") or os.getenv("EMAIL") or "").strip()
    password = (
        os.getenv("SMTP_PASS") or os.getenv("GMAIL_APP_PASSWORD") or ""
    ).strip()
    host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT") or "587")
    from_addr = (os.getenv("SMTP_FROM") or user).strip()
    if dry_run:
        LOG.info("DRY-RUN would email %s :: %s", to, subject)
        return True
    if not user or not password:
        LOG.warning("SMTP not configured — cannot email %s", to)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)
    LOG.info("emailed %s", to)
    return True


def notify_operator(title: str, body: str, *, dry_run: bool) -> None:
    text = f"{title}\n{body}"
    LOG.info("OPERATOR %s", text.replace("\n", " | "))
    if dry_run:
        return
    webhook = (os.getenv("SEND_WEBHOOK_URL") or "").strip()
    if webhook:
        try:
            requests.post(webhook, json={"text": text}, timeout=20)
        except Exception as exc:
            LOG.warning("webhook failed: %s", exc)
    bot = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if bot and chat:
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot}/sendMessage",
                json={"chat_id": chat, "text": text},
                timeout=20,
            )
        except Exception as exc:
            LOG.warning("telegram bot failed: %s", exc)
    target = (os.getenv("TELEGRAM_TARGET") or "").strip()
    hermes = Path.home() / ".local/bin/hermes"
    if hermes.exists() and target:
        try:
            subprocess.run(
                [str(hermes), "send", "--to", target, text],
                check=False,
                timeout=30,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            LOG.warning("hermes failed: %s", exc)
    if os.name == "darwin":
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification {json.dumps(body[:180])} with title {json.dumps(title)}',
                ],
                check=False,
                timeout=10,
            )
        except Exception:
            pass


def alert_body(lang: str, when: str, office: str, link: str) -> tuple[str, str]:
    if (lang or "en").lower().startswith("de"):
        subject = f"SlotWake: freier Bürgerbüro-Termin {when}"
        body = (
            f"Es gibt einen passenden Termin:\n\n"
            f"{when} · {office}\n\n"
            f"Jetzt selbst auf der Stadtseite buchen (wir buchen nicht für dich):\n"
            f"{link}\n\n"
            f"SlotWake München — nur Benachrichtigung, nicht die Stadt München.\n"
            f"Zum Abbestellen antworte auf diese Mail mit STOP.\n"
        )
    else:
        subject = f"SlotWake: Munich Bürgerbüro slot {when}"
        body = (
            f"A matching appointment just showed up:\n\n"
            f"{when} · {office}\n\n"
            f"Book it yourself on the city site (we do not book for you):\n"
            f"{link}\n\n"
            f"SlotWake München — notify only, not the City of Munich.\n"
            f"To unsubscribe, reply STOP.\n"
        )
    return subject, body


def main() -> int:
    setup_log()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-hours", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run or os.getenv("DRY_RUN", "").strip() in {"1", "true", "yes"}

    if not args.force_hours and not in_business_hours():
        LOG.info("outside concierge hours — exit")
        return 0

    rows = load_rows()
    added = ingest_imap(rows)
    if added:
        save_rows(rows)
        notify_operator(
            "SlotWake signups",
            f"{added} new waitlist row(s) ingested",
            dry_run=dry,
        )

    session = requests.Session()
    slots = fetch_all_slots(session, rows)
    state = load_state()
    sent: dict[str, str] = dict(state.get("sent") or {})

    active = [
        r
        for r in rows
        if (r.get("status") or "") not in {"booked", "unsubscribed", "expired"}
        and urgency_ok(r)
        and (r.get("email") or "")
    ]
    LOG.info("slots=%s active_subscribers=%s", len(slots), len(active))

    matched = 0
    for row in active:
        email = row["email"].lower()
        want = SERVICE_MAP.get((row.get("service") or "").lower(), 1063475)
        for s in slots:
            meta = s.get("_zms") or {}
            sid = int(meta.get("service_id") or 0)
            if sid != want:
                continue
            oid = int(meta["office_id"])
            when = datetime.fromisoformat(s["datetime_iso8601"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=TZ)
            if not in_window(when, row):
                continue
            if not wants_office(row, oid):
                continue
            key = f"{email}|{meta.get('timestamp')}"
            if key in sent:
                continue
            link = BOOK_BASE.format(service=sid, office=oid)
            office = OFFICE_NAME.get(oid, str(oid))
            subject, body = alert_body(
                row.get("alert_lang") or "en", s["date_time"], office, link
            )
            ok = send_smtp(email, subject, body, dry_run=dry)
            notify_operator(
                "SlotWake alert",
                f"{email}\n{s['date_time']} · {office}\n{link}\nmail={'ok' if ok else 'FAILED'}",
                dry_run=dry,
            )
            if ok or dry:
                sent[key] = now_iso()
                row["status"] = "alerted"
                row["last_alert_at"] = now_iso()
                row["last_slot"] = f"{s['date_time']} {office}"
                try:
                    row["alerts_sent"] = str(int(row.get("alerts_sent") or "0") + 1)
                except ValueError:
                    row["alerts_sent"] = "1"
                matched += 1
                break

    state["sent"] = sent
    state["last_run"] = now_iso()
    state["last_slot_count"] = len(slots)
    save_state(state)
    save_rows(rows)
    LOG.info("done matches=%s", matched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
