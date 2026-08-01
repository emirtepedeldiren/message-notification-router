#!/usr/bin/env bash
# Produce an improved run once the daily model allowances have refilled,
# without risking the predictions already in hand.
#
#   ./code/resume.sh
#
# The current output.csv was answered by a model on every row. A fresh run can
# only be an improvement if it manages that too, so this routes into a
# candidate file and promotes it only when every row came from a model.
# Otherwise the existing predictions stay exactly as they are.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

CANDIDATE="output_candidate.csv"
CANDIDATE_CHECKPOINT="code/cache/checkpoint_candidate.json"

echo "== predictions currently held =="
$PYTHON - <<'PY'
import csv
from collections import Counter
from pathlib import Path

if not Path("output.csv").exists():
    print("  none yet — this will be the first run")
else:
    rows = list(csv.DictReader(open("output.csv", encoding="utf-8")))
    counts = Counter(r["action"] for r in rows)
    print(f"  {len(rows)} rows — " + ", ".join(f"{a}: {counts.get(a, 0)}" for a in ("notify", "digest", "mute")))
PY

echo
echo "== model allowances today =="
$PYTHON - <<'PY'
import sys
sys.path.insert(0, "code")
import config
from google import genai
from google.genai import types

client = genai.Client(api_key=config.API_KEY)
schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
available = 0
for model in [config.ROUTER_MODEL, *config.ROUTER_FALLBACK_MODELS]:
    try:
        client.models.generate_content(
            model=model,
            contents=["ok=true"],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=schema, temperature=0
            ),
        )
        available += 1
        print(f"  {model:26s} available")
    except Exception as exc:
        print(f"  {model:26s} {'daily quota spent' if 'PerDay' in str(exc) else 'rate limited'}")

if available == 0:
    sys.exit("\nEvery model is still spent. The existing output.csv is untouched and remains valid.")
PY

echo
echo "== routing a fresh candidate =="
rm -f "$CANDIDATE_CHECKPOINT"
$PYTHON -u code/main.py --checkpoint "$CANDIDATE_CHECKPOINT" --output "$CANDIDATE" --verbose

echo
echo "== deciding whether to promote =="
$PYTHON - <<'PY'
import csv, json, shutil, sys
from collections import Counter
from pathlib import Path

checkpoint = json.loads(Path("code/cache/checkpoint_candidate.json").read_text())
sources = Counter(row["source"] for row in checkpoint.values())
rules = sources.get("rules", 0)
total = len(checkpoint)

print(f"  candidate: {total} rows, {sources.get('model', 0)} model-answered, {rules} on the rule baseline")

if rules:
    print(f"  NOT promoting — {rules} row(s) fell back, which would be a regression.")
    print("  output.csv is unchanged. Re-run later when allowances have refilled.")
    sys.exit(0)

before = list(csv.DictReader(open("output.csv", encoding="utf-8"))) if Path("output.csv").exists() else []
after = list(csv.DictReader(open("output_candidate.csv", encoding="utf-8")))
if before:
    changed = sum(
        1
        for a, b in zip(sorted(before, key=lambda r: r["message_id"]), sorted(after, key=lambda r: r["message_id"]))
        if (a["action"], a["message_type"]) != (b["action"], b["message_type"])
    )
    print(f"  {changed} row(s) differ from the previous predictions")

shutil.copy("output_candidate.csv", "output.csv")
print("  promoted to output.csv")
PY

echo
echo "== validating and packaging =="
./code/package_submission.sh
