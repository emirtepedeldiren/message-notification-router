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

# Model choice is constrained by the free tier's per-model daily allowance, so
# the two workloads deliberately sit on different models: perception runs once
# and is cached, routing is the accuracy-critical path.
# (gemini-3.6-flash allows only 20 requests/day on the free tier — unusable here.)
ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "gemini-3.5-flash")
PERCEPTION_MODEL = os.environ.get("PERCEPTION_MODEL", "gemini-3.5-flash-lite")

# Daily allowances are per model, and 110 messages can exhaust one mid-run.
# When that happens the router moves to the next model here rather than
# dropping every remaining message to the rule baseline.
ROUTER_FALLBACK_MODELS = [
    model.strip()
    for model in os.environ.get(
        "ROUTER_FALLBACK_MODELS",
        "gemini-3-flash-preview,gemini-2.5-flash,gemini-3.1-flash-lite,gemini-3.5-flash-lite",
    ).split(",")
    if model.strip()
]

# Deterministic by default so reruns reproduce the submitted output.csv.
TEMPERATURE = float(os.environ.get("ROUTER_TEMPERATURE", "0"))

# Free-tier friendly: stay well under the requests-per-minute ceiling.
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "3"))
REQUESTS_PER_MINUTE = int(os.environ.get("REQUESTS_PER_MINUTE", "8"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "4"))

# Perception sends whole images and audio files, so it is limited by the
# free tier's input-tokens-per-minute ceiling rather than its request count.
# A slower cadence here costs a few minutes once and then lives in the cache.
PERCEPTION_REQUESTS_PER_MINUTE = int(os.environ.get("PERCEPTION_REQUESTS_PER_MINUTE", "5"))

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
