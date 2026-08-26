#!/usr/bin/env bash
# Push public stats.json to GitHub Pages (no emails, aggregate counts only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f stats.json ]]; then
  echo "stats.json missing — run concierge first:" >&2
  echo "  CONCIERGE_FORCE=1 .venv/bin/python scripts/concierge.py --dry-run" >&2
  exit 1
fi

git add stats.json
if git diff --cached --quiet stats.json; then
  echo "stats.json unchanged — nothing to push"
  exit 0
fi

git commit -m "$(cat <<'EOF'
Update public waitlist stats for /stats page.

Aggregate subscriber counts only — no personal data.
EOF
)"
git push origin HEAD
echo "Published: $(git remote get-url origin 2>/dev/null || echo origin)/stats.html"
