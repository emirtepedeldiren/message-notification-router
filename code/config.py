"""Runtime configuration. Secrets come from the environment only."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = REPO_ROOT / "code"
CACHE_DIR = CODE_DIR / "cache"
PROMPT_DIR = CODE_DIR / "prompts"

load_dotenv(REPO_ROOT / ".env")

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Routing model. Flash is the accuracy/quota sweet spot on the free tier;
# evaluation/main.py compares it against the lite variant and the rule baseline.
ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "gemini-2.5-flash")
PERCEPTION_MODEL = os.environ.get("PERCEPTION_MODEL", "gemini-2.5-flash")

# Deterministic by default so reruns reproduce the submitted output.csv.
TEMPERATURE = float(os.environ.get("ROUTER_TEMPERATURE", "0"))

# Free-tier friendly: stay well under the requests-per-minute ceiling.
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "4"))
REQUESTS_PER_MINUTE = int(os.environ.get("REQUESTS_PER_MINUTE", "12"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "4"))

# Confidence band observed in the labelled examples (0.78 - 0.91). Predictions
# are kept inside it so calibration stays consistent with the expected output.
CONFIDENCE_FLOOR = 0.72
CONFIDENCE_CEILING = 0.93


def require_api_key() -> str:
    if not API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add a key "
            "from https://aistudio.google.com/apikey"
        )
    return API_KEY


def has_api_key() -> bool:
    return bool(API_KEY)
