#!/usr/bin/env bash
# Builds the three files HackerRank asks for and checks them before you upload.
#
#   ./code/package_submission.sh
#
# Produces code.zip in the repository root, verifies output.csv against
# dataset/messages.csv, and points at the chat transcript.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OUTPUT="output.csv"
ZIP="code.zip"
LOG="$HOME/hackerrank_orchestrate_august26/log.txt"

echo "== validating $OUTPUT =="
python3 - <<'PY'
import csv, sys
from pathlib import Path

EXPECTED = ["message_id", "action", "message_type", "reason", "confidence", "evidence_message_ids"]
ACTIONS = {"notify", "digest", "mute"}
TYPES = {
    "personal", "urgent", "event", "payment", "business_update", "promotion",
    "greeting", "forward", "spam", "scam", "unknown",
}

def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)

if not Path("output.csv").exists():
    sys.exit("output.csv is missing — run: python code/main.py")

columns, rows = read("output.csv")
_, messages = read("dataset/messages.csv")
history_ids = {r["message_id"] for r in read("dataset/message_history.csv")[1]}

problems = []
if columns != EXPECTED:
    problems.append(f"columns are {columns}, expected {EXPECTED}")

expected_ids = [m["message_id"] for m in messages]
got_ids = [r["message_id"] for r in rows]
if len(got_ids) != len(set(got_ids)):
    problems.append("duplicate message_id rows")
missing = set(expected_ids) - set(got_ids)
extra = set(got_ids) - set(expected_ids)
if missing:
    problems.append(f"{len(missing)} message(s) have no prediction: {sorted(missing)[:5]}")
if extra:
    problems.append(f"{len(extra)} unexpected message_id(s): {sorted(extra)[:5]}")

for row in rows:
    mid = row["message_id"]
    if row["action"] not in ACTIONS:
        problems.append(f"{mid}: action {row['action']!r} is not allowed")
    if row["message_type"] not in TYPES:
        problems.append(f"{mid}: message_type {row['message_type']!r} is not allowed")
    if not row["reason"].strip():
        problems.append(f"{mid}: empty reason")
    try:
        confidence = float(row["confidence"])
        if not 0.0 <= confidence <= 1.0:
            problems.append(f"{mid}: confidence {confidence} outside 0-1")
    except ValueError:
        problems.append(f"{mid}: confidence {row['confidence']!r} is not a number")
    evidence = row["evidence_message_ids"].strip()
    if not evidence:
        problems.append(f"{mid}: evidence is blank — use 'none'")
    elif evidence != "none":
        unknown = [e for e in evidence.split(";") if e not in history_ids]
        if unknown:
            problems.append(f"{mid}: evidence ids not in message_history: {unknown}")

if problems:
    print(f"FAILED with {len(problems)} problem(s):")
    for problem in problems[:20]:
        print(f"  - {problem}")
    sys.exit(1)

print(f"  {len(rows)} rows, one per message, schema and value ranges all valid")
PY

echo
echo "== building $ZIP =="
rm -f "$ZIP"
# Ship the runnable solution and its cache; leave out the corpus, the venv,
# build artefacts, and anything holding a secret.
zip -q -r "$ZIP" code \
  -x 'code/**/__pycache__/*' \
     'code/**/*.pyc' \
     'code/.pytest_cache/*' \
     'code/cache/llm/*' \
     'code/cache/checkpoint.json'
zip -q "$ZIP" .env.example
echo "  $(du -h "$ZIP" | cut -f1)  $ZIP"
unzip -l "$ZIP" | tail -1

echo
echo "== secret scan =="
if unzip -p "$ZIP" | grep -qE 'AQ\.[A-Za-z0-9]{10}|AIza[A-Za-z0-9_-]{30}'; then
  echo "  REFUSING: the archive contains something shaped like an API key"
  exit 1
fi
echo "  no API keys found in the archive"

echo
echo "== upload these =="
echo "  1. code.zip      $REPO_ROOT/$ZIP"
echo "  2. predictions   $REPO_ROOT/$OUTPUT"
echo "  3. transcript    $LOG"
[ -f "$LOG" ] || echo "     WARNING: transcript not found at $LOG"
