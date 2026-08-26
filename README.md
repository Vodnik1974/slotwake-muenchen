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

## Waitlist → alerts

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export STARNBERG_TERMIN_ROOT=/Users/Inna/Projects/starnberg-termin
# put signups in data/waitlist.csv
.venv/bin/python scripts/notify_once.py
```

Optional: `SEND_WEBHOOK_URL` in `.env`.

## Go-to-market

`docs/gtm.md` · `docs/posts.md`

## Hard rules

- No auto-book · no sold slots · not on fs-hilfe checkout · no `ACTIVE_SNIPER_IDS` without a decision
