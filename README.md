# SlotWake München

**Separate product from [fs-hilfe.de](https://fs-hilfe.de/).**  
Notify-only alerts for München Bürgerbüro appointments (Anmeldung / Ausweis / Pass).  
Users book themselves on [muenchen.de](https://stadt.muenchen.de/buergerservice/terminvereinbarung.html). We do not book for them.

## Live

- Site: https://vodnik1974.github.io/slotwake-muenchen/
- Waitlist: FormSubmit → notify email (activate via Confirm link on first test submit)

## Stack

| Piece | Where |
|---|---|
| Landing + waitlist form | this repo (`index.html`) |
| Hosting | GitHub Pages |
| ZMS listing / census | sibling `../starnberg-termin` (`muenchen-anmeldung`, notify-only) |
| Public brand | SlotWake — not on fs-hilfe checkout |

## Deploy

```bash
git push origin main
# Pages: Settings → Pages → branch `main` / root
```

Local preview: `python3 -m http.server 8080`

## Waitlist → alerts (automated)

Concierge runs every **15 minutes** via LaunchAgent (06:00–19:00 Berlin).

```bash
# one-time
cp .env.example .env   # set SMTP_PASS = Gmail App Password
./scripts/install-launchagent.sh

# manual
CONCIERGE_FORCE=1 .venv/bin/python scripts/concierge.py --dry-run
```

See `docs/concierge.md`. Tracker: `data/waitlist.csv`.

## Go-to-market

`docs/gtm.md` · `docs/posts.md`

## Hard rules

- No auto-book · no sold slots · not on fs-hilfe checkout · no `ACTIVE_SNIPER_IDS` without a decision
