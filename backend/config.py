"""Central configuration. Reads .env once at import."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

load_dotenv(REPO_ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


FORTYGUARD_API_KEY = _get("FORTYGUARD_API_KEY")
FORTYGUARD_BASE_URL = _get("FORTYGUARD_BASE_URL", "https://api.fortyguard.com/v1")

# Heat layer selection (spec section 5, open question 2).
# 'exceedance'      — hours the temperature passes the threshold
# 'persistence'     — longest continuous run of hours past the threshold
# 'tcm'             — single temperature snapshot (weather, not climate risk)
# 'time_of_measure' — hour of day each tile peaks
# Snapshot is deliberately NOT the default: it tells you it was hot at 2pm last
# Tuesday. Exceedance tells you a location is reliably dangerous, which is what
# justifies spending public money.
FORTYGUARD_ANALYTIC_TYPE = _get("FORTYGUARD_ANALYTIC_TYPE", "exceedance")

# Threshold in °C for exceedance/persistence. The API default is 30, which is
# useless in Fresno — every tile exceeds it every daylight hour, so HEI comes
# back flat. 35 °C sits where a 30-day exceedance count actually separates
# tiles. Minqi owns the final value and it needs a citation
# (METHODOLOGY section 2); it must stay discriminating as well as defensible.
HEAT_THRESHOLD_C = float(_get("HEAT_THRESHOLD_C", "35"))
HEAT_DIRECTION = _get("HEAT_DIRECTION", "above")

# Days in the exceedance window (filter_type 4, API max is 1 month).
# This is load-bearing, not a tuning knob. Measured in Fresno on 2026-08-24:
#   single hour, peak       -> 0.38 °C spread  (0.18 °C across a typical route)
#   30-day exceedance @35°C -> 22.2 hours spread (10.5 hours across a route)
# Small temperature differences compound into large exposure differences only
# when integrated over time. A short window collapses HEI to noise.
HEAT_WINDOW_DAYS = int(_get("HEAT_WINDOW_DAYS", "30"))

# Tile size in metres. API accepts 60, 80, or 100. Finest available is best for
# 50m segments.
FORTYGUARD_GRANULARITY_M = int(_get("FORTYGUARD_GRANULARITY_M", "60"))

# Metres to buffer either side of the route when building the AOI polygon.
ROUTE_BUFFER_M = int(_get("ROUTE_BUFFER_M", "120"))

ORS_API_KEY = _get("ORS_API_KEY")
OVERPASS_URL = _get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

# Overpass sits behind Apache/mod_security and returns 406 Not Acceptable to
# requests without a descriptive User-Agent — before the query is even parsed,
# so the error looks nothing like a query problem. Identifying the client is
# also what the Overpass usage policy asks for.
USER_AGENT = _get(
    "USER_AGENT",
    "ambient-ops/0.1 (FortyGuard Hackathon 26; https://github.com/moezalikhan/ambient-ops)",
)

# --- agent model ----------------------------------------------------------
# Spec section 14.5: "whichever provides reliable tool-calling within budget".
# Budget here is zero, so every preset below is a free tier. They all speak the
# OpenAI chat-completions API, so switching provider is a base_url change.
#
#   groq       Llama 3.3 70B. Very fast (good for a live agent trace), solid
#              tool-calling, free tier ~30 req/min. Default.
#   gemini     Gemini 2.0 Flash via its OpenAI-compatible endpoint. Generous
#              free tier, reliable function calling. Best fallback.
#   cerebras   Very fast Llama, free tier.
#   openrouter Free model variants (":free" suffix), rate limited.
#   ollama     Fully local, no key, no network. Tool-calling on small models is
#              weaker — a last resort if every hosted free tier is exhausted.
LLM_PRESETS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.0-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
        "key_env": "CEREBRAS_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "key_env": "OPENROUTER_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1:8b",
        "key_env": "OLLAMA_API_KEY",
    },
}

LLM_PROVIDER = _get("LLM_PROVIDER", "groq")
_preset = LLM_PRESETS.get(LLM_PROVIDER, LLM_PRESETS["groq"])

LLM_BASE_URL = _get("LLM_BASE_URL", _preset["base_url"])
LLM_MODEL = _get("LLM_MODEL", _preset["model"])
# Provider-specific key, or a single LLM_API_KEY that overrides all of them.
LLM_API_KEY = _get("LLM_API_KEY") or _get(_preset["key_env"]) or (
    "ollama" if LLM_PROVIDER == "ollama" else ""
)

CACHE_DB_PATH = REPO_ROOT / _get("CACHE_DB_PATH", "data/ambient_ops.db")
DEMO_ROUTES_PATH = DATA_DIR / "demo_routes.json"

# Default Heat Priority Score weights (spec section 6).
# Exposed as sliders in the UI; these are the starting position, not an optimum.
DEFAULT_WEIGHTS = {
    "HEI": 0.40,  # Heat Exposure Index
    "DTF": 0.20,  # Dwell Time Factor
    "SVI": 0.20,  # Surface Vulnerability Index
    "PSI": 0.20,  # Population Sensitivity Index
}

WALKING_SPEED_MPS = 1.3  # average adult walking speed, used by DTF
SEGMENT_LENGTH_M = 50


def missing_keys() -> list[str]:
    """Which integrations are unconfigured. Surfaced at /api/health."""
    missing = []
    if not FORTYGUARD_API_KEY:
        missing.append("FORTYGUARD_API_KEY")
    if not ORS_API_KEY:
        missing.append("ORS_API_KEY")
    if not LLM_API_KEY:
        missing.append(f"{_preset['key_env']} (agent model, provider={LLM_PROVIDER})")
    return missing
