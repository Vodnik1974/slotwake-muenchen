# Concierge automation

Goal: you do nothing day-to-day. Mac LaunchAgent runs every 15 minutes,
ingests FormSubmit signups (IMAP), checks München ZMS slots, emails matches,
pings you on Telegram/macOS, updates `data/waitlist.csv`.

## One-time setup

1. **Gmail App Password** (Google Account → Security → App passwords):
   - put it in `.env` as `SMTP_PASS` (and same for IMAP)
   - enable IMAP in Gmail settings

2. Copy env:
   ```bash
   cp .env.example .env
   # edit EMAIL / SMTP_USER / SMTP_PASS
   ```

3. Seed / verify:
   ```bash
   .venv/bin/python scripts/add_signup.py --email you@gmail.com --urgency 14d \
     --from 2026-08-26 --to 2026-09-20
   CONCIERGE_FORCE=1 .venv/bin/python scripts/concierge.py --dry-run
   ```

4. Install schedule:
   ```bash
   chmod +x scripts/install-launchagent.sh scripts/uninstall-launchagent.sh
   ./scripts/install-launchagent.sh
   ```

5. Leave FormSubmit activation on; new signups arrive as email → IMAP picks them up on next run (mark unread if testing).

## Tracker

File: `data/waitlist.csv`

| status | meaning |
|---|---|
| watching | active |
| alerted | got at least one slot email |
| booked | you marked manually (optional) |
| unsubscribed / expired | skipped |

Dedup of sent slot timestamps: `data/alert_state.json`

## Logs

`~/Library/Logs/slotwake-muenchen.launchd.log`

## Uninstall

```bash
./scripts/uninstall-launchagent.sh
```

## Hard rule

Never auto-book. Emails always say book on muenchen.de yourself.
