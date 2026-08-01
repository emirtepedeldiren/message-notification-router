#!/usr/bin/env bash
# Finish the submission once the daily model allowances have refilled.
#
#   ./code/resume.sh
#
# Re-routes only the messages that fell back to the rule baseline when quota
# ran out, leaves model-answered rows alone, then validates and packages.
# Safe to run more than once.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

echo "== what is already answered =="
$PYTHON - <<'PY'
import json
from collections import Counter
from pathlib import Path

path = Path("code/cache/checkpoint.json")
if not path.exists():
    print("  no checkpoint — this will be a full run")
else:
    rows = json.loads(path.read_text())
    counts = Counter(row["source"] for row in rows.values())
    model, rules = counts.get("model", 0), counts.get("rules", 0)
    print(f"  {len(rows)} rows stored: {model} answered by a model, {rules} to redo")
PY

echo
echo "== which models have allowance today =="
$PYTHON - <<'PY'
import sys
sys.path.insert(0, "code")
import config
from google import genai
from google.genai import types

client = genai.Client(api_key=config.API_KEY)
schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
available = []
for model in [config.ROUTER_MODEL, *config.ROUTER_FALLBACK_MODELS]:
    try:
        client.models.generate_content(
            model=model,
            contents=["ok=true"],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=schema, temperature=0
            ),
        )
        available.append(model)
        print(f"  {model:26s} available")
    except Exception as exc:
        state = "daily quota spent" if "PerDay" in str(exc) else "rate limited or unavailable"
        print(f"  {model:26s} {state}")

if not available:
    sys.exit("\nEvery model is still spent. Try again later — the existing output.csv remains valid.")
PY

echo
echo "== routing =="
$PYTHON -u code/main.py --checkpoint --verbose

echo
echo "== validating and packaging =="
./code/package_submission.sh
